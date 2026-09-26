"""Know and control the laptop: specs, live usage, running processes, network, volume, brightness,
Settings pages, installing apps (winget) and running PowerShell commands.

Everything that changes the system in a way that's hard to undo (installing apps, running commands
that aren't read-only) needs the user's spoken "yes" first; see the gating in ai.py and skills/apps.py.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import threading
import time

SYSTEM = platform.system()
NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # don't flash a console window on Windows


def _powershell(script: str, timeout: float = 30) -> str:
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=timeout, creationflags=NO_WINDOW)
    return (out.stdout or "").strip()


def is_admin() -> bool:
    if SYSTEM != "Windows":
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# --- what this laptop is ------------------------------------------------------------------------

_specs: dict | None = None


def hardware() -> dict:
    """Static facts, looked up once: maker, model, CPU, GPU, OS."""
    global _specs
    if _specs is not None:
        return _specs
    _specs = {"os": platform.platform(), "cpu": platform.processor(), "gpu": [], "maker": "", "model": ""}
    if SYSTEM == "Windows":
        try:
            raw = _powershell(
                "$cs = Get-CimInstance Win32_ComputerSystem; "
                "@{maker=$cs.Manufacturer; model=$cs.Model; "
                "cpu=(Get-CimInstance Win32_Processor | Select-Object -First 1).Name; "
                "gpu=@((Get-CimInstance Win32_VideoController).Name); "
                "os=(Get-CimInstance Win32_OperatingSystem).Caption} | ConvertTo-Json -Compress")
            _specs.update({k: v for k, v in json.loads(raw or "{}").items() if v})
        except Exception as e:
            print(f"(couldn't read hardware details: {e!r})")
    return _specs


def _sentence(text: str) -> str:
    """Capitalise the first letter only ("CPU at 5 percent", not "Cpu at 5 percent")."""
    return text[:1].upper() + text[1:]


def _gb(n: float) -> str:
    return f"{n / 1024 ** 3:.0f} GB" if n >= 10 * 1024 ** 3 else f"{n / 1024 ** 3:.1f} GB"


def system_info() -> str:
    """A spoken summary of the laptop and how it's doing right now."""
    import psutil

    hw = hardware()
    mem = psutil.virtual_memory()
    parts = []
    machine = " ".join(x for x in (hw.get("maker"), hw.get("model")) if x)
    parts.append(f"This is a {machine}, running {hw.get('os')}." if machine else f"This computer runs {hw.get('os')}.")
    if hw.get("cpu"):
        parts.append(f"Processor: {hw['cpu'].strip()}, {psutil.cpu_count(logical=False)} cores.")
    gpus = hw.get("gpu") or []
    if isinstance(gpus, str):
        gpus = [gpus]
    if gpus:
        parts.append("Graphics: " + " and ".join(gpus) + ".")
    parts.append(f"Memory: {_gb(mem.total)}, {mem.percent:.0f} percent in use.")
    parts.append(usage(include_memory=False))
    return " ".join(parts)


def usage(include_memory: bool = True) -> str:
    import psutil

    parts = [f"CPU at {psutil.cpu_percent(interval=0.5):.0f} percent"]
    if include_memory:
        parts.append(f"memory at {psutil.virtual_memory().percent:.0f} percent")
    try:
        disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\" if SYSTEM == "Windows" else "/")
        parts.append(f"{_gb(disk.free)} free on the main drive")
    except Exception:
        pass
    battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    if battery is not None:
        state = "charging" if battery.power_plugged else "on battery"
        left = ""
        if not battery.power_plugged and battery.secsleft not in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN):
            left = f", about {battery.secsleft // 3600} hours {battery.secsleft % 3600 // 60} minutes left"
        parts.append(f"battery {battery.percent:.0f} percent and {state}{left}")
    uptime = time.time() - psutil.boot_time()
    parts.append(f"up for {int(uptime // 3600)} hours {int(uptime % 3600 // 60)} minutes")
    return _sentence(", ".join(parts)) + "."


def top_processes(sort: str = "memory", count: int = 8) -> str:
    """Like Task Manager: the busiest apps, with all of an app's processes (e.g. Chrome's) added up."""
    import psutil

    procs = list(psutil.process_iter(["name"]))
    for p in procs:
        try:
            p.cpu_percent(None)
        except Exception:
            pass
    time.sleep(0.7)
    totals: dict[str, list[float]] = {}
    cores = psutil.cpu_count() or 1
    for p in procs:
        try:
            name = re.sub(r"\.exe$", "", p.info["name"] or "", flags=re.I)
            if not name or name.lower() in {"system idle process", "idle"}:
                continue
            cpu = p.cpu_percent(None) / cores
            mem = p.memory_info().rss
        except Exception:
            continue
        t = totals.setdefault(name, [0.0, 0.0, 0])
        t[0] += cpu
        t[1] += mem
        t[2] += 1
    key = 0 if sort == "cpu" else 1
    ranked = sorted(totals.items(), key=lambda kv: kv[1][key], reverse=True)[:count]
    rows = [f"{name}: {cpu:.0f}% CPU, {mem / 1024 ** 2:.0f} MB" + (f" across {n} processes" if n > 1 else "")
            for name, (cpu, mem, n) in ranked]
    return f"Top apps by {'CPU' if key == 0 else 'memory'}: " + "; ".join(rows) + "."


def network() -> str:
    import socket

    parts = []
    if SYSTEM == "Windows":
        try:
            out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True,
                                 errors="replace", timeout=10, creationflags=NO_WINDOW).stdout
            ssid = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.M)
            signal = re.search(r"^\s*Signal\s*:\s*(\d+)%", out, re.M)
            if ssid:
                parts.append(f"Connected to Wi-Fi {ssid.group(1).strip()}"
                             + (f" at {signal.group(1)} percent signal" if signal else ""))
        except Exception:
            pass
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=3) as s:
            parts.append(f"local address {s.getsockname()[0]}")
            parts.append("internet is working")
    except OSError:
        parts.append("no internet connection")
    return _sentence(", ".join(parts)) + "."


# --- volume, brightness, Settings ---------------------------------------------------------------

def set_volume(level: int | None = None, change: str | None = None) -> str:
    """Set volume to 0-100, or change it: 'up', 'down', 'mute'. Uses the media keys (2% per press)."""
    import pyautogui

    if change == "mute":
        pyautogui.press("volumemute")
        return "Muted. Say unmute to bring it back."
    if change == "unmute":
        pyautogui.press("volumemute")
        return "Sound's back on."
    if change in ("up", "down"):
        pyautogui.press("volumeup" if change == "up" else "volumedown", presses=5)
        return f"Volume {change} a bit."
    if level is None:
        return "What volume would you like, from 0 to 100?"
    level = max(0, min(100, int(level)))
    pyautogui.press("volumedown", presses=50)  # to zero, then up to the target
    pyautogui.press("volumeup", presses=round(level / 2))
    return f"Volume set to {level}."


def set_brightness(level: int | None = None, change: str | None = None) -> str:
    if SYSTEM != "Windows":
        return "I can only change brightness on Windows for now."
    try:
        current = int(_powershell("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness"
                                  " | Select-Object -First 1).CurrentBrightness") or 50)
    except (ValueError, subprocess.SubprocessError):
        return "This screen doesn't let me change its brightness."
    if change in ("up", "down"):
        level = current + (20 if change == "up" else -20)
    if level is None:
        return f"Brightness is at {current} percent."
    level = max(0, min(100, int(level)))
    _powershell("Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | "
                f"Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={level}}}")
    return f"Brightness set to {level}."


SETTINGS_PAGES = {
    "display": "display", "screen": "display", "sound": "sound", "audio": "sound", "bluetooth": "bluetooth",
    "wifi": "network-wifi", "wi-fi": "network-wifi", "network": "network-status", "internet": "network-status",
    "vpn": "network-vpn", "hotspot": "network-mobilehotspot", "battery": "batterysaver", "power": "powersleep",
    "sleep": "powersleep", "apps": "appsfeatures", "installed apps": "appsfeatures", "startup": "startupapps",
    "startup apps": "startupapps", "default apps": "defaultapps", "update": "windowsupdate",
    "windows update": "windowsupdate", "updates": "windowsupdate", "storage": "storagesense",
    "notifications": "notifications", "privacy": "privacy", "microphone": "privacy-microphone",
    "camera": "privacy-webcam", "mouse": "mousetouchpad", "touchpad": "devices-touchpad", "keyboard": "keyboard",
    "printers": "printers", "wallpaper": "personalization-background", "background": "personalization-background",
    "personalization": "personalization", "themes": "themes", "dark mode": "colors", "colors": "colors",
    "date": "dateandtime", "time": "dateandtime", "language": "regionlanguage", "account": "yourinfo",
    "accounts": "yourinfo", "about": "about", "system": "about", "night light": "nightlight",
    "focus": "quiethours", "do not disturb": "quiethours", "graphics": "display-advancedgraphics",
}


def open_settings(page: str = "") -> str:
    key = re.sub(r"\s*settings?$", "", (page or "").lower().strip()).strip()
    uri = SETTINGS_PAGES.get(key, "")
    if SYSTEM != "Windows":
        return "Settings pages only open on Windows."
    os.startfile(f"ms-settings:{uri}")  # type: ignore[attr-defined]
    return f"Opening {key or 'Settings'} settings." if uri else "Opening Settings."


# --- installing apps (winget) --------------------------------------------------------------------

def parse_winget_table(output: str) -> list[dict]:
    """Rows of `winget search` output: [{'name', 'id', 'version', 'source'}]."""
    lines = [line.split("\r")[-1].rstrip() for line in output.splitlines()]
    for i, line in enumerate(lines[:-1]):
        if re.match(r"^Name\s+Id\s+Version", line) and set(lines[i + 1].strip()) <= {"-", "─"} and lines[i + 1].strip():
            header = line
            break
    else:
        return []
    cols = [m.start() for m in re.finditer(r"\S+", header)]
    names = header.split()
    rows = []
    for line in lines[i + 2:]:
        if not line.strip():
            continue
        cells = {}
        for n, start in enumerate(cols):
            end = cols[n + 1] if n + 1 < len(cols) else None
            cells[names[n].lower()] = line[start:end].strip()
        if cells.get("id"):
            rows.append({"name": cells.get("name", ""), "id": cells["id"], "version": cells.get("version", ""),
                         "source": cells.get("source", "")})
    return rows


def find_package(query: str) -> dict | None:
    if SYSTEM != "Windows":
        return None
    out = subprocess.run(["winget", "search", query, "--accept-source-agreements", "--disable-interactivity"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
                         creationflags=NO_WINDOW).stdout
    rows = parse_winget_table(out)
    if not rows:
        return None
    wanted = query.lower().strip()
    exact = [r for r in rows if r["name"].lower() == wanted]
    from_winget = [r for r in rows if r["source"].lower() == "winget"]
    return (exact or from_winget or rows)[0]


def install_package(package: dict, notify) -> str:
    """Start installing in the background; `notify(text)` is called when it finishes."""
    def run():
        cmd = ["winget", "install", "--id", package["id"], "-e", "--silent",
               "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    timeout=3600, creationflags=NO_WINDOW)
            ok = result.returncode == 0 or "successfully installed" in (result.stdout or "").lower()
            notify(f"{package['name']} finished installing." if ok else
                   f"Installing {package['name']} didn't work. Windows said: "
                   f"{(result.stdout or result.stderr or '').strip().splitlines()[-1:] or ['nothing']}")
        except Exception as e:
            notify(f"Installing {package['name']} failed: {e}")

    threading.Thread(target=run, name=f"install {package['id']}", daemon=True).start()
    if is_admin():
        return f"Installing {package['name']} now. I'll tell you when it's done."
    return (f"Installing {package['name']} now. Windows will probably ask for permission: click Yes on "
            "that prompt. I'll tell you when it's done.")


# --- PowerShell ----------------------------------------------------------------------------------

SAFE_VERBS = {"get", "test", "measure", "select", "sort", "where", "format", "out", "convertto", "group",
              "resolve", "find", "compare", "foreach"}
SAFE_WORDS = {"ipconfig", "hostname", "whoami", "systeminfo", "ver", "where.exe", "ping", "tasklist",
              "driverquery", "nslookup", "tracert"}


def is_read_only(command: str) -> bool:
    """True for commands that only look at things (Get-Process, ipconfig...). Anything else needs a yes."""
    if re.search(r"[>{}&`]|\$\(|@\(", command):
        return False  # redirection, script blocks, call operator, sub-expressions: could run anything
    if re.search(r"\b(iex|invoke-\w+|start-process|remove|stop|set|new|clear|restart|format-volume|del|rm|"
                 r"rmdir|erase|reg|shutdown|kill|taskkill|install|uninstall|enable|disable|add|move|copy|"
                 r"rename|write|out-file)\b", command, re.I):
        return False
    # The command word at the start of each pipeline stage, statement or parenthesis.
    words = re.findall(r"(?:^|[|;(\n])\s*([A-Za-z][\w.-]*)", command)
    for word in words:
        verb = word.split("-")[0].lower()
        if "-" in word and verb in SAFE_VERBS:
            continue
        if word.lower() in SAFE_WORDS:
            continue
        return False
    return bool(words)


def run_powershell(command: str, timeout: float = 60) -> str:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=timeout, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        return f"The command was still running after {timeout:.0f} seconds, so I stopped waiting."
    text = ((out.stdout or "") + ("\n" + out.stderr if out.stderr else "")).strip()
    if len(text) > 3000:
        text = text[:3000] + "\n... (output cut)"
    return text or ("Done, no output." if out.returncode == 0 else f"It failed with exit code {out.returncode}.")
