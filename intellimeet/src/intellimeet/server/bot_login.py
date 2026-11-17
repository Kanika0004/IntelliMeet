"""Interactive Google sign-in for the bot's Chrome profile, started from the web app."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time

from ..config import Settings
from ..meet_joiner import ACCOUNT_MARKER, MeetJoiner, find_chrome, profile_dir, signed_in_account

log = logging.getLogger(__name__)


class BotLogin:
    """Opens a Chrome window on Google's sign-in page and watches for success."""

    TIMEOUT = 600

    def __init__(self, settings: Settings, active_flag: threading.Event):
        self.settings = settings
        self.active = active_flag
        self.message: str | None = None
        self._proc: subprocess.Popen | None = None

    def status(self) -> dict:
        return {
            "signed_in": signed_in_account(self.settings) is not None,
            "account": signed_in_account(self.settings),
            "login_in_progress": self.active.is_set(),
            "message": self.message,
            "profile_dir": str(profile_dir(self.settings)),
            "password_fallback": bool(self.settings.email and self.settings.password),
            # On a hosted server the sign-in window opens on a virtual display, viewed through noVNC.
            "remote_screen": os.environ.get("REMOTE_SCREEN_URL") or None,
        }

    def start(self) -> None:
        if self.active.is_set():
            raise RuntimeError("The sign-in window is already open")
        self.active.set()
        self.message = "Opening Chrome…"
        threading.Thread(target=self._run, name="bot-login", daemon=True).start()

    def cancel(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def _run(self) -> None:
        """Open a *normal* Chrome window (not automation-controlled - Google often blocks sign-in
        in those) on the bot's profile. When the person closes it, check whether it is signed in."""
        try:
            chrome = find_chrome(self.settings)
            if not chrome:
                self.message = "Google Chrome wasn't found. Install Chrome, or set CHROME_BINARY in .env to chrome.exe's path."
                return
            prof = profile_dir(self.settings)
            prof.mkdir(parents=True, exist_ok=True)
            self._proc = subprocess.Popen(
                [chrome, f"--user-data-dir={prof}", "--profile-directory=Default", "--no-first-run",
                 "--no-default-browser-check", "--new-window",
                 "https://accounts.google.com/ServiceLogin?continue=https://myaccount.google.com/"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self.message = ("Sign in to Google in the new Chrome window, then CLOSE that window to finish."
                            if not os.environ.get("REMOTE_SCREEN_URL") else
                            "Open the server screen, sign in to Google in the Chrome window there, then close that window.")
            end = time.time() + self.TIMEOUT
            while self._proc.poll() is None:
                if time.time() > end:
                    self._proc.terminate()
                    self.message = "Sign-in timed out after 10 minutes."
                    return
                time.sleep(1)
            time.sleep(2)  # let Chrome release the profile
            self.message = "Checking sign-in…"
            account = MeetJoiner(self.settings).verify_signed_in()
            self.message = f"Signed in as {account}" if account else (
                "The bot is still not signed in. Click 'Sign in bot', finish signing in to Google, then close the window.")
        except Exception as exc:  # noqa: BLE001
            log.exception("bot login failed")
            from .worker import friendly_error

            self.message = friendly_error(exc)
        finally:
            self._proc = None
            self.active.clear()

    def sign_out(self) -> None:
        if self.active.is_set():
            raise RuntimeError("Close the sign-in window first")
        prof = profile_dir(self.settings)
        (prof / ACCOUNT_MARKER).unlink(missing_ok=True)
        shutil.rmtree(prof, ignore_errors=True)
        self.message = "Signed out - the bot's Chrome profile was cleared."
