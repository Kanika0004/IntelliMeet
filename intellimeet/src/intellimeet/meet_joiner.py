"""Join a Google Meet call with Selenium-driven Chrome.

The bot uses its OWN Chrome profile (separate from your everyday Chrome). Sign in to
Google in that profile once - from the web app (Settings -> Sign in bot) or with
``intellimeet login`` - and every later run reuses the session. Google usually blocks
scripted password logins, so EMAIL_ID / EMAIL_PASSWORD are only a fallback.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Callable, Optional

from .config import Settings

log = logging.getLogger(__name__)

MEET_LINK_RE = re.compile(
    r"^(https?://)?meet\.google\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}(\?.*)?$", re.IGNORECASE
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ACCOUNT_MARKER = "intellimeet_account.txt"

# Join buttons in preference order. "Switch here" is excluded on purpose: it would kick
# the same account off another device.
JOIN_LABELS = ["Join now", "Ask to join", "Join here too", "Join anyway", "Join meeting"]
# Pre-join pop-ups to get out of the way.
DISMISS_LABELS = [
    "Continue without microphone and camera",
    "Continue without microphone",
    "Continue without camera",
    "Got it",
    "Dismiss",
    "No thanks",
]

# All DOM inspection runs as one JavaScript call, so it is fast and tolerant of Meet's
# frequently changing class names.
_JS = r"""
const visible = el => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
  return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
const enabled = el => !el.disabled && el.getAttribute('aria-disabled') !== 'true';
const label = el => ((el.getAttribute('aria-label') || '') + ' ' + (el.innerText || '')).toLowerCase();
const clickables = () => [...document.querySelectorAll('button, [role="button"]')].filter(visible);
const text = () => (document.body ? document.body.innerText : '').toLowerCase();
"""

JS_FIND = _JS + r"""
const labels = arguments[0].map(l => l.toLowerCase());
const els = clickables().filter(enabled);
for (const l of labels) { const el = els.find(e => label(e).includes(l)); if (el) return [l, el]; }
return null;
"""

# Turn off mic/camera: aria-labels, data-is-muted state, and the original repo's selectors.
JS_DEVICES_OFF = _JS + r"""
const res = {mic: 'unknown', cam: 'unknown', clicked: []};
const els = clickables();
const isMic = e => /microphone|mic\b/.test(label(e)) || e.closest('[data-anchor-id="hw0c9"]');
const isCam = e => /camera/.test(label(e)) || e.closest('[data-anchor-id="psRWwc"]');
for (const e of els) {
  const l = label(e); const muted = e.getAttribute('data-is-muted');
  const kind = isMic(e) ? 'mic' : isCam(e) ? 'cam' : null;
  if (!kind) continue;
  const on = muted === 'false' || l.includes('turn off');
  const off = muted === 'true' || l.includes('turn on') || l.includes('problem') || l.includes('blocked') || l.includes('not found');
  if (on && !off) { e.click(); res.clicked.push(kind); res[kind] = 'was-on'; }
  else if (off) res[kind] = res[kind] === 'was-on' ? 'was-on' : 'off';
}
return res;
"""

JS_NAME_INPUT = _JS + r"""
const ins = [...document.querySelectorAll('input')].filter(i => visible(i) && (!i.type || i.type === 'text'));
return ins.find(i => /name/i.test((i.getAttribute('aria-label')||'') + (i.placeholder||''))) || (ins.length === 1 ? ins[0] : null);
"""

JS_SET_VALUE = r"""
const [el, value] = arguments; el.focus();
const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
setter.call(el, value);
el.dispatchEvent(new Event('input', {bubbles: true})); el.dispatchEvent(new Event('change', {bubbles: true}));
return el.value;
"""

JS_STATE = _JS + r"""
const t = text();
const has = s => t.includes(s);
if ([...document.querySelectorAll('[aria-label]')].some(e => visible(e) && /leave call/i.test(e.getAttribute('aria-label'))))
  return 'in_call';
if (has('you left the meeting') || has('you\'ve been removed') || has('the call has ended') || has('return to home screen')
    || has('this meeting has ended') || has('you left the call')) return 'ended';
if (has('asking to be let in') || has('someone in the call') && has('let you in') || has('please wait until a meeting host')
    || has('you\'ll join the call when someone lets you in')) return 'waiting';
if (has('ready to join') || has('ask to join') || has('join now') || has('what\'s your name')) return 'prejoin';
return 'loading';
"""

# Page text -> friendly message
BLOCK_MESSAGES = [
    ("You can't join this video call",
     "Google Meet refused entry (\"You can't join this video call\"). Meetings from personal Gmail accounts only "
     "admit people signed in to Google, and college/work meetings may only admit their own accounts. "
     "Open Settings -> Sign in bot and sign in with a Google account that is allowed to join."),
    ("denied your request", "Someone in the meeting denied the bot's request to join."),
    ("No one responded to your request", "No one admitted the bot in time. Ask the host to admit it."),
    ("You've been removed from the meeting", "The bot was removed from the meeting."),
    ("Check your meeting code", "This meeting code doesn't exist. Check the link."),
    ("Invalid video call name", "This meeting code doesn't exist. Check the link."),
    ("isn't available", "This meeting isn't available. Check the link or wait until the host has started it."),
]


def normalize_meet_link(link: str) -> str:
    link = link.strip()
    if not MEET_LINK_RE.match(link):
        raise ValueError("Not a valid Google Meet link (expected meet.google.com/abc-defg-hij)")
    if not link.lower().startswith("http"):
        link = "https://" + link
    return link


def with_english(link: str) -> str:
    """Force Meet's UI to English so button labels match."""
    return link + ("&" if "?" in link else "?") + "hl=en" if "hl=" not in link else link


def profile_dir(settings: Settings) -> Path:
    """The bot's persistent Chrome profile (always set, so a sign-in survives restarts)."""
    p = Path(settings.chrome_profile_dir) if settings.chrome_profile_dir else Path(settings.data_dir) / "chrome-profile"
    return p.expanduser().resolve()


def signed_in_account(settings: Settings) -> Optional[str]:
    marker = profile_dir(settings) / ACCOUNT_MARKER
    if marker.exists():
        return marker.read_text(encoding="utf-8").strip() or "Google account"
    return None


def find_chrome(settings: Settings) -> Optional[str]:
    """Path to the Chrome executable (CHROME_BINARY, standard install locations, or PATH)."""
    import os
    import shutil

    if settings.chrome_binary and Path(settings.chrome_binary).exists():
        return settings.chrome_binary
    candidates = []
    for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    candidates.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    for c in candidates:
        if c.exists():
            return str(c)
    for name in ("google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


class MeetJoinError(RuntimeError):
    pass


class BrowserClosed(MeetJoinError):
    pass


def _is_closed_error(exc: Exception) -> bool:
    name = exc.__class__.__name__
    text = str(exc)
    return name in {"NoSuchWindowException", "InvalidSessionIdException"} or any(
        s in text for s in ("not connected to DevTools", "target window already closed", "browser has closed")
    )


class MeetJoiner:
    """Controls a Chrome window that joins (and later leaves) a Google Meet."""

    def __init__(
        self,
        settings: Settings,
        on_status: Optional[Callable[[str], None]] = None,
        debug_dir: Optional[Path] = None,
    ):
        self.settings = settings
        self.driver = None
        self.debug_dir = Path(debug_dir) if debug_dir else Path(settings.data_dir) / "debug"
        self.last_screenshot: Optional[Path] = None
        self._status = on_status or (lambda msg: log.info(msg))

    # ------------------------------------------------------------------ browser
    def start_browser(self) -> None:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        profile = profile_dir(self.settings)
        profile.mkdir(parents=True, exist_ok=True)

        opts = Options()
        opts.add_argument(f"--user-data-dir={profile}")
        opts.add_argument("--profile-directory=Default")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--start-maximized")
        opts.add_argument("--no-first-run")
        opts.add_argument("--no-default-browser-check")
        opts.add_argument("--lang=en-US")  # button labels are matched in English
        opts.add_argument("--autoplay-policy=no-user-gesture-required")  # meeting audio must play
        opts.add_argument("--disable-features=MediaSessionService")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.add_experimental_option(
            "prefs",
            {
                # Block mic + camera for the bot entirely: it only listens, and this makes it
                # impossible for Meet to turn them on.
                "profile.default_content_setting_values.media_stream_mic": 2,
                "profile.default_content_setting_values.media_stream_camera": 2,
                "profile.default_content_setting_values.notifications": 2,
                "intl.accept_languages": "en-US,en",
            },
        )
        import os as _os

        if hasattr(_os, "geteuid") and _os.geteuid() == 0:  # Chrome refuses to run as root without this
            opts.add_argument("--no-sandbox")
            opts.add_argument("--disable-dev-shm-usage")
        if self.settings.chrome_binary:
            opts.binary_location = self.settings.chrome_binary
        if self.settings.headless:
            opts.add_argument("--headless=new")
            opts.add_argument("--window-size=1280,800")

        self._status("Launching Chrome")
        try:
            self.driver = webdriver.Chrome(options=opts)
        except Exception as exc:  # noqa: BLE001
            detail = (getattr(exc, "msg", None) or str(exc)).strip().split("\n")[0][:200]
            if "already in use" in str(exc) or "Chrome instance exited" in str(exc):
                raise MeetJoinError(
                    "Chrome could not start with the bot's profile. Close any other IntelliMeet Chrome window "
                    f"(e.g. the sign-in window) and try again. ({detail})"
                ) from exc
            if "only supports Chrome version" in str(exc):
                raise MeetJoinError(f"ChromeDriver doesn't match your Chrome version - update Chrome and try again. ({detail})") from exc
            raise
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
        )
        for perm in ("audioCapture", "videoCapture"):
            try:
                self.driver.execute_cdp_cmd(
                    "Browser.setPermission",
                    {"permission": {"name": perm}, "setting": "denied", "origin": "https://meet.google.com"},
                )
            except Exception:  # noqa: BLE001
                pass

    def alive(self) -> bool:
        try:
            _ = self.driver.current_url
            return True
        except Exception:  # noqa: BLE001
            return False

    def screenshot(self, name: str) -> Optional[Path]:
        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            path = self.debug_dir / f"{name}.png"
            self.driver.save_screenshot(str(path))
            self.last_screenshot = path
            return path
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------ sign-in
    def open_login_window(self) -> None:
        """Open Google sign-in in the bot profile so a person can sign in by hand."""
        self.start_browser()
        self.driver.get("https://accounts.google.com/ServiceLogin?continue=https://myaccount.google.com/")

    def detect_account(self) -> Optional[str]:
        """Return the signed-in email if Chrome is really on the Google Account page.

        Checks the page's *host* - the sign-in URL contains "myaccount.google.com" in its
        ?continue= parameter, so a plain substring check gives false positives.
        """
        from urllib.parse import urlparse

        try:
            if urlparse(self.driver.current_url).netloc != "myaccount.google.com":
                return None
            emails = EMAIL_RE.findall(self.driver.page_source)
            emails = [e for e in emails if not e.lower().endswith(("google.com", "gstatic.com", "googleusercontent.com"))]
            return emails[0] if emails else "Google account"
        except Exception:  # noqa: BLE001
            return None

    def verify_signed_in(self) -> Optional[str]:
        """Open the profile (hidden) and check whether it is signed in to Google."""
        headless = self.settings.headless
        self.settings.headless = True
        try:
            self.start_browser()
            self.driver.get("https://myaccount.google.com/")
            time.sleep(3)
            account = self.detect_account()
            if account:
                self.save_account(account)
            else:
                (profile_dir(self.settings) / ACCOUNT_MARKER).unlink(missing_ok=True)
            return account
        finally:
            self.settings.headless = headless
            self.quit()

    def save_account(self, account: str) -> None:
        (profile_dir(self.settings) / ACCOUNT_MARKER).write_text(account, encoding="utf-8")

    def google_login(self) -> Optional[str]:
        """Make sure the profile is signed in. Returns the account, or None for guest mode."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait

        d = self.driver
        try:
            d.get("https://myaccount.google.com/")
            time.sleep(3)
        except Exception as exc:  # noqa: BLE001
            if _is_closed_error(exc):
                raise
            log.warning("couldn't check Google sign-in (%s); continuing", str(exc).splitlines()[0])
            return signed_in_account(self.settings)
        account = self.detect_account()
        if account:
            self.save_account(account)
            self._status(f"Signed in as {account}")
            return account

        # Not signed in: forget any stale marker.
        (profile_dir(self.settings) / ACCOUNT_MARKER).unlink(missing_ok=True)
        if not (self.settings.email and self.settings.password):
            self._status("Bot is not signed in to Google - joining as a guest")
            return None

        self._status("Signing in to Google")
        d.get("https://accounts.google.com/ServiceLogin?continue=https://myaccount.google.com/")
        wait = WebDriverWait(d, 20)
        wait.until(EC.element_to_be_clickable((By.ID, "identifierId"))).send_keys(self.settings.email, Keys.ENTER)
        pwd = wait.until(EC.element_to_be_clickable((By.NAME, "Passwd")))
        time.sleep(1)
        pwd.send_keys(self.settings.password, Keys.ENTER)
        try:
            WebDriverWait(d, 30).until(lambda drv: "myaccount.google.com" in drv.current_url)
        except Exception as exc:  # noqa: BLE001
            self.screenshot("login-failed")
            raise MeetJoinError(
                "Google blocked the automatic sign-in (2-step verification or 'browser not secure'). "
                "Use Settings -> Sign in bot to sign in by hand once."
            ) from exc
        account = self.detect_account() or self.settings.email
        self.save_account(account)
        return account

    # ------------------------------------------------------------------ helpers
    def find_button(self, labels: list[str]):
        try:
            res = self.driver.execute_script(JS_FIND, labels)
            return (res[0], res[1]) if res else None
        except Exception as exc:  # noqa: BLE001
            if _is_closed_error(exc):
                raise
            return None

    def _click(self, el) -> bool:
        try:
            el.click()
            return True
        except Exception:  # noqa: BLE001
            try:
                self.driver.execute_script("arguments[0].click();", el)
                return True
            except Exception:  # noqa: BLE001
                return False

    def dismiss_popups(self) -> None:
        for _ in range(3):
            hit = self.find_button(DISMISS_LABELS)
            if not hit:
                return
            log.info("dismissing pop-up: %s", hit[0])
            self._click(hit[1])
            time.sleep(0.6)

    def state(self) -> str:
        try:
            return self.driver.execute_script(JS_STATE) or "loading"
        except Exception as exc:  # noqa: BLE001
            if _is_closed_error(exc):
                return "closed"
            return "loading"

    def _blocked_message(self) -> Optional[str]:
        try:
            text = self.driver.execute_script("return document.body ? document.body.innerText : ''") or ""
        except Exception:  # noqa: BLE001
            return None
        for needle, msg in BLOCK_MESSAGES:
            if needle.lower() in text.lower():
                return msg
        return None

    def save_debug(self, name: str) -> Optional[Path]:
        shot = self.screenshot(name)
        try:
            (self.debug_dir / f"{name}.html").write_text(self.driver.page_source, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return shot

    def _fail(self, message: str, tag: str):
        shot = self.save_debug(tag)
        if shot:
            message += f" Screenshot saved: {shot}"
        raise MeetJoinError(message)

    def turn_off_devices(self) -> dict:
        """Make sure mic and camera are off (they are also blocked at browser level)."""
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.common.keys import Keys

        result = {}
        for attempt in range(3):
            try:
                result = self.driver.execute_script(JS_DEVICES_OFF) or {}
            except Exception:  # noqa: BLE001
                result = {}
            if not result.get("clicked"):
                break
            time.sleep(0.8)
        if attempt == 2 and result.get("clicked"):
            # Still on after clicking: fall back to Meet's keyboard shortcuts.
            for key in ("d", "e"):
                ActionChains(self.driver).key_down(Keys.CONTROL).send_keys(key).key_up(Keys.CONTROL).perform()
                time.sleep(0.4)
        log.info("devices: %s", result)
        return result

    def enter_name(self) -> bool:
        from selenium.webdriver.common.keys import Keys

        try:
            inp = self.driver.execute_script(JS_NAME_INPUT)
        except Exception:  # noqa: BLE001
            inp = None
        if not inp:
            return False
        name = self.settings.bot_display_name or "IntelliMeet Bot"
        try:
            if (inp.get_attribute("value") or "").strip() == name:
                return True
            self._click(inp)
            inp.send_keys(Keys.CONTROL, "a")
            inp.send_keys(name)
            time.sleep(0.5)
            if (inp.get_attribute("value") or "").strip() != name:
                self.driver.execute_script(JS_SET_VALUE, inp, name)
        except Exception:  # noqa: BLE001
            self.driver.execute_script(JS_SET_VALUE, inp, name)
        self._status(f"Entered name '{name}'")
        return True

    def still_in_call(self) -> bool:
        """False only when Meet clearly shows the call is over or the window is gone."""
        st = self.state()
        return st not in ("ended", "closed")

    # ------------------------------------------------------------------ meeting
    def join(self, link: str, admit_timeout: Optional[int] = None, should_abort: Callable[[], bool] = lambda: False, tag: str = "join") -> None:
        admit_timeout = admit_timeout or self.settings.admit_timeout or 300
        try:
            self._join(link, admit_timeout, should_abort, tag)
        except MeetJoinError:
            raise
        except Exception as exc:  # noqa: BLE001
            if _is_closed_error(exc):
                raise BrowserClosed(
                    "The bot's Chrome window was closed. Leave that window open - the bot closes it by itself."
                ) from exc
            raise

    def _join(self, link: str, admit_timeout: int, should_abort: Callable[[], bool], tag: str) -> None:
        d = self.driver
        link = with_english(normalize_meet_link(link))
        self._status("Opening meeting link")
        d.get(link)

        # 1. Wait for the pre-join screen (or a refusal page).
        self._status("Waiting for Google Meet to load")
        end = time.time() + 60
        while True:
            if should_abort():
                raise MeetJoinError("Cancelled")
            if time.time() > end:
                self._fail("Google Meet's join screen didn't appear within 60 seconds.", f"{tag}-no-prejoin")
            if "accounts.google.com" in d.current_url:
                self._fail("Google asked the bot to sign in. Open Settings and click 'Sign in bot'.", f"{tag}-signin")
            self.dismiss_popups()
            st = self.state()
            if st == "in_call":
                self._status("Joined the meeting")
                return
            blocked = self._blocked_message()
            if blocked and not self.find_button(JOIN_LABELS):
                self._fail(blocked, f"{tag}-blocked")
            if st == "prejoin" or self.find_button(JOIN_LABELS):
                break
            time.sleep(1)
        time.sleep(2)  # let device toggles render

        # 2. Mic + camera off (belt and braces: they are blocked at browser level too).
        self._status("Turning off microphone and camera")
        self.dismiss_popups()
        self.turn_off_devices()

        # 3. Guests need a name before the join button is enabled.
        self.enter_name()

        # 4. Click the join button.
        self._status("Requesting to join")
        clicked = None
        end = time.time() + 40
        while time.time() < end:
            if should_abort():
                raise MeetJoinError("Cancelled")
            self.dismiss_popups()
            hit = self.find_button(JOIN_LABELS)
            if not hit:
                # Fallback used by the original Google-Meet-Bot project.
                from selenium.webdriver.common.by import By

                els = [e for e in d.find_elements(By.CSS_SELECTOR, 'button[jsname="Qx7uuf"]') if e.is_displayed()]
                hit = ("join button", els[0]) if els else None
            if hit and self._click(hit[1]):
                clicked = hit[0]
                break
            if self.enter_name():
                continue
            blocked = self._blocked_message()
            if blocked:
                self._fail(blocked, f"{tag}-blocked")
            time.sleep(1)
        if not clicked:
            self._fail("Couldn't find an enabled 'Join now' / 'Ask to join' button.", f"{tag}-no-button")
        log.info("clicked '%s'", clicked)

        # 5. Wait until we're inside the call.
        asked = "ask" in clicked.lower()
        self._status("Waiting to be admitted - admit the bot from Meet" if asked else "Joining the call")
        end = time.time() + admit_timeout
        while time.time() < end:
            if should_abort():
                raise MeetJoinError("Cancelled while waiting to be admitted")
            st = self.state()
            if st == "in_call":
                time.sleep(1)
                self.dismiss_popups()
                self.turn_off_devices()
                self._status("Joined the meeting")
                return
            if st == "closed":
                raise BrowserClosed("The bot's Chrome window was closed.")
            blocked = self._blocked_message()
            if blocked:
                self._fail(blocked, f"{tag}-refused")
            if st == "prejoin" and not asked:
                # 'Join now' sometimes needs a second click once devices settle.
                hit = self.find_button(JOIN_LABELS)
                if hit:
                    self._click(hit[1])
            time.sleep(2)
        self._fail(f"Not admitted within {admit_timeout // 60} minutes.", f"{tag}-timeout")

    def leave(self) -> None:
        if not self.driver:
            return
        try:
            hit = self.find_button(["Leave call"])
            if hit:
                self._click(hit[1])
                time.sleep(1)
        except Exception:  # noqa: BLE001
            pass
        self.quit()

    def quit(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except Exception:  # noqa: BLE001
                pass
            self.driver = None
