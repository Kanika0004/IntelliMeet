"""Command-line interface.

  intellimeet serve                  start the web app (dashboard + API)
  intellimeet login                  sign in to Google once in the bot's Chrome profile
  intellimeet join --meet-link URL   join, record and analyse from the terminal
  intellimeet process FILE           transcribe + analyse an existing recording/transcript
  intellimeet devices                list audio input devices
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import Settings


def _settings(args) -> Settings:
    return Settings.from_env(getattr(args, "env", None))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="intellimeet", description="IntelliMeet - AI meeting assistant for Google Meet")
    p.add_argument("--env", help="path to .env file", default=None)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("serve", help="run the web dashboard and API")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--reload", action="store_true")

    sub.add_parser("login", help="open Chrome with the bot profile to sign in to Google manually")

    j = sub.add_parser("join", help="join a meeting and record it")
    j.add_argument("--meet-link")
    j.add_argument("--duration", type=int, help="seconds to record")
    j.add_argument("--no-analysis", action="store_true")

    pr = sub.add_parser("process", help="transcribe and analyse an audio or transcript file")
    pr.add_argument("file")
    pr.add_argument("--no-analysis", action="store_true")

    sub.add_parser("devices", help="list audio input devices")
    sub.add_parser("test-audio", help="record 5 s with every capture method and report which one hears sound")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    cmd = args.cmd or "serve"
    settings = _settings(args)

    if cmd == "serve":
        import uvicorn

        uvicorn.run(
            "intellimeet.server.app:app",
            host=getattr(args, "host", None) or settings.host,
            port=getattr(args, "port", None) or settings.port,
            reload=getattr(args, "reload", False),
        )
        return 0

    if cmd == "login":
        import subprocess

        from .meet_joiner import MeetJoiner, find_chrome, profile_dir

        chrome = find_chrome(settings)
        if not chrome:
            print("Google Chrome not found. Set CHROME_BINARY in .env to chrome.exe's path.", file=sys.stderr)
            return 1
        prof = profile_dir(settings)
        prof.mkdir(parents=True, exist_ok=True)
        print(f"Bot Chrome profile: {prof}")
        print("Sign in to Google in the Chrome window that opens, then CLOSE that window...")
        subprocess.run([chrome, f"--user-data-dir={prof}", "--profile-directory=Default", "--no-first-run",
                        "--new-window", "https://accounts.google.com/ServiceLogin?continue=https://myaccount.google.com/"])
        account = MeetJoiner(settings).verify_signed_in()
        print(f"Signed in as {account}" if account else "Not signed in - run `intellimeet login` again.")
        return 0 if account else 1

    if cmd == "test-audio":
        import tempfile
        import threading

        from .recorder import IS_WINDOWS, AudioRecorder

        print("Play a video or music now - recording 5 seconds with each method...\n")
        rec = AudioRecorder(settings)
        methods = []
        if IS_WINDOWS:
            methods.append(("System audio - WASAPI (PyAudioWPatch)", rec._record_wasapi))
        methods.append(("System audio - soundcard", rec._record_soundcard))
        methods.append(("Input device", rec._record_device))
        for label, fn in methods:
            out = Path(tempfile.gettempdir()) / f"intellimeet-test-{len(label)}.wav"
            try:
                st = fn(out, 5, threading.Event(), None, None)
                verdict = "SILENT" if st.silent else "OK - sound captured"
                print(f"  {label:42s} peak {st.peak * 100:5.1f}%  {verdict}   ({st.source})")
            except Exception as exc:  # noqa: BLE001
                print(f"  {label:42s} ERROR: {exc}")
        print("\nIn Settings -> Audio capture, choose the method/device that shows 'OK'.")
        return 0

    if cmd == "devices":
        from .recorder import AudioRecorder

        print(AudioRecorder.list_devices())
        return 0

    if cmd == "join":
        from .pipeline import run_pipeline

        if not (args.meet_link or settings.meet_link):
            print("Provide --meet-link or set MEET_LINK in .env", file=sys.stderr)
            return 1
        result = run_pipeline(settings, args.meet_link, args.duration, analyze=not args.no_analysis)
        print(json.dumps(result.get("analysis") or result["transcript"], indent=2))
        return 0

    if cmd == "process":
        from .pipeline import process_audio

        result = process_audio(
            settings, Path(args.file), lambda st, m: logging.info("[%s] %s", st, m), analyze=not args.no_analysis
        )
        print(json.dumps(result, indent=2))
        return 0

    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
