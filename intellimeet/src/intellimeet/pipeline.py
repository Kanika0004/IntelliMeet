"""End-to-end pipeline: join -> record -> transcribe -> analyse."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .analyzer import MeetingAnalyzer
from .config import Settings
from .meet_joiner import MeetJoiner
from .recorder import AudioRecorder, RecordingStats, audio_duration, compress_if_needed
from .transcriber import Transcriber

log = logging.getLogger(__name__)

StageCallback = Callable[[str, str], None]  # (stage, message)


def record_meeting(
    settings: Settings,
    link: str,
    duration: int,
    out_path: Path,
    on_stage: StageCallback,
    stop_event: Optional[threading.Event] = None,
    on_progress: Optional[Callable[[float], None]] = None,
    tag: str = "join",
) -> RecordingStats:
    """Join the meeting, record it, leave. Returns recording stats; raises on failure."""
    stop_event = stop_event or threading.Event()
    joiner = MeetJoiner(settings, on_status=lambda m: on_stage("joining", m))
    try:
        on_stage("joining", "Starting browser")
        joiner.start_browser()
        joiner.google_login()
        joiner.join(link, should_abort=stop_event.is_set, tag=tag)
        recorder = AudioRecorder(settings)
        on_stage("recording", f"Recording ({'system audio' if recorder.source == 'loopback' else 'input device'})"
                              f" for up to {duration // 60} min")
        stats = recorder.record(
            out_path, duration, stop_event=stop_event, on_progress=on_progress,
            # stop early only when Meet clearly shows the call is over, or the window is gone
            should_stop=lambda: not joiner.still_in_call(),
        )
        log.info("recording finished: %s", stats.to_dict())
        return stats
    finally:
        joiner.leave()


def process_audio(settings: Settings, audio_path: Path, on_stage: StageCallback, analyze: bool = True) -> dict:
    """Transcribe (and optionally analyse) an audio/transcript file."""
    on_stage("transcribing", "Transcribing audio")
    upload = audio_path
    if audio_path.suffix.lower() not in {".txt", ".vtt", ".srt"} and settings.transcriber == "openai":
        upload = compress_if_needed(audio_path, settings.max_audio_size_bytes)
    transcript = Transcriber(settings).transcribe(upload)
    result: dict = {"transcript": transcript.to_dict(), "analysis": None}

    dur = audio_duration(audio_path) if audio_path.suffix.lower() not in {".txt", ".vtt", ".srt"} else None
    if dur is None and transcript.segments:
        dur = transcript.segments[-1].end
    result["duration_seconds"] = dur

    if analyze:
        on_stage("analyzing", "Generating summary and action items")
        result["analysis"] = MeetingAnalyzer(settings).analyze(transcript.text)
    return result


def run_pipeline(
    settings: Settings,
    link: Optional[str] = None,
    duration: Optional[int] = None,
    analyze: bool = True,
    on_stage: Optional[StageCallback] = None,
) -> dict:
    """CLI entry: join a meeting, record it, and write a JSON report next to the audio."""
    on_stage = on_stage or (lambda stage, msg: log.info("[%s] %s", stage, msg))
    link = link or settings.meet_link
    duration = duration or settings.duration
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = Path(settings.output_dir) / f"meeting-{stamp}.wav"
    stats = record_meeting(settings, link, duration, out, on_stage)
    if stats.silent:
        raise RuntimeError("The recording is silent. Check the audio source with `intellimeet devices`.")
    result = process_audio(settings, out, on_stage, analyze=analyze)
    result["audio_file"] = str(out)
    report = out.with_suffix(".json")
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    on_stage("completed", f"Report written to {report}")
    return result
