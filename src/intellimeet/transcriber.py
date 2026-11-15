"""Speech-to-text with the OpenAI Whisper API or local faster-whisper."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings


@dataclass
class Segment:
    start: float
    end: float
    text: str

    def to_dict(self) -> dict:
        return {"start": round(self.start, 2), "end": round(self.end, 2), "text": self.text}


@dataclass
class Transcript:
    text: str
    segments: list[Segment] = field(default_factory=list)
    language: str | None = None

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "segments": [s.to_dict() for s in self.segments],
        }


class TranscriptionError(RuntimeError):
    pass


def _patch_pyav() -> None:
    """faster-whisper calls av.open(..., metadata_errors="ignore"), which PyAV 19+ removed.
    Wrap av.open so the unsupported argument is dropped instead of crashing."""
    try:
        import av
    except ImportError:
        return
    if getattr(av, "_intellimeet_patched", False):
        return
    orig = av.open

    def open_compat(*args, **kwargs):
        try:
            return orig(*args, **kwargs)
        except TypeError as exc:
            if "metadata_errors" in kwargs and "metadata_errors" in str(exc):
                kwargs.pop("metadata_errors")
                return orig(*args, **kwargs)
            raise

    av.open = open_compat
    av._intellimeet_patched = True


class Transcriber:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def provider(self) -> str:
        return self.settings.transcriber

    def is_configured(self) -> bool:
        if self.provider == "local":
            try:
                import faster_whisper  # noqa: F401
            except ImportError:
                return False
            return True
        return bool(self.settings.openai_api_key)

    def transcribe(self, path: Path) -> Transcript:
        path = Path(path)
        if path.suffix.lower() in {".txt", ".vtt", ".srt"}:
            return transcript_from_text_file(path)
        if self.provider == "local":
            return self._local(path)
        return self._openai(path)

    def _openai(self, path: Path) -> Transcript:
        if not self.settings.openai_api_key:
            raise TranscriptionError(
                "OPENAI_API_KEY is not set. Add it to .env or set TRANSCRIBER=local to use faster-whisper."
            )
        from openai import OpenAI

        client = OpenAI(api_key=self.settings.openai_api_key)
        with open(path, "rb") as fh:
            resp = client.audio.transcriptions.create(
                model=self.settings.whisper_model,
                file=fh,
                response_format="verbose_json",
            )
        data = resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        segments = [
            Segment(float(s["start"]), float(s["end"]), s["text"].strip())
            for s in (data.get("segments") or [])
        ]
        return Transcript(text=(data.get("text") or "").strip(), segments=segments, language=data.get("language"))

    def _local(self, path: Path) -> Transcript:
        _patch_pyav()
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise TranscriptionError("faster-whisper is not installed: pip install faster-whisper") from exc
        model = WhisperModel(
            self.settings.local_whisper_model,
            device=self.settings.local_whisper_device,
            compute_type="int8" if self.settings.local_whisper_device == "cpu" else "float16",
        )
        segs, info = model.transcribe(str(path), vad_filter=True)
        segments = [Segment(s.start, s.end, s.text.strip()) for s in segs]
        return Transcript(
            text=" ".join(s.text for s in segments).strip(),
            segments=segments,
            language=getattr(info, "language", None),
        )


_TS = re.compile(r"(\d{1,2}):(\d{2})(?::(\d{2}))?(?:[.,]\d+)?")


def _to_seconds(stamp: str) -> float:
    m = _TS.match(stamp)
    if not m:
        return 0.0
    a, b, c = m.groups()
    return int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)


def transcript_from_text_file(path: Path) -> Transcript:
    """Accept a plain-text / VTT / SRT transcript so meetings can be analysed without audio."""
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    segments: list[Segment] = []
    if "-->" in raw:
        blocks = re.split(r"\n\s*\n", raw.strip())
        for block in blocks:
            lines = [ln for ln in block.splitlines() if ln.strip() and ln.strip() != "WEBVTT"]
            for i, ln in enumerate(lines):
                if "-->" in ln:
                    a, b = [p.strip() for p in ln.split("-->")[:2]]
                    text = " ".join(lines[i + 1 :]).strip()
                    if text:
                        segments.append(Segment(_to_seconds(a), _to_seconds(b.split(" ")[0]), text))
                    break
    else:
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        t = 0.0
        for ln in lines:
            m = re.match(r"^\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*(.*)$", ln)
            if m:
                start, text = _to_seconds(m.group(1)), m.group(2)
            else:
                start, text = t, ln
            dur = max(2.0, len(text.split()) / 2.5)
            segments.append(Segment(start, start + dur, text))
            t = start + dur
    text = " ".join(s.text for s in segments)
    return Transcript(text=text, segments=segments, language=None)
