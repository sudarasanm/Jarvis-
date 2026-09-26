"""Control the computer: open and close apps, open websites, type, press keys, draft emails.

Used both by the quick voice commands in skills/apps.py and by Claude's tools in ai.py.
Every function returns a short sentence Jarvis can speak.
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
import time
import urllib.parse
import webbrowser

SYSTEM = platform.system()

WEBSITES = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "maps": "https://maps.google.com",
    "google maps": "https://maps.google.com",
    "wikipedia": "https://www.wikipedia.org",
    "netflix": "https://www.netflix.com",
    "hotstar": "https://www.hotstar.com",
    "disney hotstar": "https://www.hotstar.com",
    "jiohotstar": "https://www.hotstar.com",
    "prime video": "https://www.primevideo.com",
    "amazon prime": "https://www.primevideo.com",
    "instagram": "https://www.instagram.com",
    "facebook": "https://www.facebook.com",
    "linkedin": "https://www.linkedin.com",
    "reddit": "https://www.reddit.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
    "whatsapp web": "https://web.whatsapp.com",
    "spotify web": "https://open.spotify.com",
}

# Spoken name -> what Windows' "start" / ShellExecute understands.
WINDOWS_APPS = {
    "chrome": "chrome", "google chrome": "chrome",
    "edge": "msedge", "microsoft edge": "msedge",
    "firefox": "firefox", "brave": "brave",
    "notepad": "notepad", "calculator": "calc", "paint": "mspaint",
    "file explorer": "explorer", "explorer": "explorer", "files": "explorer", "my files": "explorer",
    "terminal": "wt", "windows terminal": "wt",
    "command prompt": "cmd", "cmd": "cmd", "powershell": "powershell",
    "vs code": "code", "visual studio code": "code", "vscode": "code",
    "word": "winword", "microsoft word": "winword", "excel": "excel", "microsoft excel": "excel",
    "powerpoint": "powerpnt", "outlook": "outlook",
    "settings": "ms-settings:", "task manager": "taskmgr", "control panel": "control",
    "spotify": "spotify:", "whatsapp": "whatsapp:", "camera": "microsoft.windows.camera:",
    "store": "ms-windows-store:", "microsoft store": "ms-windows-store:", "snipping tool": "snippingtool",
}

MAC_APPS = {
    "chrome": "Google Chrome", "google chrome": "Google Chrome", "safari": "Safari", "firefox": "Firefox",
    "terminal": "Terminal", "finder": "Finder", "files": "Finder", "notes": "Notes", "calculator": "Calculator",
    "vs code": "Visual Studio Code", "visual studio code": "Visual Studio Code", "spotify": "Spotify",
    "mail": "Mail", "settings": "System Settings", "whatsapp": "WhatsApp",
}

LINUX_APPS = {
    "chrome": "google-chrome", "google chrome": "google-chrome", "firefox": "firefox",
    "terminal": "x-terminal-emulator", "files": "nautilus", "file explorer": "nautilus",
    "vs code": "code", "visual studio code": "code", "calculator": "gnome-calculator",
}

# Spoken name -> process names to close (lower case, without .exe).
PROCESS_NAMES = {
    "chrome": ["chrome", "google chrome"], "google chrome": ["chrome", "google chrome"],
    "edge": ["msedge", "microsoft edge"], "microsoft edge": ["msedge", "microsoft edge"],
    "vs code": ["code", "visual studio code"], "visual studio code": ["code", "visual studio code"],
    "word": ["winword", "microsoft word"], "excel": ["excel", "microsoft excel"],
    "powerpoint": ["powerpnt", "microsoft powerpoint"], "calculator": ["calculatorapp", "calculator", "calc"],
    "terminal": ["windowsterminal", "terminal"], "windows terminal": ["windowsterminal"],
    "command prompt": ["cmd"], "paint": ["mspaint"], "task manager": ["taskmgr"],
    "brave": ["brave"], "firefox": ["firefox"], "ollama": ["ollama app", "ollama"],
    "settings": ["systemsettings"], "system settings": ["systemsettings"], "chatgpt": ["chatgpt"],
    "spotify": ["spotify"], "whatsapp": ["whatsapp"], "notepad": ["notepad"],
}

# Apps that may be holding unsaved work: never force-close these.
SAVES_WORK = {"word", "microsoft word", "excel", "microsoft excel", "powerpoint", "notepad", "vs code",
              "visual studio code", "paint", "outlook"}

# Never close these: they would take down Windows' desktop, the OS, or Jarvis itself.
PROTECTED = {"explorer", "file explorer", "files", "finder", "python", "pythonw", "jarvis", "yourself",
             "system", "windows", "svchost", "csrss", "winlogon", "dwm", "lsass", "services", "wininit", "smss"}


def _normalize(name: str) -> str:
    name = name.lower().strip(" .!?,")
    name = re.sub(r"^(?:all\s+(?:of\s+)?)?(?:(?:the|my|a|an)\s+)?", "", name)
    return re.sub(r"\s+(apps?|applications?|programs?|browsers?|windows?)$", "", name).strip()


def open_url(url: str) -> None:
    webbrowser.open(url, new=2)


def open_website(name: str) -> str:
    key = _normalize(name)
    if key in WEBSITES:
        url = WEBSITES[key]
    elif "." in key and " " not in key:
        url = key if key.startswith("http") else f"https://{key}"
    else:
        url = f"https://www.{key.replace(' ', '')}.com"
    open_url(url)
    return f"Opening {name}."


def _website_key(key: str) -> str | None:
    if key in WEBSITES:
        return key
    squashed = key.replace(" ", "")
    return next((k for k in WEBSITES if k.replace(" ", "") == squashed), None)


# Words that mean speech recognition garbled the request ("open close the system").
NOT_A_NAME = {"close", "open", "the", "a", "an", "and", "it", "this", "that", "something", "up", "all"}

_installed: dict[str, str] | None = None


def installed_apps(refresh: bool = False) -> dict[str, str]:
    """Apps in the Windows Start menu: {'photoshop 2024': 'Adobe.Photoshop...'} (name lower-cased -> AppID)."""
    global _installed
    if _installed is not None and not refresh:
        return _installed
    _installed = {}
    if SYSTEM != "Windows":
        return _installed
    import json

    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=20, creationflags=0x08000000,
        ).stdout
        apps = json.loads(out or "[]")
        if isinstance(apps, dict):
            apps = [apps]
        _installed = {a["Name"].lower(): a["AppID"] for a in apps if a.get("Name") and a.get("AppID")}
    except Exception as e:
        print(f"(couldn't list installed apps: {e!r})")
    return _installed


def find_installed_app(name: str) -> tuple[str, str] | None:
    """Best Start-menu match for a spoken app name: (name, AppID)."""
    import difflib

    key = _normalize(name)
    apps = installed_apps()
    if not key or not apps:
        return None
    if key in apps:
        return key, apps[key]
    words = [n for n in apps if re.search(rf"\b{re.escape(key)}\b", n)]
    if words:
        best = min(words, key=len)  # "word" -> "word" over "wordpad"; shortest full-word match
        return best, apps[best]
    close = difflib.get_close_matches(key, list(apps), n=1, cutoff=0.75)
    return (close[0], apps[close[0]]) if close else None


def open_app(name: str, settle: float = 1.5) -> str:
    """Open an app or website by its spoken name. Never guesses wildly: says so if it can't find it."""
    import difflib

    key = _normalize(name)
    if not key or key.split()[0] in NOT_A_NAME or all(w in NOT_A_NAME for w in key.split()):
        return f"Sorry, I didn't catch what to open. You said: {name}."
    site = _website_key(key)
    if site or ("." in key and " " not in key):
        return open_website(site or key)

    opened = False
    if SYSTEM == "Windows":
        target = WINDOWS_APPS.get(key)
        if target == "wt" and not shutil.which("wt"):
            target = "powershell"
        if target:
            opened = _windows_start(target)
        if not opened:
            app = find_installed_app(key)
            if app:
                subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app[1]}"])
                opened = True
                name = app[0].title() if app[0] != key else name
    elif SYSTEM == "Darwin":
        app = MAC_APPS.get(key, name.title())
        opened = subprocess.run(["open", "-a", app], capture_output=True).returncode == 0
    else:
        cmd = LINUX_APPS.get(key, key.replace(" ", "-"))
        if shutil.which(cmd):
            subprocess.Popen([cmd], start_new_session=True)
            opened = True

    if not opened:
        # A near-miss of something we know ("hotstr" -> hotstar), or a one-word site name.
        known = list(WEBSITES) + list(WINDOWS_APPS)
        close = difflib.get_close_matches(key, known, n=1, cutoff=0.8)
        if close and close[0] != key:
            return open_app(close[0], settle)
        if " " not in key and key.isalpha():
            return open_website(key)
        return f"I couldn't find an app or website called {name}."
    time.sleep(settle)  # give the window a moment so typing afterwards lands in it
    return f"Opening {name}."


def _windows_start(target: str) -> bool:
    import os

    try:
        os.startfile(target)  # type: ignore[attr-defined]  # Windows only
        return True
    except OSError:
        return False


def _running(candidates: list[str]) -> list:
    import psutil

    found = []
    for proc in psutil.process_iter(["name"]):
        pname = re.sub(r"\.exe$", "", (proc.info.get("name") or "").lower())
        if pname in candidates:
            found.append(proc)
    return found


def _alive(procs: list) -> list:
    return [p for p in procs if p.is_running()]


def close_app(name: str, wait: float = 3.0) -> str:
    """Close an app, window or browser tab by name, and only report success once it's really gone."""
    from . import screen

    key = _normalize(name)
    if key in PROTECTED:
        return "I'd rather not close that one. It keeps the lights on."
    if not key:
        return "Close what?"
    candidates = PROCESS_NAMES.get(key, [key, key.replace(" ", ""), f"{key} app"])

    windows = screen.matching_windows(key) if SYSTEM == "Windows" else []
    try:
        procs = _running(candidates)
    except ImportError:
        return "I need the psutil package to close apps."

    if not windows and not procs:
        if SYSTEM == "Windows":  # maybe it's a browser tab ("close the Gmail tab")
            tab = screen.find_tab(key)
            if tab is not None:
                return screen.close_tab(key)
        return f"I can't see {name} open anywhere."

    # 1. Politely: close its windows (like clicking X), so apps can save and browsers restore cleanly.
    for w in windows:
        try:
            w.close()
        except Exception:
            pass
    if SYSTEM == "Darwin" and procs:
        subprocess.run(["osascript", "-e", f'quit app "{MAC_APPS.get(key, name.title())}"'], capture_output=True)
    deadline = time.time() + (wait if windows or SYSTEM == "Darwin" else 0)  # windowless: nothing to wait for
    while time.time() < deadline:
        time.sleep(0.5)
        left = screen.matching_windows(key) if SYSTEM == "Windows" else []
        if not left and not (_alive(procs) and not windows):
            return f"Closed {name}."

    # 2. Still open. Apps with unsaved work are probably asking to save; don't force those.
    if key in SAVES_WORK:
        return f"{name.capitalize()} is still open. It's probably asking whether to save your work."
    exes = {p.info["name"] for p in _alive(procs)}
    for exe in exes:
        if SYSTEM == "Windows":
            subprocess.run(["taskkill", "/F", "/T", "/IM", exe], capture_output=True, creationflags=0x08000000)
    if SYSTEM != "Windows":
        for p in _alive(procs):
            p.kill()
    time.sleep(1.0)
    left = screen.matching_windows(key) if SYSTEM == "Windows" else []
    if left or _alive(procs):
        return f"I couldn't close {name}. It may be running as administrator."
    return f"Closed {name}."


def type_text(text: str) -> str:
    """Type into whichever window has keyboard focus."""
    import pyautogui

    if text.isascii():
        pyautogui.write(text, interval=0.01)
    else:  # pyautogui can only type ASCII; paste anything else
        import pyperclip

        pyperclip.copy(text)
        pyautogui.hotkey("command" if SYSTEM == "Darwin" else "ctrl", "v")
    return "Done."


KEY_NAMES = {
    "control": "ctrl", "ctrl": "ctrl", "alt": "alt", "shift": "shift", "windows": "win", "win": "win",
    "command": "command", "cmd": "command", "enter": "enter", "return": "enter", "tab": "tab",
    "escape": "esc", "esc": "esc", "space": "space", "spacebar": "space", "backspace": "backspace",
    "delete": "delete", "up": "up", "down": "down", "left": "left", "right": "right", "home": "home",
    "end": "end", "pageup": "pageup", "pagedown": "pagedown", "capslock": "capslock",
}


def parse_keys(spoken: str) -> list[str] | None:
    """'control shift t' / 'ctrl+t' / 'alt plus f4' -> ['ctrl', 'shift', 't']; None if unrecognised."""
    spoken = spoken.lower().replace("page up", "pageup").replace("page down", "pagedown").replace("caps lock", "capslock")
    tokens = [t for t in re.split(r"\s*(?:\+|\bplus\b|\band\b|\s)\s*", spoken) if t and t not in {"the", "key", "keys"}]
    keys = []
    for t in tokens:
        if t in KEY_NAMES:
            keys.append(KEY_NAMES[t])
        elif re.fullmatch(r"[a-z0-9]|f(?:[1-9]|1[0-2])", t):
            keys.append(t)
        else:
            return None
    return keys or None


def press_keys(spoken: str) -> str:
    keys = parse_keys(spoken)
    if keys is None:
        return f"I don't know the key {spoken}."
    import pyautogui

    if len(keys) == 1:
        pyautogui.press(keys[0])
    else:
        pyautogui.hotkey(*keys)
    return "Done."


def spoken_email(text: str) -> str:
    """'sudar at gmail dot com' -> 'sudar@gmail.com'."""
    text = text.lower().strip(" .")
    text = re.sub(r"\s+at\s+", "@", text)
    text = re.sub(r"\s+dot\s+", ".", text)
    text = re.sub(r"\s+underscore\s+", "_", text)
    text = re.sub(r"\s+(dash|hyphen)\s+", "-", text)
    return text.replace(" ", "")


def compose_email(to: str, subject: str = "", body: str = "", client: str = "gmail") -> str:
    """Open a pre-filled draft. Never sends: the user reviews and clicks Send."""
    to = spoken_email(to) if "@" not in to else to.strip()
    if client == "gmail":
        url = "https://mail.google.com/mail/?" + urllib.parse.urlencode(
            {"view": "cm", "fs": "1", "to": to, "su": subject, "body": body})
    else:
        url = f"mailto:{to}?" + urllib.parse.urlencode({"subject": subject, "body": body}, quote_via=urllib.parse.quote)
    open_url(url)
    return f"I've drafted the email to {to}. Have a look and hit send when you're happy."


# --- browser profiles (Chrome, Brave, Edge) -------------------------------------------------------

BROWSERS = {
    # key: (Windows data dir under %LOCALAPPDATA%, macOS dir under ~/Library/Application Support,
    #       Linux dir under ~/.config, Windows exe, macOS app name)
    "chrome": (r"Google\Chrome\User Data", "Google/Chrome", "google-chrome", "chrome", "Google Chrome"),
    "brave": (r"BraveSoftware\Brave-Browser\User Data", "BraveSoftware/Brave-Browser",
              "BraveSoftware/Brave-Browser", "brave", "Brave Browser"),
    "edge": (r"Microsoft\Edge\User Data", "Microsoft Edge", "microsoft-edge", "msedge", "Microsoft Edge"),
}


def _browser(name: str) -> str | None:
    key = _normalize(name)
    for browser in BROWSERS:
        if browser in key:
            return browser
    return None


def _user_data_dir(browser: str):
    import os
    from pathlib import Path

    win, mac, linux = BROWSERS[browser][:3]
    if SYSTEM == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", ""), *win.split("\\"))
    if SYSTEM == "Darwin":
        return Path.home() / "Library" / "Application Support" / mac
    return Path.home() / ".config" / linux


def browser_profiles(name: str) -> list[dict]:
    """[{'dir': 'Profile 1', 'name': 'Work', 'email': 'me@x.com', 'full_name': 'Me'}] for a browser."""
    import json

    browser = _browser(name)
    if browser is None:
        raise ValueError(f"I only know Chrome, Brave and Edge profiles, not {name}.")
    path = _user_data_dir(browser) / "Local State"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    cache = state.get("profile", {}).get("info_cache", {})
    return [
        {"dir": d, "name": info.get("name", d), "email": info.get("user_name", ""),
         "full_name": info.get("gaia_name", "")}
        for d, info in cache.items()
    ]


def list_browser_profiles(name: str) -> str:
    profiles = browser_profiles(name)
    if not profiles:
        return f"I couldn't find any {name} profiles on this computer."
    described = []
    for p in profiles:
        extra = ", ".join(x for x in (p["full_name"], p["email"]) if x and x != p["name"])
        described.append(f"{p['name']} ({extra})" if extra else p["name"])
    return f"{name.capitalize()} has {len(profiles)} profile{'s' if len(profiles) != 1 else ''}: " + "; ".join(described)


def open_browser_profile(name: str, profile: str, url: str = "") -> str:
    browser = _browser(name)
    if browser is None:
        return f"I only know Chrome, Brave and Edge profiles, not {name}."
    wanted = _normalize(profile)
    profiles = browser_profiles(browser)
    match = next((p for p in profiles if wanted in (_normalize(p["name"]), _normalize(p["email"]),
                                                     _normalize(p["full_name"]), _normalize(p["dir"]))), None)
    match = match or next((p for p in profiles if wanted and any(
        wanted in _normalize(p[k]) for k in ("name", "email", "full_name"))), None)
    if match is None:
        return f"There's no {name} profile called {profile}. " + list_browser_profiles(browser)
    flag = f"--profile-directory={match['dir']}"
    extra = [url] if url else []
    exe, app = BROWSERS[browser][3], BROWSERS[browser][4]
    if SYSTEM == "Windows":
        subprocess.Popen(["cmd", "/c", "start", "", exe, flag, *extra], creationflags=0x08000000)  # no console
    elif SYSTEM == "Darwin":
        subprocess.Popen(["open", "-na", app, "--args", flag, *extra])
    else:
        subprocess.Popen([BROWSERS[browser][2], flag, *extra], start_new_session=True)
    time.sleep(1.5)
    return f"Opening {name} as {match['name']}."
