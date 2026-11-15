"""FastAPI application: REST API + the built React dashboard."""

from __future__ import annotations

import json
import logging
import os
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..analyzer import MeetingAnalyzer
from ..config import EDITABLE, Settings, public_settings, update_settings
from ..recorder import AudioRecorder, RecordingError, default_source, list_devices
from ..meet_joiner import normalize_meet_link, signed_in_account
from ..transcriber import Transcriber
from ..recorder import audio_duration
from . import sample
from .db import ACTIVE_STATUSES, Database
from .bot_login import BotLogin
from .worker import JobRunner

log = logging.getLogger(__name__)

AUDIO_EXT = {".wav", ".mp3", ".m4a", ".mp4", ".webm", ".ogg", ".flac", ".mpeg", ".mpga"}
TEXT_EXT = {".txt", ".vtt", ".srt"}

settings = Settings.from_env(os.environ.get("INTELLIMEET_ENV"))
db = Database(settings.database_path)
runner: Optional[JobRunner] = None
bot_login: Optional[BotLogin] = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global runner, bot_login
    from ..recorder import preload

    preload()  # soundcard must be imported before COM is touched on Windows
    db.fail_interrupted()
    runner = JobRunner(settings, db)
    bot_login = BotLogin(settings, runner.login_active)
    yield


app = FastAPI(title="IntelliMeet API", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------- serializers
def _meeting(row, full: bool = False) -> dict:
    analysis = json.loads(row["analysis_json"]) if row["analysis_json"] else None
    d = {
        "id": row["id"],
        "title": row["title"],
        "source": row["source"],
        "meet_link": row["meet_link"],
        "status": row["status"],
        "stage_message": row["stage_message"],
        "progress": row["progress"],
        "duration_requested": row["duration_requested"],
        "duration_seconds": row["duration_seconds"],
        "analyze": bool(row["analyze"]),
        "original_filename": row["original_filename"],
        "has_audio": bool(row["audio_path"]) and Path(row["audio_path"]).exists()
        and Path(row["audio_path"]).suffix.lower() in AUDIO_EXT,
        "error": row["error"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
    }
    if full:
        ap = Path(row["audio_path"]) if row["audio_path"] else None
        d["can_reprocess"] = bool(ap and ap.exists() and (ap.suffix.lower() in TEXT_EXT or (audio_duration(ap) or 0) >= 5))
        d["analysis"] = analysis
        d["transcript"] = json.loads(row["transcript_json"]) if row["transcript_json"] else None
        d["events"] = db.events(row["id"])
    else:
        items = (analysis or {}).get("action_items", [])
        d["summary"] = (analysis or {}).get("summary")
        d["topics"] = (analysis or {}).get("topics", [])
        d["sentiment"] = (analysis or {}).get("sentiment")
        d["action_items_total"] = len(items)
        d["action_items_open"] = sum(not i.get("done") for i in items)
    return d


def _get(mid: str):
    row = db.get_meeting_row(mid)
    if not row:
        raise HTTPException(404, "Meeting not found")
    return row


# ---------------------------------------------------------------------- system
@app.get("/api/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/api/config")
def config():
    analyzer = MeetingAnalyzer(settings)
    transcriber = Transcriber(settings)
    return {
        "version": __version__,
        "transcriber": {"provider": transcriber.provider, "configured": transcriber.is_configured(),
                        "model": settings.whisper_model if transcriber.provider == "openai" else settings.local_whisper_model},
        "analyzer": {"provider": analyzer.provider,
                     "model": {"openai": settings.gpt_model, "gemini": settings.gemini_model}.get(analyzer.provider, "rule-based"),
                     "configured": analyzer.provider != "basic"},
        "audio": {
            "source": settings.audio_source or default_source(),
            "device": str(settings.audio_device) if settings.audio_device is not None else None,
        },
        "bot": {
            "display_name": settings.bot_display_name,
            "chrome_profile": signed_in_account(settings) is not None,
            "account": signed_in_account(settings),
            "google_credentials": bool(settings.email and settings.password),
            "headless": settings.headless,
            "audio_device": str(settings.audio_device) if settings.audio_device is not None else None,
            "default_duration": settings.duration,
        },
        "ffmpeg": bool(shutil.which("ffmpeg")),
    }


@app.get("/api/stats")
def stats():
    rows = db.list_meeting_rows()
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    completed = [r for r in rows if r["status"] == "completed"]
    open_items = 0
    scores = []
    for r in completed:
        a = json.loads(r["analysis_json"]) if r["analysis_json"] else {}
        open_items += sum(not i.get("done") for i in a.get("action_items", []))
        if a.get("sentiment"):
            scores.append(a["sentiment"].get("score", 0))
    return {
        "total_meetings": len(rows),
        "completed_meetings": len(completed),
        "meetings_this_week": sum(r["created_at"] >= week_ago for r in rows),
        "total_seconds": sum(r["duration_seconds"] or 0 for r in completed),
        "open_action_items": open_items,
        "average_sentiment": round(sum(scores) / len(scores), 2) if scores else None,
        "active_jobs": sum(r["status"] in ACTIVE_STATUSES for r in rows),
    }


# -------------------------------------------------------------------- meetings
class BotRequest(BaseModel):
    meet_link: str
    title: Optional[str] = None
    duration_minutes: float = Field(default=30, gt=0, le=240)
    analyze: bool = True


@app.get("/api/meetings")
def list_meetings(q: str = "", status: str = ""):
    return [_meeting(r) for r in db.list_meeting_rows(q.strip(), status)]


@app.post("/api/meetings", status_code=201)
def create_bot_meeting(req: BotRequest):
    try:
        link = normalize_meet_link(req.meet_link)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    title = (req.title or "").strip()
    mid = db.create_meeting(
        title=title or f"Google Meet · {link.rsplit('/', 1)[-1].split('?')[0]}",
        title_is_auto=0 if title else 1,
        source="bot",
        meet_link=link,
        stage_message="Waiting for the bot",
        duration_requested=int(req.duration_minutes * 60),
        analyze=int(req.analyze),
    )
    db.add_event(mid, "queued", "Bot request queued")
    runner.submit_bot(mid)
    return _meeting(_get(mid), full=True)


@app.post("/api/meetings/upload", status_code=201)
async def upload_meeting(file: UploadFile = File(...), title: str = Form(""), analyze: bool = Form(True)):
    name = Path(file.filename or "recording").name
    ext = Path(name).suffix.lower()
    if ext not in AUDIO_EXT | TEXT_EXT:
        raise HTTPException(422, f"Unsupported file type '{ext}'. Upload audio ({', '.join(sorted(AUDIO_EXT))}) or a transcript (.txt, .vtt, .srt).")
    title = title.strip()
    mid = db.create_meeting(
        title=title or Path(name).stem.replace("_", " ").replace("-", " ").strip().title() or "Uploaded meeting",
        title_is_auto=0 if title else 1,
        source="upload",
        stage_message="Upload received",
        analyze=int(analyze),
        original_filename=name,
    )
    dest = settings.data_dir / "uploads" / f"{mid}{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)
    db.update_meeting(mid, audio_path=str(dest))
    db.add_event(mid, "queued", f"Uploaded {name}")
    runner.submit_processing(mid)
    return _meeting(_get(mid), full=True)


@app.get("/api/meetings/{mid}")
def get_meeting(mid: str):
    return _meeting(_get(mid), full=True)


class MeetingPatch(BaseModel):
    title: Optional[str] = None


@app.patch("/api/meetings/{mid}")
def patch_meeting(mid: str, patch: MeetingPatch):
    _get(mid)
    if patch.title is not None and patch.title.strip():
        db.update_meeting(mid, title=patch.title.strip(), title_is_auto=0)
    return _meeting(_get(mid), full=True)


@app.delete("/api/meetings/{mid}", status_code=204)
def delete_meeting(mid: str):
    row = _get(mid)
    if row["status"] in ACTIVE_STATUSES and row["status"] != "queued":
        raise HTTPException(409, "Stop the meeting before deleting it")
    runner.stop(mid)
    if row["audio_path"]:
        Path(row["audio_path"]).unlink(missing_ok=True)
    db.delete_meeting(mid)


@app.post("/api/meetings/{mid}/stop")
def stop_meeting(mid: str):
    row = _get(mid)
    if row["status"] not in ("queued", "joining", "recording"):
        raise HTTPException(409, "Only a queued, joining or recording meeting can be stopped")
    runner.stop(mid)
    db.add_event(mid, row["status"], "Stop requested")
    return _meeting(_get(mid), full=True)


@app.post("/api/meetings/{mid}/retry")
def retry_meeting(mid: str, mode: str = "auto"):
    """mode: auto | rejoin (send the bot again) | reprocess (re-run transcription/analysis)
    | reanalyze (re-run only the AI summary on the saved transcript)."""
    row = _get(mid)
    if mode == "reanalyze":
        if not row["transcript_json"]:
            raise HTTPException(409, "This meeting has no transcript yet")
        if row["status"] in ACTIVE_STATUSES:
            raise HTTPException(409, "This meeting is still being processed")
        db.add_event(mid, "analyzing", "Summary regeneration requested")
        runner.submit_reanalysis(mid)
        return _meeting(_get(mid), full=True)
    if row["status"] not in ("failed", "cancelled", "completed"):
        raise HTTPException(409, "This meeting is still being processed")
    audio = Path(row["audio_path"]) if row["audio_path"] else None
    has_audio = bool(audio and audio.exists() and (audio.suffix.lower() in TEXT_EXT or (audio_duration(audio) or 0) >= 5))
    if mode == "auto":
        mode = "reprocess" if has_audio and not (row["source"] == "bot" and row["status"] == "cancelled") else "rejoin"
    if mode == "rejoin" and row["source"] != "bot":
        raise HTTPException(409, "Only bot meetings can be re-joined; upload the file again")
    if mode == "reprocess" and not has_audio:
        raise HTTPException(409, "There is no usable recording to re-process")
    db.update_meeting(mid, status="queued", error=None, progress=0, completed_at=None, started_at=None,
                      stage_message="Sending the bot again" if mode == "rejoin" else "Re-processing recording")
    db.add_event(mid, "queued", "Bot sent again" if mode == "rejoin" else "Re-processing requested")
    if mode == "rejoin":
        if audio:
            audio.unlink(missing_ok=True)
        db.update_meeting(mid, audio_path=None, transcript=None, analysis=None, duration_seconds=None)
        runner.submit_bot(mid)
    else:
        runner.submit_processing(mid)
    return _meeting(_get(mid), full=True)


class ActionItemPatch(BaseModel):
    done: bool


@app.patch("/api/meetings/{mid}/action-items/{index}")
def toggle_action_item(mid: str, index: int, patch: ActionItemPatch):
    row = _get(mid)
    analysis = json.loads(row["analysis_json"]) if row["analysis_json"] else None
    if not analysis or not (0 <= index < len(analysis.get("action_items", []))):
        raise HTTPException(404, "Action item not found")
    analysis["action_items"][index]["done"] = patch.done
    db.update_meeting(mid, analysis=analysis)
    return analysis["action_items"][index]


@app.get("/api/action-items")
def all_action_items(status: str = "open"):
    out = []
    for r in db.list_meeting_rows(status="completed"):
        a = json.loads(r["analysis_json"]) if r["analysis_json"] else {}
        for i, it in enumerate(a.get("action_items", [])):
            if status == "open" and it.get("done"):
                continue
            out.append({**it, "index": i, "meeting_id": r["id"], "meeting_title": r["title"], "meeting_date": r["created_at"]})
    return out


@app.get("/api/meetings/{mid}/audio")
def meeting_audio(mid: str):
    row = _get(mid)
    path = Path(row["audio_path"] or "")
    if not row["audio_path"] or not path.exists() or path.suffix.lower() not in AUDIO_EXT:
        raise HTTPException(404, "No audio for this meeting")
    return FileResponse(path)


@app.get("/api/meetings/{mid}/export")
def export_meeting(mid: str, format: str = "md"):
    m = _meeting(_get(mid), full=True)
    slug = "".join(c if c.isalnum() else "-" for c in m["title"].lower()).strip("-")[:60] or "meeting"
    if format == "json":
        return PlainTextResponse(
            json.dumps(m, indent=2), media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{slug}.json"'},
        )
    a = m.get("analysis") or {}
    lines = [f"# {m['title']}", "", f"*Date:* {m['created_at'][:16].replace('T', ' ')} UTC  "]
    if m.get("duration_seconds"):
        lines.append(f"*Duration:* {int(m['duration_seconds'] // 60)} min {int(m['duration_seconds'] % 60)} s  ")
    if m.get("meet_link"):
        lines.append(f"*Meeting link:* {m['meet_link']}")
    if a:
        lines += ["", "## Summary", "", a.get("summary", "")]
        if a.get("key_points"):
            lines += ["", "## Key points", ""] + [f"- {p}" for p in a["key_points"]]
        if a.get("decisions"):
            lines += ["", "## Decisions", ""] + [f"- {p}" for p in a["decisions"]]
        if a.get("action_items"):
            lines += ["", "## Action items", ""]
            for it in a["action_items"]:
                meta = ", ".join(x for x in (it.get("owner"), f"due {it['due']}" if it.get("due") else None) if x)
                lines.append(f"- [{'x' if it.get('done') else ' '}] {it['task']}" + (f" ({meta})" if meta else ""))
        s = a.get("sentiment") or {}
        if s:
            lines += ["", "## Sentiment", "", f"**{s.get('label', '').title()}** ({s.get('score', 0):+.2f}) - {s.get('explanation', '')}"]
    t = m.get("transcript") or {}
    if t.get("segments"):
        lines += ["", "## Transcript", ""]
        for seg in t["segments"]:
            ts = f"{int(seg['start'] // 60):02d}:{int(seg['start'] % 60):02d}"
            who = f"**{seg['speaker']}:** " if seg.get("speaker") else ""
            lines.append(f"[{ts}] {who}{seg['text']}  ")
    return PlainTextResponse(
        "\n".join(lines) + "\n", media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{slug}.md"'},
    )


# ------------------------------------------------------------------------ chat
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@app.get("/api/meetings/{mid}/chat")
def get_chat(mid: str):
    _get(mid)
    return db.chat(mid)


@app.post("/api/meetings/{mid}/chat")
def post_chat(mid: str, req: ChatRequest):
    row = _get(mid)
    if not row["transcript_json"]:
        raise HTTPException(409, "This meeting has no transcript yet")
    transcript = json.loads(row["transcript_json"])
    analysis = json.loads(row["analysis_json"]) if row["analysis_json"] else None
    history = db.chat(mid)
    db.add_chat(mid, "user", req.message.strip())
    text = "\n".join(
        (f"{s['speaker']}: " if s.get("speaker") else "") + s["text"] for s in transcript.get("segments") or []
    ) or transcript.get("text", "")
    try:
        answer = MeetingAnalyzer(settings).answer(req.message.strip(), text, analysis, history)
    except Exception as exc:  # noqa: BLE001
        log.exception("chat failed")
        answer = f"Sorry, I couldn't reach the AI provider: {exc}"
    return db.add_chat(mid, "assistant", answer)


@app.delete("/api/meetings/{mid}/chat", status_code=204)
def clear_chat(mid: str):
    _get(mid)
    db.clear_chat(mid)


# ---------------------------------------------------------------- settings
@app.get("/api/settings")
def get_settings():
    return {"values": public_settings(settings), "env_path": str(settings.env_path),
            "default_audio_source": default_source()}


@app.put("/api/settings")
def put_settings(changes: dict):
    unknown = [k for k in changes if k not in EDITABLE]
    if unknown:
        raise HTTPException(422, f"Unknown settings: {', '.join(unknown)}")
    try:
        if "duration" in changes and not (10 <= int(changes["duration"]) <= 4 * 3600):
            raise ValueError("Recording length must be between 10 seconds and 4 hours")
        if "admit_timeout" in changes and not (30 <= int(changes["admit_timeout"]) <= 3600):
            raise ValueError("Admit timeout must be between 30 seconds and 1 hour")
        for k in ("transcriber", "analyzer", "audio_source"):
            allowed = {"transcriber": {"openai", "local"}, "analyzer": {"auto", "openai", "gemini", "basic"},
                       "audio_source": {"", "loopback", "device"}}[k]
            if k in changes and str(changes[k]).lower() not in allowed:
                raise ValueError(f"Invalid value for {k}")
        saved = update_settings(settings, changes)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"Couldn't write {settings.env_path}: {exc}") from exc
    return {"saved": saved, "values": public_settings(settings)}


@app.post("/api/settings/test-ai")
def test_ai():
    analyzer = MeetingAnalyzer(settings)
    if analyzer.provider == "basic":
        return {"ok": True, "provider": "basic", "message": "Offline analyzer - no API key needed."}
    try:
        reply = analyzer._chat(analyzer.provider, [{"role": "user", "content": "Reply with the single word: ready"}])
        return {"ok": True, "provider": analyzer.provider, "message": f"Connected - model replied: {reply.strip()[:40]}"}
    except Exception as exc:  # noqa: BLE001
        msg = str(exc) or exc.__class__.__name__
        if "timed out" in msg.lower() or "timeout" in exc.__class__.__name__.lower():
            msg = ("No reply from the AI service within 90 s. The network may be blocking it "
                   "(college Wi-Fi often does) - try a mobile hotspot.")
        return {"ok": False, "provider": analyzer.provider, "message": msg[:300]}


@app.get("/api/audio/devices")
def audio_devices():
    return list_devices()


class AudioTest(BaseModel):
    seconds: float = Field(default=5, ge=1, le=15)
    audio_source: Optional[str] = None
    audio_device: Optional[str] = None


@app.post("/api/audio/test")
def audio_test(req: AudioTest):
    if runner.bot_busy:
        raise HTTPException(409, "The bot is recording a meeting right now")
    from dataclasses import replace

    s = replace(settings)
    if req.audio_source is not None:
        s.audio_source = req.audio_source
    if req.audio_device is not None:
        s.audio_device = req.audio_device or None
    out = settings.data_dir / "debug" / "audio-test.wav"
    try:
        stats = AudioRecorder(s).record(out, req.seconds)
    except RecordingError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Audio test failed: {exc}") from exc
    return {**stats.to_dict(), "url": "/api/audio/test.wav"}


@app.get("/api/audio/test.wav")
def audio_test_file():
    f = settings.data_dir / "debug" / "audio-test.wav"
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="audio/wav", headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------- bot sign-in
@app.get("/api/bot/status")
def bot_status():
    return bot_login.status()


@app.post("/api/bot/login")
def bot_sign_in():
    if runner.bot_busy:
        raise HTTPException(409, "The bot is in a meeting right now. Try again when it has finished.")
    try:
        bot_login.start()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return bot_login.status()


@app.post("/api/bot/login/cancel")
def bot_sign_in_cancel():
    bot_login.cancel()
    return bot_login.status()


@app.post("/api/bot/logout")
def bot_sign_out():
    if runner.bot_busy:
        raise HTTPException(409, "The bot is in a meeting right now.")
    try:
        bot_login.sign_out()
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return bot_login.status()


# ---------------------------------------------------------------------- sample
@app.post("/api/sample", status_code=201)
def load_sample():
    return {"ids": sample.seed(db)}


# ------------------------------------------------------------------- frontend
def _frontend_dir() -> Optional[Path]:
    candidates = [os.environ.get("FRONTEND_DIST"), Path(__file__).resolve().parents[3] / "frontend" / "dist",
                  Path.cwd() / "frontend" / "dist"]
    for c in candidates:
        if c and (Path(c) / "index.html").exists():
            return Path(c)
    return None


_dist = _frontend_dir()
if _dist:
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        f = _dist / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(_dist / "index.html")
