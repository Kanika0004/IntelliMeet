"""Record meeting audio.

Two sources:

* ``loopback`` (default on Windows/Linux): records whatever the computer is playing -
  i.e. the meeting audio from the bot's Chrome window - straight from the speakers.
  No Stereo Mix / virtual cable needed. Uses the ``soundcard`` library (WASAPI on
  Windows, PulseAudio/PipeWire on Linux).
* ``device``: records from an input device (microphone, Stereo Mix, VB-Cable, BlackHole)
  through ``sounddevice``.
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import threading
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .config import Settings

log = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"


class RecordingError(RuntimeError):
    pass


@dataclass
class RecordingStats:
    seconds: float
    peak: float  # 0..1
    rms: float  # 0..1
    source: str

    @property
    def silent(self) -> bool:
        return self.peak < 0.003

    def to_dict(self) -> dict:
        return {"seconds": round(self.seconds, 2), "peak": round(self.peak, 4), "rms": round(self.rms, 5),
                "source": self.source, "silent": self.silent}


def default_source() -> str:
    return "device" if IS_MAC else "loopback"


def _com_init() -> None:
    """soundcard uses COM on Windows; each extra thread that touches it must initialise COM."""
    if IS_WINDOWS:
        try:
            import ctypes

            ctypes.windll.ole32.CoInitializeEx(None, 0)  # S_FALSE (already initialised) is fine
        except Exception:  # noqa: BLE001
            pass


def _import_soundcard():
    """Import soundcard safely.

    soundcard initialises COM when it is first imported and raises on S_FALSE
    ("Error 0x100000001") if COM was already initialised on that thread. So the first
    import must happen *before* we touch COM; later threads then initialise COM themselves.
    """
    import sys

    import numpy as np

    # soundcard <= 0.4.3 calls numpy.fromstring in binary mode, which numpy 2 removed.
    if not getattr(np, "_intellimeet_patched", False):
        orig = np.fromstring

        def fromstring(s, dtype=float, count=-1, sep="", **kw):
            if sep == "":
                return np.frombuffer(s, dtype=dtype, count=count).copy()
            return orig(s, dtype=dtype, count=count, sep=sep, **kw)

        np.fromstring = fromstring
        np._intellimeet_patched = True

    if "soundcard" in sys.modules:
        _com_init()  # this thread may be new
        sc = sys.modules["soundcard"]
    else:
        try:
            import soundcard as sc
        except RuntimeError as exc:
            if IS_WINDOWS and "0x100000001" in str(exc):
                # COM was already initialised on this thread: undo once and import again.
                import ctypes

                ctypes.windll.ole32.CoUninitialize()
                for mod in [m for m in sys.modules if m.startswith("soundcard")]:
                    del sys.modules[mod]
                import soundcard as sc
            else:
                raise
    warnings.filterwarnings("ignore", category=getattr(sc, "SoundcardRuntimeWarning", RuntimeWarning))
    return sc


def preload() -> None:
    """Import soundcard on the main thread at startup (best effort)."""
    if not IS_MAC:
        try:
            _import_soundcard()
        except Exception as exc:  # noqa: BLE001
            log.warning("system audio capture unavailable: %s", exc)


def list_devices() -> dict:
    """Devices for the settings page."""
    out: dict = {"loopback_supported": False, "speakers": [], "default_speaker": None,
                 "inputs": [], "default_input": None, "errors": []}
    if not IS_MAC:
        try:
            sc = _import_soundcard()
            out["speakers"] = [s.name for s in sc.all_speakers()]
            out["default_speaker"] = sc.default_speaker().name
            out["loopback_supported"] = True
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"System audio capture unavailable: {str(exc) or exc.__class__.__name__}")
    try:
        import sounddevice as sd

        default_in = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) else sd.default.device
        seen = set()
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and d["name"] not in seen:
                seen.add(d["name"])
                out["inputs"].append(d["name"])
                if i == default_in:
                    out["default_input"] = d["name"]
    except Exception as exc:  # noqa: BLE001
        out["errors"].append(f"Input devices unavailable: {exc}")
    return out


class AudioRecorder:
    def __init__(self, settings: Settings):
        self.settings = settings

    @staticmethod
    def list_devices() -> str:
        d = list_devices()
        lines = ["System audio (loopback) - speakers:"] + [f"  {s}" for s in d["speakers"]]
        lines += ["Input devices:"] + [f"  {s}" for s in d["inputs"]]
        lines += d["errors"]
        return "\n".join(lines)

    @property
    def source(self) -> str:
        return (self.settings.audio_source or default_source()).lower()

    def record(
        self,
        path: Path,
        duration: float,
        stop_event: Optional[threading.Event] = None,
        on_progress: Optional[Callable[[float], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> RecordingStats:
        """Record up to ``duration`` seconds into a WAV file.

        Ends early when ``stop_event`` is set or ``should_stop()`` returns True (checked every 5 s).
        Raises RecordingError if the audio device can't be opened.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        stop_event = stop_event or threading.Event()
        if self.source == "loopback":
            return self._record_loopback(path, duration, stop_event, on_progress, should_stop)
        return self._record_device(path, duration, stop_event, on_progress, should_stop)

    # ----------------------------------------------------------- loopback
    def _record_loopback(self, path, duration, stop_event, on_progress, should_stop) -> RecordingStats:
        """Windows: PyAudioWPatch (WASAPI loopback) first, soundcard as fallback. Linux: soundcard."""
        if IS_WINDOWS:
            try:
                import pyaudiowpatch  # noqa: F401
            except ImportError:
                log.info("PyAudioWPatch not installed; using soundcard for loopback")
            else:
                try:
                    return self._record_wasapi(path, duration, stop_event, on_progress, should_stop)
                except RecordingError as exc:
                    log.warning("WASAPI loopback failed (%s); trying soundcard", exc)
        return self._record_soundcard(path, duration, stop_event, on_progress, should_stop)

    def _record_wasapi(self, path, duration, stop_event, on_progress, should_stop) -> RecordingStats:
        import queue

        import numpy as np
        import pyaudiowpatch as pyaudio
        import soundfile as sf

        p = pyaudio.PyAudio()
        try:
            try:
                wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            except OSError as exc:
                raise RecordingError("WASAPI is not available on this system.") from exc
            want = (str(self.settings.audio_device) if self.settings.audio_device else "").strip()
            if not want:
                want = p.get_device_info_by_index(wasapi["defaultOutputDevice"])["name"]
            loopbacks = list(p.get_loopback_device_info_generator())
            dev = next((d for d in loopbacks if d["name"].startswith(want)), None) or next(
                (d for d in loopbacks if want.lower() in d["name"].lower()), None)
            if dev is None:
                names = ", ".join(d["name"] for d in loopbacks) or "none"
                raise RecordingError(f"No loopback device for '{want}'. Available: {names}")

            channels = max(1, min(2, int(dev["maxInputChannels"]) or 2))
            sr = int(dev["defaultSampleRate"])
            chunks: "queue.Queue[bytes]" = queue.Queue()

            def callback(in_data, frame_count, time_info, status):  # noqa: ARG001
                chunks.put(in_data)
                return (None, pyaudio.paContinue)

            try:
                stream = p.open(format=pyaudio.paInt16, channels=channels, rate=sr, input=True,
                                input_device_index=dev["index"], frames_per_buffer=1024, stream_callback=callback)
            except Exception as exc:  # noqa: BLE001
                raise RecordingError(f"Couldn't open '{dev['name']}': {exc}") from exc

            log.info("recording WASAPI loopback '%s' %d Hz %d ch", dev["name"], sr, channels)
            peak = sq = 0.0
            n = frames = 0
            start = last_check = time.time()
            # WASAPI delivers no data while nothing is playing; pad with silence so the
            # file stays in sync with real time.
            written = 0
            with sf.SoundFile(path, mode="w", samplerate=sr, channels=channels, subtype="PCM_16") as f:
                try:
                    while not stop_event.is_set():
                        try:
                            buf = chunks.get(timeout=0.5)
                        except queue.Empty:
                            buf = None
                        elapsed = time.time() - start
                        expected = int(elapsed * sr)
                        if buf:
                            data = np.frombuffer(buf, dtype=np.int16).reshape(-1, channels).astype(np.float32) / 32768
                            gap = expected - written - len(data)
                            if gap > sr // 2:  # >0.5 s of missing data = silence while nothing played
                                f.write(np.zeros((gap, channels), dtype=np.float32))
                                written += gap
                            f.write(data)
                            written += len(data)
                            frames += len(data)
                            peak = max(peak, float(np.abs(data).max()) if data.size else 0.0)
                            sq += float(np.square(data).sum())
                            n += data.size
                        elif expected - written > sr:
                            pad = expected - written
                            f.write(np.zeros((pad, channels), dtype=np.float32))
                            written += pad
                        if on_progress:
                            on_progress(min(elapsed / max(duration, 1), 1.0))
                        if elapsed >= duration:
                            break
                        if should_stop and time.time() - last_check > 5:
                            last_check = time.time()
                            if should_stop():
                                log.info("meeting ended; stopping recording")
                                break
                finally:
                    stream.stop_stream()
                    stream.close()
            log.info("WASAPI loopback: %d frames with sound data, peak %.4f", frames, peak)
            return RecordingStats(time.time() - start, peak, (sq / n) ** 0.5 if n else 0.0,
                                  f"System audio (WASAPI) · {dev['name'].replace(' [Loopback]', '')}")
        finally:
            p.terminate()

    def _record_soundcard(self, path, duration, stop_event, on_progress, should_stop) -> RecordingStats:
        import numpy as np
        import soundfile as sf

        try:
            sc = _import_soundcard()
            name = self.settings.audio_device
            speaker = sc.get_speaker(str(name)) if name else sc.default_speaker()
            # match by the exact WASAPI id - names like "Speakers (Realtek(R) Audio)" can fuzzy-match wrongly
            mic = sc.get_microphone(id=str(speaker.id), include_loopback=True)
        except Exception as exc:  # noqa: BLE001
            raise RecordingError(
                f"Couldn't capture system audio ({str(exc) or exc.__class__.__name__}). In Settings -> Audio capture, pick another speaker "
                "or switch the source to an input device."
            ) from exc

        sr = 48000
        channels = 2
        peak = 0.0
        sq_sum = 0.0
        n = 0
        start = time.time()
        last_check = start
        log.info("recording system audio from '%s'", speaker.name)
        with sf.SoundFile(path, mode="w", samplerate=sr, channels=channels, subtype="PCM_16") as f:
            try:
                with mic.recorder(samplerate=sr, channels=channels) as rec:
                    while not stop_event.is_set():
                        data = rec.record(numframes=sr // 2)  # 0.5 s
                        if data is None or not len(data):
                            continue
                        data = np.nan_to_num(np.asarray(data, dtype=np.float32))
                        if data.ndim == 1:
                            data = np.stack([data, data], axis=1)
                        data = np.clip(data[:, :channels], -1, 1)
                        f.write(data)
                        peak = max(peak, float(np.abs(data).max()))
                        sq_sum += float(np.square(data).sum())
                        n += data.size
                        elapsed = time.time() - start
                        if on_progress:
                            on_progress(min(elapsed / max(duration, 1), 1.0))
                        if elapsed >= duration:
                            break
                        if should_stop and time.time() - last_check > 5:
                            last_check = time.time()
                            if should_stop():
                                log.info("meeting ended; stopping recording")
                                break
            except Exception as exc:  # noqa: BLE001
                if time.time() - start < 2:
                    raise RecordingError(f"System audio recording failed to start: {exc}") from exc
                log.warning("recording stopped with error: %s", exc)
        return RecordingStats(time.time() - start, peak, (sq_sum / n) ** 0.5 if n else 0.0, f"System audio (soundcard) · {speaker.name}")

    # ------------------------------------------------------------- device
    def _resolve_device(self):
        import sounddevice as sd

        want = self.settings.audio_device
        if want is None or want == "":
            return None, sd.query_devices(kind="input")
        if isinstance(want, int) or str(want).isdigit():
            idx = int(want)
            return idx, sd.query_devices(idx)
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0 and str(want).lower() in d["name"].lower():
                return i, d
        raise RecordingError(f"Audio input '{want}' was not found. Pick a device in Settings -> Audio.")

    def _record_device(self, path, duration, stop_event, on_progress, should_stop) -> RecordingStats:
        import numpy as np
        import sounddevice as sd
        import soundfile as sf

        try:
            device, info = self._resolve_device()
        except RecordingError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RecordingError(f"No audio input device available: {exc}") from exc

        channels = max(1, min(int(self.settings.channels or 1), int(info["max_input_channels"]) or 1))
        # Use the device's own rate first - a mismatch is the most common PortAudio failure on Windows.
        rates = [int(info.get("default_samplerate") or 48000), int(self.settings.sample_rate), 48000, 44100, 16000]
        stats = {"peak": 0.0, "sq": 0.0, "n": 0}
        last_exc: Exception | None = None
        for sr in dict.fromkeys(rates):
            try:
                sd.check_input_settings(device=device, channels=channels, samplerate=sr)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                continue
            with sf.SoundFile(path, mode="w", samplerate=sr, channels=channels, subtype="PCM_16") as f:

                def callback(indata, frames, t, status):  # noqa: ARG001
                    f.write(indata.copy())
                    stats["peak"] = max(stats["peak"], float(np.abs(indata).max()))
                    stats["sq"] += float(np.square(indata).sum())
                    stats["n"] += indata.size

                try:
                    stream = sd.InputStream(samplerate=sr, channels=channels, device=device, dtype="float32", callback=callback)
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    continue
                log.info("recording from '%s' at %d Hz", info["name"], sr)
                start = last_check = time.time()
                with stream:
                    while not stop_event.is_set():
                        elapsed = time.time() - start
                        if on_progress:
                            on_progress(min(elapsed / max(duration, 1), 1.0))
                        if elapsed >= duration:
                            break
                        if should_stop and time.time() - last_check > 5:
                            last_check = time.time()
                            if should_stop():
                                break
                        time.sleep(0.25)
                n = stats["n"]
                return RecordingStats(time.time() - start, stats["peak"], (stats["sq"] / n) ** 0.5 if n else 0.0, info["name"])
        raise RecordingError(f"Couldn't open audio input '{info['name']}': {last_exc}")


def compress_if_needed(path: Path, max_bytes: int) -> Path:
    """Convert to a low-bitrate mono MP3 if larger than ``max_bytes`` (Whisper API limit is 25 MB)."""
    path = Path(path)
    if path.stat().st_size <= max_bytes:
        return path
    if not shutil.which("ffmpeg"):
        log.warning("Audio is %d bytes but ffmpeg is not installed; sending as-is", path.stat().st_size)
        return path
    out = path.with_suffix(".compressed.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-b:a", "32k", str(out)],
        check=True,
    )
    return out


def audio_duration(path: Path) -> Optional[float]:
    try:
        import soundfile as sf

        info = sf.info(str(path))
        return float(info.frames) / float(info.samplerate)
    except Exception:  # noqa: BLE001
        pass
    if shutil.which("ffprobe"):
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                capture_output=True, text=True, check=True,
            )
            return float(out.stdout.strip())
        except Exception:  # noqa: BLE001
            return None
    return None


def audio_level(path: Path) -> Optional[float]:
    """Peak level 0..1 of a WAV/FLAC/OGG file (None if it can't be read)."""
    try:
        import numpy as np
        import soundfile as sf

        data, _ = sf.read(str(path), dtype="float32", always_2d=True)
        return float(np.abs(data).max()) if data.size else 0.0
    except Exception:  # noqa: BLE001
        return None
