import time

import pytest


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    import os
    d = tmp_path_factory.mktemp("data")
    os.environ.update(DATA_DIR=str(d), ANALYZER="basic", OPENAI_API_KEY="", GEMINI_API_KEY="")
    os.environ["INTELLIMEET_ENV"] = str(d / ".env")
    from fastapi.testclient import TestClient
    from intellimeet.server.app import app
    with TestClient(app) as c:
        yield c


def wait_done(client, mid, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        m = client.get(f"/api/meetings/{mid}").json()
        if m["status"] in ("completed", "failed"):
            return m
        time.sleep(0.2)
    raise AssertionError("timeout")


def test_sample_and_stats(client):
    ids = client.post("/api/sample").json()["ids"]
    assert len(ids) == 2
    s = client.get("/api/stats").json()
    assert s["completed_meetings"] == 2 and s["open_action_items"] > 0
    assert client.get("/api/meetings", params={"q": "chrome profile"}).json()


def test_upload_transcript_flow(client):
    txt = b"[00:00] Kanika: Welcome everyone, this is the design review.\n[00:20] Ayush will send the mockups by Friday.\n[00:40] We decided to ship the dark theme.\n"
    r = client.post("/api/meetings/upload", files={"file": ("design-review.txt", txt, "text/plain")}, data={"title": ""})
    assert r.status_code == 201
    m = wait_done(client, r.json()["id"])
    assert m["status"] == "completed", m["error"]
    assert m["analysis"]["action_items"]
    mid = m["id"]
    assert client.patch(f"/api/meetings/{mid}/action-items/0", json={"done": True}).json()["done"] is True
    reply = client.post(f"/api/meetings/{mid}/chat", json={"message": "When are the mockups due?"}).json()
    assert reply["role"] == "assistant" and "Friday" in reply["content"]
    md = client.get(f"/api/meetings/{mid}/export").text
    assert "## Action items" in md and "[x]" in md
    assert client.delete(f"/api/meetings/{mid}").status_code == 204


def test_rejects_bad_link_and_file(client):
    assert client.post("/api/meetings", json={"meet_link": "https://zoom.us/j/1"}).status_code == 422
    r = client.post("/api/meetings/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 422


def test_bot_status(client):
    s = client.get("/api/bot/status").json()
    assert s["signed_in"] is False and s["login_in_progress"] is False
    assert "chrome-profile" in s["profile_dir"]


def test_settings_roundtrip(client):
    from intellimeet.server.app import settings
    v = client.get("/api/settings").json()["values"]
    assert "openai_api_key" in v and isinstance(v["openai_api_key"], dict)
    r = client.put("/api/settings", json={"bot_display_name": "Notes Bot", "duration": 900, "openai_api_key": "sk-test-1234567890"})
    assert r.status_code == 200, r.text
    v = r.json()["values"]
    assert v["bot_display_name"] == "Notes Bot" and v["openai_api_key"]["set"] and "1234567890" not in v["openai_api_key"]["masked"]
    assert settings.duration == 900
    assert "OPENAI_API_KEY=sk-test-1234567890" in settings.env_path.read_text()
    assert client.put("/api/settings", json={"analyzer": "nope"}).status_code == 422
    client.put("/api/settings", json={"openai_api_key": ""})


def test_audio_devices_endpoint(client):
    d = client.get("/api/audio/devices").json()
    assert "speakers" in d and "inputs" in d and "errors" in d


def test_user_accounts_isolate_meetings(client, monkeypatch, tmp_path):
    import intellimeet.server.app as appmod
    from fastapi.testclient import TestClient

    monkeypatch.setattr(appmod, "AUTH", True)
    other = TestClient(appmod.app)
    assert client.get("/api/meetings").status_code == 401
    admin = client.post("/api/auth/register", json={"name": "A", "email": "a@kiit.ac.in", "password": "password1"}).json()
    user = other.post("/api/auth/register", json={"name": "B", "email": "b@kiit.ac.in", "password": "password2"}).json()
    assert admin["is_admin"] and not user["is_admin"]
    f = tmp_path / "t.txt"
    f.write_text("[00:00] Ayush will send the mockups by Friday.\n")
    mid = other.post("/api/meetings/upload", files={"file": ("t.txt", f.open("rb"))}).json()["id"]
    wait_done(other, mid)
    assert client.get(f"/api/meetings/{mid}").status_code == 404          # not visible to other users
    assert other.get("/api/settings").status_code == 403                  # settings are admin-only
    assert client.get("/api/settings").status_code == 200
    assert other.post("/api/auth/login", json={"email": "b@kiit.ac.in", "password": "wrong"}).status_code == 401
    other.post("/api/auth/logout")
    assert other.get("/api/meetings").status_code == 401
