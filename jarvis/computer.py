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
}

# Never close these: they would take down Windows' desktop, the OS, or Jarvis itself.
PROTECTED = {"explorer", "file explorer", "files", "finder", "python", "pythonw", "jarvis", "yourself",
             "system", "windows", "svchost", "csrss", "winlogon", "dwm", "lsass", "services", "wininit", "smss"}


def _normalize(name: str) -> str:
    name = name.lower().strip(" .!?,")
    name = re.sub(r"^(the|my|a|an)\s+", "", name)
    return re.sub(r"\s+(app|application|program|browser|window)$", "", name).strip()


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


def open_app(name: str, settle: float = 1.5) -> str:
    """Open an app by its spoken name, falling back to a website of that name."""
    key = _normalize(name)
    if key in WEBSITES or ("." in key and " " not in key):
        return open_website(key)

    opened = False
    if SYSTEM == "Windows":
        target = WINDOWS_APPS.get(key)
        if target == "wt" and not shutil.which("wt"):
            target = "powershell"
        if target:
            opened = _windows_start(target)
        if not opened:
            opened = _windows_search_launch(key)
    elif SYSTEM == "Darwin":
        app = MAC_APPS.get(key, name.title())
        opened = subprocess.run(["open", "-a", app], capture_output=True).returncode == 0
    else:
        cmd = LINUX_APPS.get(key, key.replace(" ", "-"))
        if shutil.which(cmd):
            subprocess.Popen([cmd], start_new_session=True)
            opened = True

    if not opened:
        return open_website(key)
    time.sleep(settle)  # give the window a moment so typing afterwards lands in it
    return f"Opening {name}."


def _windows_start(target: str) -> bool:
    import os

    try:
        os.startfile(target)  # type: ignore[attr-defined]  # Windows only
        return True
    except OSError:
        return False


def _windows_search_launch(name: str) -> bool:
    """Open anything installed by typing its name into the Start menu, like a person would."""
    try:
        import pyautogui
    except ImportError:
        return False
    pyautogui.press("win")
    time.sleep(0.8)
    pyautogui.write(name, interval=0.03)
    time.sleep(1.0)
    pyautogui.press("enter")
    return True


def _running(candidates: list[str]) -> list:
    import psutil

    found = []
    for proc in psutil.process_iter(["name"]):
        pname = re.sub(r"\.exe$", "", (proc.info.get("name") or "").lower())
        if pname in candidates:
            found.append(proc)
    return found


def close_app(name: str) -> str:
    key = _normalize(name)
    if key in PROTECTED:
        return "I'd rather not close that one. It keeps the lights on."
    candidates = PROCESS_NAMES.get(key, [key, key.replace(" ", "")])
    try:
        procs = _running(candidates)
    except ImportError:
        return "I need the psutil package to close apps."
    if not procs:
        return f"{name.capitalize()} doesn't seem to be running."

    if SYSTEM == "Windows":
        # Without /F, taskkill asks windows to close politely, so apps can save and Chrome won't
        # complain about a crash next time.
        exes = {p.info["name"] for p in procs}
        for exe in exes:
            subprocess.run(["taskkill", "/IM", exe], capture_output=True)
    elif SYSTEM == "Darwin":
        app = MAC_APPS.get(key, name.title())
        subprocess.run(["osascript", "-e", f'quit app "{app}"'], capture_output=True)
    else:
        for p in procs:
            p.terminate()
    return f"Closing {name}."


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
