"""Background job runner.

Bot jobs run one at a time (a single Chrome window and audio device), uploads are
processed on a small thread pool so they never wait behind a live meeting.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config import Settings
from ..pipeline import process_audio, record_meeting
from ..recorder import audio_duration
from .db import Database, now

log = logging.getLogger(__name__)

STAGE_PROGRESS = {"queued": 0.0, "joining": 0.1, "recording": 0.2, "transcribing": 0.75, "analyzing": 0.9, "completed": 1.0}


class JobRunner:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self._bot_queue: "queue.Queue[str]" = queue.Queue()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="process")
        self._stops: dict[str, threading.Event] = {}
        self._busy = threading.Event()
        self.login_active = threading.Event()  # set while the sign-in window is open
        self._thread = threading.Thread(target=self._bot_loop, name="bot-worker", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------- public API
    def submit_bot(self, mid: str) -> None:
        self._stops[mid] = threading.Event()
        self._bot_queue.put(mid)

    def submit_processing(self, mid: str) -> None:
        self._pool.submit(self._process_job, mid)

    def submit_reanalysis(self, mid: str) -> None:
        self._pool.submit(self._reanalyze_job, mid)

    def _reanalyze_job(self, mid: str) -> None:
        """Re-run only the AI summary on the saved transcript (no re-transcription)."""
        import json

        from ..analyzer import MeetingAnalyzer

        row = self.db.get_meeting_row(mid)
        if not row or not row["transcript_json"]:
            return
        prev_status = row["status"]
        self._stage(mid, "analyzing", "Regenerating summary and action items")
        try:
            t = json.loads(row["transcript_json"])
            text = "\n".join((f"{x['speaker']}: " if x.get("speaker") else "") + x["text"] for x in t.get("segments") or []) or t.get("text", "")
            analysis = MeetingAnalyzer(self.settings).analyze(text)
        except Exception as exc:  # noqa: BLE001
            if prev_status == "completed":
                self.db.update_meeting(mid, status="completed", progress=1.0, stage_message="Meeting processed")
                self.db.add_event(mid, "failed", f"Regenerating the summary failed: {friendly_error(exc)}")
            else:
                self._fail(mid, exc)
            return
        fields = {"analysis": analysis, "completed_at": now()}
        if row["title_is_auto"] and analysis.get("title"):
            fields["title"] = analysis["title"]
        self.db.update_meeting(mid, **fields)
        self._stage(mid, "completed", "Summary regenerated" + (" (offline - AI unavailable)" if analysis.get("warning") else ""))

    def stop(self, mid: str) -> bool:
        """Stop recording early (keeps what was recorded) or cancel a queued job."""
        ev = self._stops.get(mid)
        if not ev:
            return False
        ev.set()
        return True

    # --------------------------------------------------------------- internals
    def _stage(self, mid: str, stage: str, message: str) -> None:
        fields = {"status": stage, "stage_message": message}
        if stage in STAGE_PROGRESS:
            fields["progress"] = STAGE_PROGRESS[stage]
        self.db.update_meeting(mid, **fields)
        self.db.add_event(mid, stage, message)

    def _bot_loop(self) -> None:
        while True:
            mid = self._bot_queue.get()
            try:
                self._bot_job(mid)
            except Exception:  # noqa: BLE001
                log.exception("bot job crashed")
            finally:
                self._stops.pop(mid, None)

    @property
    def bot_busy(self) -> bool:
        return self._busy.is_set()

    def _bot_job(self, mid: str) -> None:
        self._busy.set()
        try:
            self._bot_job_inner(mid)
        finally:
            self._busy.clear()

    def _bot_job_inner(self, mid: str) -> None:
        row = self.db.get_meeting_row(mid)
        if not row:
            return
        stop = self._stops.get(mid) or threading.Event()
        if self.login_active.is_set():
            self._stage(mid, "queued", "Waiting for the Google sign-in window to be closed")
        while self.login_active.is_set() and not stop.is_set():
            time.sleep(2)
        if stop.is_set():
            self._stage(mid, "cancelled", "Cancelled before the bot joined")
            return
        self.db.update_meeting(mid, started_at=now())
        audio = Path(self.settings.data_dir) / "recordings" / f"{mid}.wav"
        duration = int(row["duration_requested"] or self.settings.duration)

        def on_progress(frac: float) -> None:
            # recording spans 0.2 -> 0.7 of the overall bar
            self.db.update_meeting(mid, progress=round(0.2 + 0.5 * frac, 3))

        try:
            stats = record_meeting(
                self.settings,
                row["meet_link"],
                duration,
                audio,
                on_stage=lambda st, msg: self._stage(mid, st, msg),
                stop_event=stop,
                on_progress=on_progress,
                tag=mid,
            )
        except Exception as exc:  # noqa: BLE001
            got = audio_duration(audio) if audio.exists() else None
            if stop.is_set() and not got:
                self._stage(mid, "cancelled", "Cancelled by user")
                return
            if not got or got < 5:
                audio.unlink(missing_ok=True)
                self._fail(mid, exc)
                return
            # Something broke mid-meeting but we have real audio: keep it and process it.
            log.warning("bot error after %.0fs of recording; processing what we have: %s", got, exc)
            self.db.add_event(mid, "recording", f"Recording ended early: {friendly_error(exc)}")
        else:
            if stats.seconds < 3:
                audio.unlink(missing_ok=True)
                self._fail(mid, RuntimeError("The bot left the meeting right after joining, so nothing was recorded."))
                return
            if stats.silent:
                self.db.update_meeting(mid, audio_path=str(audio))
                self._fail(mid, RuntimeError(
                    f"The recording ({int(stats.seconds)} s from {stats.source}) is completely silent. "
                    "Open Settings -> Audio capture, run 'Test audio' while something is playing, and pick the "
                    "speaker/device that shows a level."))
                return
            self.db.add_event(mid, "recording", f"Recorded {int(stats.seconds)} s from {stats.source}")
        if stop.is_set():
            self.db.add_event(mid, "recording", "Recording stopped early by user")
        self.db.update_meeting(mid, audio_path=str(audio))
        self._process_job(mid)

    def _process_job(self, mid: str) -> None:
        row = self.db.get_meeting_row(mid)
        if not row or not row["audio_path"]:
            return
        if not row["started_at"]:
            self.db.update_meeting(mid, started_at=now())
        try:
            result = process_audio(
                self.settings,
                Path(row["audio_path"]),
                on_stage=lambda st, msg: self._stage(mid, st, msg),
                analyze=bool(row["analyze"]),
            )
        except Exception as exc:  # noqa: BLE001
            self._fail(mid, exc)
            return
        fields = {
            "transcript": result["transcript"],
            "analysis": result["analysis"],
            "duration_seconds": result.get("duration_seconds"),
            "completed_at": now(),
        }
        if row["title_is_auto"] and result["analysis"] and result["analysis"].get("title"):
            fields["title"] = result["analysis"]["title"]
        self.db.update_meeting(mid, **fields)
        self._stage(mid, "completed", "Meeting processed")

    def _fail(self, mid: str, exc: Exception) -> None:
        log.error("job %s failed: %s\n%s", mid, exc, traceback.format_exc())
        msg = friendly_error(exc)
        self.db.update_meeting(mid, status="failed", error=msg, completed_at=now())
        self.db.add_event(mid, "failed", msg)


def friendly_error(exc: Exception) -> str:
    """Short, human-readable error text (Selenium messages include full stack traces)."""
    raw = getattr(exc, "msg", None) or str(exc) or exc.__class__.__name__
    first = raw.strip().split("\n")[0].replace("Message: ", "").split("; For documentation")[0].strip()
    name = exc.__class__.__name__
    if name in {"NoSuchWindowException", "InvalidSessionIdException"} or "not connected to DevTools" in raw:
        return "The bot's Chrome window was closed. Leave that window open - the bot closes it by itself."
    if name == "SessionNotCreatedException" or "Chrome instance exited" in first or "cannot find Chrome binary" in first:
        return ("Chrome could not be started. Make sure Google Chrome is installed and not already open with the "
                f"bot's profile, then try again. ({first})")
    if name == "NoSuchDriverException":
        return "No ChromeDriver available. Selenium Manager needs internet access the first time to download it."
    if "ERR_INTERNET_DISCONNECTED" in raw or "ERR_NAME_NOT_RESOLVED" in raw or "ERR_TUNNEL_CONNECTION_FAILED" in raw:
        return "Chrome couldn't reach Google - check the internet connection (or proxy/VPN) and try again."
    if name == "RecordingError":
        return first
    if "PortAudio" in first or name == "PortAudioError":
        return f"Audio recording failed: {first}. Pick another device in Settings -> Audio capture."
    if name in {"MeetJoinError", "BrowserClosed"}:
        return raw.strip()[:800]
    if name == "TranscriptionError" or "not set" in first:
        return f"{first} You can add it in Settings -> AI providers, then click 'Re-process recording'."
    if "AuthenticationError" in name or "incorrect api key" in first.lower() or "api key not valid" in first.lower():
        return f"The AI provider rejected the API key - check it in Settings -> AI providers. ({first[:200]})"
    return first[:500]
