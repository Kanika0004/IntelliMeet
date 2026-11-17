"""Sample meetings so the dashboard can be explored without API keys or a live call."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from typing import Optional

from .db import Database


def _segments(lines: list[tuple[str, str]], gap: float = 1.0) -> tuple[str, list[dict]]:
    t = 0.0
    segs = []
    for speaker, text in lines:
        dur = max(3.0, len(text.split()) / 2.6)
        segs.append({"start": round(t, 2), "end": round(t + dur, 2), "text": text, "speaker": speaker})
        t += dur + gap
    return " ".join(s["text"] for s in segs), segs


SPRINT = [
    ("Kanika", "Okay, let's get started with sprint fourteen planning. The goal for this sprint is to ship the transcript search and the action item tracker."),
    ("Ayush", "Before we commit, the Whisper pipeline is still slow on long recordings. A sixty minute call takes about eight minutes to transcribe on the CPU box."),
    ("Ritul", "We could chunk the audio into ten minute pieces and transcribe them in parallel. That should cut it to under three minutes."),
    ("Kanika", "That sounds good. Ayush, can you own the chunking change?"),
    ("Ayush", "Yes, I'll have a pull request up by Thursday."),
    ("Shivangi", "On the frontend side, the meeting detail page is done. I still need to add highlight for search matches in the transcript view."),
    ("Kanika", "Great progress. What about the action items, are we storing completion state?"),
    ("Shivangi", "Not yet. We need an endpoint to toggle an item as done. I can pair with Ritul on that."),
    ("Ritul", "Sure. I will add the patch endpoint and the database migration by Wednesday."),
    ("Kanika", "One concern is the Google login. The bot got blocked twice this week with the browser not secure message."),
    ("Ayush", "The fix is to use a saved Chrome profile. We sign in once manually and the bot reuses the session. It has worked every time since."),
    ("Kanika", "Then we decided: saved profile is the default and password login is only a fallback. Let's document that in the README."),
    ("Shivangi", "I'll update the README and the setup guide tomorrow."),
    ("Kanika", "Last thing, the project review with our guide is next Monday. We need a demo with a real meeting recorded end to end."),
    ("Ritul", "I'm a bit worried about audio capture on Windows. Stereo Mix is disabled on some laptops."),
    ("Ayush", "VB-Audio Cable works reliably. I tested it yesterday, the recording was clean."),
    ("Kanika", "Perfect. So the plan is clear. Thanks everyone, this was a really productive session."),
]

SPRINT_ANALYSIS = {
    "title": "Sprint 14 Planning",
    "summary": (
        "The team planned sprint fourteen around shipping transcript search and the action item tracker. "
        "Transcription speed on long recordings was the main technical risk, and the team agreed to chunk audio and "
        "transcribe pieces in parallel. Google sign-in blocks will be handled with a saved Chrome profile as the default. "
        "The sprint ends with an end-to-end demo for the project review next Monday."
    ),
    "key_points": [
        "Sprint goal: ship transcript search and the action item tracker",
        "A 60-minute recording takes about 8 minutes to transcribe on CPU; parallel 10-minute chunks should bring it under 3",
        "Meeting detail page is complete; search-match highlighting is still pending",
        "Action items need a persisted completion state and a toggle endpoint",
        "VB-Audio Cable is the reliable option for capturing meeting audio on Windows",
    ],
    "decisions": [
        "Use a saved Chrome profile as the default sign-in method; password login only as a fallback",
        "Chunk long recordings and transcribe the pieces in parallel",
    ],
    "action_items": [
        {"task": "Implement chunked, parallel transcription", "owner": "Ayush", "due": "Thursday", "done": False},
        {"task": "Add the action-item toggle endpoint and database migration", "owner": "Ritul", "due": "Wednesday", "done": True},
        {"task": "Highlight search matches in the transcript view", "owner": "Shivangi", "due": None, "done": False},
        {"task": "Update the README and setup guide with the saved-profile login flow", "owner": "Shivangi", "due": "Tomorrow", "done": False},
        {"task": "Prepare an end-to-end demo with a real recorded meeting", "owner": "Kanika", "due": "Next Monday", "done": False},
    ],
    "topics": ["Sprint planning", "Transcription", "Authentication", "Frontend", "Demo prep"],
    "sentiment": {
        "label": "positive",
        "score": 0.62,
        "explanation": "Collaborative and upbeat, with a couple of technical concerns resolved during the call.",
    },
    "provider": "sample",
}

CLIENT = [
    ("Priya", "Thanks for joining. We wanted to review how the pilot has gone over the last two weeks."),
    ("Kanika", "Of course. So far the bot has recorded forty two meetings across three teams, and summaries are being used daily."),
    ("Priya", "The summaries are useful, but some of our managers said the action items miss the owner when people speak informally."),
    ("Kanika", "That's fair. Owner detection depends on names being mentioned. We can prompt the model to infer owners from context and mark them as suggested."),
    ("Priya", "That would help. The other issue is data retention. Our security team needs recordings deleted after thirty days."),
    ("Ayush", "We can add a retention setting that deletes audio after a configurable number of days and keeps only the transcript."),
    ("Priya", "Good. And pricing, we are still waiting on the revised quote."),
    ("Kanika", "I'll send the revised quote by Friday along with the retention design."),
    ("Priya", "Honestly the delay on the quote has been frustrating for our procurement team."),
    ("Kanika", "Understood, and I apologise for that. You will have it this week."),
    ("Priya", "Alright. If those two items land, we are ready to expand the pilot to the finance team next month."),
]

CLIENT_ANALYSIS = {
    "title": "Pilot Review with Northwind",
    "summary": (
        "Northwind reviewed the two-week IntelliMeet pilot, which recorded 42 meetings across three teams. "
        "Summaries are valued, but action items sometimes miss owners and the security team requires a 30-day "
        "retention policy for recordings. A delayed pricing quote has frustrated procurement. Expansion to the "
        "finance team next month depends on resolving retention and pricing."
    ),
    "key_points": [
        "Pilot recorded 42 meetings across three teams in two weeks",
        "Managers report missing owners on informally assigned action items",
        "Security requires recordings to be deleted after 30 days",
        "The revised pricing quote is overdue",
        "Expansion to the finance team is conditional on retention and pricing",
    ],
    "decisions": ["Add a configurable audio retention setting that keeps transcripts only"],
    "action_items": [
        {"task": "Send the revised pricing quote and retention design", "owner": "Kanika", "due": "Friday", "done": False},
        {"task": "Build a configurable audio retention setting", "owner": "Ayush", "due": None, "done": False},
        {"task": "Improve owner inference for informally assigned action items", "owner": None, "due": None, "done": False},
    ],
    "topics": ["Pilot review", "Data retention", "Pricing", "Action items"],
    "sentiment": {
        "label": "mixed",
        "score": 0.05,
        "explanation": "Positive about the product's value but frustrated by the delayed quote.",
    },
    "provider": "sample",
}


def seed(db: Database, user_id: Optional[int] = None) -> list[str]:
    ids = []
    base = datetime.now(timezone.utc)
    for offset_h, lines, analysis, link in (
        (26, CLIENT, CLIENT_ANALYSIS, "https://meet.google.com/nwd-pilt-rvw"),
        (3, SPRINT, SPRINT_ANALYSIS, "https://meet.google.com/abc-defg-hij"),
    ):
        text, segs = _segments(lines)
        created = (base - timedelta(hours=offset_h)).isoformat(timespec="seconds")
        done = (base - timedelta(hours=offset_h) + timedelta(seconds=segs[-1]["end"] + 40)).isoformat(timespec="seconds")
        mid = db.create_meeting(
            title=analysis["title"],
            title_is_auto=0,
            source="sample",
            user_id=user_id,
            meet_link=link,
            status="completed",
            stage_message="Meeting processed",
            progress=1.0,
            duration_requested=int(segs[-1]["end"]) + 1,
            duration_seconds=segs[-1]["end"],
            created_at=created,
            started_at=created,
            completed_at=done,
        )
        db.update_meeting(mid, transcript={"text": text, "language": "en", "segments": segs}, analysis=analysis)
        for stage, msg in (
            ("joining", "Joined the meeting"),
            ("recording", "Recording"),
            ("transcribing", "Transcribing audio"),
            ("analyzing", "Generating summary and action items"),
            ("completed", "Meeting processed"),
        ):
            db.add_event(mid, stage, msg)
        ids.append(mid)
    return ids
