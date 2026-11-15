"""Configuration loaded from environment variables / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from dotenv import load_dotenv


def _bool(value: Optional[str], default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _device(value: Optional[str]) -> Optional[Union[int, str]]:
    if not value:
        return None
    return int(value) if value.strip().isdigit() else value


@dataclass
class Settings:
    # Google / browser
    meet_link: str = ""
    email: str = ""
    password: str = ""
    chrome_profile_dir: Optional[str] = None
    chrome_binary: Optional[str] = None
    bot_display_name: str = "IntelliMeet Bot"
    headless: bool = False
    admit_timeout: int = 300

    # Recording
    duration: int = 60
    sample_rate: int = 44100
    channels: int = 1
    audio_source: str = ""  # loopback | device ("" = loopback on Windows/Linux, device on macOS)
    audio_device: Optional[Union[int, str]] = None
    max_audio_size_bytes: int = 20 * 1024 * 1024
    output_dir: Path = field(default_factory=lambda: Path("recordings"))

    # Transcription
    transcriber: str = "openai"  # openai | local
    whisper_model: str = "whisper-1"
    local_whisper_model: str = "small"
    local_whisper_device: str = "cpu"

    # Analysis
    analyzer: str = "auto"  # auto | openai | gemini | basic
    openai_api_key: str = ""
    gpt_model: str = "gpt-4o-mini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"

    # Web app
    data_dir: Path = field(default_factory=lambda: Path("data"))
    host: str = "127.0.0.1"
    port: int = 8000
    env_path: Path = field(default_factory=lambda: Path(".env"))

    @property
    def database_path(self) -> Path:
        return self.data_dir / "intellimeet.db"

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "Settings":
        env_path = Path(env_file or ".env").resolve()
        load_dotenv(env_path)
        e = os.environ.get
        return cls(
            env_path=env_path,
            audio_source=e("AUDIO_SOURCE", "").lower(),
            admit_timeout=int(e("ADMIT_TIMEOUT", "300") or 300),
            meet_link=e("MEET_LINK", ""),
            email=e("EMAIL_ID", ""),
            password=e("EMAIL_PASSWORD", ""),
            chrome_profile_dir=e("CHROME_PROFILE_DIR") or None,
            chrome_binary=e("CHROME_BINARY") or None,
            bot_display_name=e("BOT_DISPLAY_NAME", "IntelliMeet Bot"),
            headless=_bool(e("HEADLESS"), False),
            duration=int(e("RECORDING_DURATION", "60")),
            sample_rate=int(e("SAMPLE_RATE", "44100")),
            channels=int(e("CHANNELS", "1")),
            audio_device=_device(e("AUDIO_DEVICE")),
            max_audio_size_bytes=int(e("MAX_AUDIO_SIZE_BYTES", str(20 * 1024 * 1024))),
            output_dir=Path(e("OUTPUT_DIR", "recordings")),
            transcriber=e("TRANSCRIBER", "openai").lower(),
            whisper_model=e("WHISPER_MODEL", "whisper-1"),
            local_whisper_model=e("LOCAL_WHISPER_MODEL", "small"),
            local_whisper_device=e("LOCAL_WHISPER_DEVICE", "cpu"),
            analyzer=e("ANALYZER", "auto").lower(),
            openai_api_key=e("OPENAI_API_KEY", ""),
            gpt_model=e("GPT_MODEL", "gpt-4o-mini"),
            gemini_api_key=e("GEMINI_API_KEY", ""),
            gemini_model=e("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            data_dir=Path(e("DATA_DIR", "data")),
            host=e("HOST", "127.0.0.1"),
            port=int(e("PORT", "8000")),
        )


# ---------------------------------------------------------------------------
# Settings editable from the web app (persisted to .env)
# ---------------------------------------------------------------------------
# attr -> (ENV_NAME, type, secret)
EDITABLE: dict[str, tuple[str, type, bool]] = {
    "transcriber": ("TRANSCRIBER", str, False),
    "openai_api_key": ("OPENAI_API_KEY", str, True),
    "whisper_model": ("WHISPER_MODEL", str, False),
    "local_whisper_model": ("LOCAL_WHISPER_MODEL", str, False),
    "analyzer": ("ANALYZER", str, False),
    "gpt_model": ("GPT_MODEL", str, False),
    "gemini_api_key": ("GEMINI_API_KEY", str, True),
    "gemini_model": ("GEMINI_MODEL", str, False),
    "bot_display_name": ("BOT_DISPLAY_NAME", str, False),
    "duration": ("RECORDING_DURATION", int, False),
    "admit_timeout": ("ADMIT_TIMEOUT", int, False),
    "headless": ("HEADLESS", bool, False),
    "audio_source": ("AUDIO_SOURCE", str, False),
    "audio_device": ("AUDIO_DEVICE", str, False),
}


def mask(value: str) -> str:
    if not value:
        return ""
    return value[:4] + "…" + value[-4:] if len(value) > 10 else "…" + value[-2:]


def public_settings(s: Settings) -> dict:
    out = {}
    for attr, (_, _, secret) in EDITABLE.items():
        v = getattr(s, attr)
        out[attr] = {"set": bool(v), "masked": mask(str(v))} if secret else ("" if v is None else v)
    return out


def _env_line(name: str, value: str) -> str:
    if value and (value != value.strip() or any(c in value for c in "#\"'")):
        value = '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"{name}={value}"


def update_settings(s: Settings, changes: dict) -> list[str]:
    """Apply ``changes`` to the live settings object, os.environ and the .env file."""
    import re as _re

    applied: dict[str, str] = {}
    for attr, raw in changes.items():
        if attr not in EDITABLE:
            continue
        env, typ, _ = EDITABLE[attr]
        if typ is bool:
            val = raw if isinstance(raw, bool) else str(raw).lower() in {"1", "true", "yes", "on"}
            text = "true" if val else "false"
        elif typ is int:
            val = int(raw)
            text = str(val)
        else:
            val = ("" if raw is None else str(raw)).strip()
            text = val
            if attr in {"transcriber", "analyzer", "audio_source"}:
                val = text = val.lower()
        if attr == "audio_device":
            val = int(val) if str(val).isdigit() else (val or None)
        setattr(s, attr, val)
        os.environ[env] = text
        applied[env] = text

    path = Path(s.env_path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for env, text in applied.items():
        pat = _re.compile(rf"^\s*{env}\s*=")
        for i, line in enumerate(lines):
            if pat.match(line):
                lines[i] = _env_line(env, text)
                break
        else:
            lines.append(_env_line(env, text))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return list(applied)
