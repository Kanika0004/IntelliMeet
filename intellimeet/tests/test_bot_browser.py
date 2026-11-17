"""Runs the real MeetJoiner in headless Chrome against local mock Meet pages.

Skipped by default (needs Chrome). Run with:  RUN_BROWSER_TESTS=1 python -m pytest tests/test_bot_browser.py
"""
import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("RUN_BROWSER_TESTS"), reason="set RUN_BROWSER_TESTS=1")
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture()
def joiner(tmp_path, monkeypatch):
    import intellimeet.meet_joiner as mj
    from intellimeet.config import Settings

    monkeypatch.setattr(mj, "normalize_meet_link", lambda l: l)
    monkeypatch.setattr(mj, "with_english", lambda l: l)
    j = mj.MeetJoiner(Settings(data_dir=tmp_path, headless=True, admit_timeout=30))
    j.start_browser()
    yield j
    j.quit()


def test_guest_join_mutes_and_names(joiner):
    joiner.join((FIX / "mock_meet_guest.html").as_uri())
    d = joiner.driver
    assert d.execute_script("return window.joinedAs") == "IntelliMeet Bot"
    assert d.execute_script("return [window.micAtJoin, window.camAtJoin]") == ["true", "true"]
    assert joiner.still_in_call()
    time.sleep(10)  # mock meeting ends ~12 s after joining
    assert not joiner.still_in_call()


def test_signed_in_join_now(joiner):
    joiner.join((FIX / "mock_meet_signed_in.html").as_uri())
    assert joiner.driver.execute_script("return [window.mic, window.cam]") == ["Turn on microphone", "Turn on camera"]


def test_blocked_meeting_message(joiner):
    import intellimeet.meet_joiner as mj

    with pytest.raises(mj.MeetJoinError, match="can't join this video call"):
        joiner.join((FIX / "mock_meet_blocked.html").as_uri())
