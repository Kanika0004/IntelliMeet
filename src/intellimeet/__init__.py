"""IntelliMeet: join Google Meet, record, transcribe and analyse meetings."""

from .config import Settings
from .meet_joiner import MeetJoiner
from .recorder import AudioRecorder
from .transcriber import Transcriber
from .analyzer import MeetingAnalyzer
from .pipeline import run_pipeline

__all__ = [
    "Settings",
    "MeetJoiner",
    "AudioRecorder",
    "Transcriber",
    "MeetingAnalyzer",
    "run_pipeline",
]
__version__ = "0.1.0"
