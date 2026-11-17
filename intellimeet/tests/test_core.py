import pytest

from intellimeet.analyzer import BasicAnalyzer, normalize_analysis
from intellimeet.meet_joiner import normalize_meet_link
from intellimeet.transcriber import transcript_from_text_file


def test_meet_link_validation():
    assert normalize_meet_link("meet.google.com/abc-defg-hij") == "https://meet.google.com/abc-defg-hij"
    assert normalize_meet_link("https://meet.google.com/abc-defg-hij?authuser=0").startswith("https://")
    with pytest.raises(ValueError):
        normalize_meet_link("https://zoom.us/j/123")


def test_text_transcript_parsing(tmp_path):
    f = tmp_path / "t.txt"
    f.write_text("[00:05] Hello team, let's begin.\n[01:10] Ayush will fix the bug by Friday.\n")
    t = transcript_from_text_file(f)
    assert len(t.segments) == 2
    assert t.segments[1].start == 70


def test_vtt_parsing(tmp_path):
    f = tmp_path / "t.vtt"
    f.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nHello there everyone\n\n00:00:05.000 --> 00:00:08.000\nSecond line here\n")
    t = transcript_from_text_file(f)
    assert [s.text for s in t.segments] == ["Hello there everyone", "Second line here"]


def test_basic_analyzer_finds_action_items():
    text = ("We reviewed the release plan today and it looks great. "
            "Ritul will update the database migration by Wednesday. "
            "There is a risk that the login flow is blocked. We decided to use a saved profile.")
    a = BasicAnalyzer().analyze(text)
    assert a["summary"]
    assert any("Ritul" == i["owner"] for i in a["action_items"])
    assert a["decisions"]


def test_normalize_handles_messy_output():
    a = normalize_analysis({"action_items": ["Do X", {"task": ""}], "sentiment": "positive"})
    assert a["action_items"][0]["task"] == "Do X" and len(a["action_items"]) == 1
    assert a["sentiment"]["label"] == "positive"


def test_basic_answer_uses_analysis():
    a = {"action_items": [{"task": "Send mockups", "owner": "Ayush", "due": "Friday"}]}
    out = BasicAnalyzer().answer("Who is responsible for what?", "irrelevant text here today", a)
    assert "Send mockups" in out and "Ayush" in out


def test_basic_title_skips_names_and_filler():
    text = open(__file__.replace("test_core.py", "fixtures/design-review.txt")).read()
    a = BasicAnalyzer().analyze(text)
    assert "Welcome" not in a["title"] and "Ayush" not in a["topics"]
    assert a["sentiment"]["label"] != "negative"


def test_friendly_selenium_error():
    from intellimeet.server.worker import friendly_error

    class SessionNotCreatedException(Exception):
        msg = "session not created: Chrome instance exited.\nStacktrace:\n#0 0x55"

    assert "Chrome could not be started" in friendly_error(SessionNotCreatedException())


def test_detect_account_checks_host_not_substring(tmp_path):
    from intellimeet.config import Settings
    from intellimeet.meet_joiner import MeetJoiner

    class FakeDriver:
        def __init__(self, url, html=""):
            self.current_url, self.page_source = url, html

    j = MeetJoiner(Settings(data_dir=tmp_path))
    j.driver = FakeDriver("https://accounts.google.com/ServiceLogin?continue=https://myaccount.google.com/")
    assert j.detect_account() is None  # the old bug: this used to count as signed in
    j.driver = FakeDriver("https://myaccount.google.com/?pli=1", "<div>Welcome, kanika@gmail.com</div>")
    assert j.detect_account() == "kanika@gmail.com"


def _fake_genai(monkeypatch, behaviour):
    """Install a fake google.genai client whose generate_content follows ``behaviour(model)``."""
    import sys
    import types as pytypes

    calls = []

    class Models:
        def generate_content(self, model, contents, config):
            calls.append(model)
            return behaviour(model, len([c for c in calls if c == model]))

    class Client:
        def __init__(self, **kw):
            self.models = Models()

    genai_types = pytypes.SimpleNamespace(
        HttpOptions=lambda **kw: None, Content=lambda **kw: kw, Part=lambda **kw: kw,
        GenerateContentConfig=lambda **kw: kw)
    genai = pytypes.SimpleNamespace(Client=Client, types=genai_types)
    google = pytypes.ModuleType("google")
    google.genai = genai
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", genai_types)
    import intellimeet.analyzer as an
    monkeypatch.setattr(an.time, "sleep", lambda s: None)
    return calls


def test_gemini_busy_falls_back_to_next_model(monkeypatch, tmp_path):
    import types as pytypes

    from intellimeet.analyzer import MeetingAnalyzer
    from intellimeet.config import Settings

    def behaviour(model, n):
        if model == "gemini-3.8-flash":
            raise RuntimeError("503 UNAVAILABLE. This model is currently experiencing high demand.")
        return pytypes.SimpleNamespace(text='{"title":"Demo","summary":"ok","action_items":[]}')

    calls = _fake_genai(monkeypatch, behaviour)
    a = MeetingAnalyzer(Settings(data_dir=tmp_path, analyzer="gemini", gemini_api_key="k", gemini_model="gemini-3.8-flash"))
    r = a.analyze("We talked about the demo plan for Monday.")
    # busy model: 2 tries, then the high-quota Flash-Lite fallback
    assert calls == ["gemini-3.8-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite"]
    assert r["title"] == "Demo" and "gemini-3.5-flash-lite" in r["provider"]


def test_all_busy_uses_offline_analyzer(monkeypatch, tmp_path):
    from intellimeet.analyzer import MeetingAnalyzer
    from intellimeet.config import Settings

    def behaviour(model, n):
        raise RuntimeError("503 UNAVAILABLE high demand")

    _fake_genai(monkeypatch, behaviour)
    a = MeetingAnalyzer(Settings(data_dir=tmp_path, analyzer="gemini", gemini_api_key="k"))
    r = a.analyze("Ayush will fix the bug by Friday. We decided to ship on Monday.")
    assert r["provider"].startswith("offline") and r["summary"] and r["warning"]


def test_quota_exhausted_skips_to_next_model_without_retry(monkeypatch, tmp_path):
    import types as pytypes

    from intellimeet.analyzer import MeetingAnalyzer
    from intellimeet.config import Settings

    def behaviour(model, n):
        if model in ("gemini-3.8-flash", "gemini-3.5-flash-lite"):
            raise RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded")
        return pytypes.SimpleNamespace(text='{"title":"T","summary":"s"}')

    calls = _fake_genai(monkeypatch, behaviour)
    a = MeetingAnalyzer(Settings(data_dir=tmp_path, analyzer="gemini", gemini_api_key="k", gemini_model="gemini-3.8-flash"))
    a.analyze("some meeting text about the project plan")
    assert calls == ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]


def test_chat_falls_back_offline_when_ai_fails(monkeypatch, tmp_path):
    from intellimeet.analyzer import MeetingAnalyzer
    from intellimeet.config import Settings

    _fake_genai(monkeypatch, lambda m, n: (_ for _ in ()).throw(RuntimeError("429 RESOURCE_EXHAUSTED")))
    a = MeetingAnalyzer(Settings(data_dir=tmp_path, analyzer="gemini", gemini_api_key="k"))
    out = a.answer("Who is responsible for what?", "x", {"action_items": [{"task": "Ship it", "owner": "Ayush", "due": "Friday"}]})
    assert "Ship it" in out and "offline answer" in out
