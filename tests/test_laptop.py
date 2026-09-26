import sys
import types

import pytest

from jarvis import ai, screen, system
from jarvis.brain import Brain
from jarvis.config import Config

WINGET_OUTPUT = (
    "   - \r   \\ \r   | \r"
    "Name              Id                       Version  Match        Source\n"
    "-----------------------------------------------------------------------\n"
    "Docker Desktop    Docker.DockerDesktop     4.43.1                winget\n"
    "Docker CLI        Docker.DockerCLI         28.3.0   Tag: docker  winget\n"
    "Docker Desktop    XP8CBJ40XLBWKX           Unknown               msstore\n"
)


def test_parse_winget_table():
    rows = system.parse_winget_table(WINGET_OUTPUT)
    assert rows[0] == {"name": "Docker Desktop", "id": "Docker.DockerDesktop", "version": "4.43.1", "source": "winget"}
    assert rows[1]["id"] == "Docker.DockerCLI" and rows[2]["source"] == "msstore"
    assert system.parse_winget_table("No package found matching input criteria.") == []


@pytest.fixture
def winget(monkeypatch):
    """Fake Windows with winget: searches return Docker; installs are recorded, not run."""
    installs = []
    monkeypatch.setattr(system, "SYSTEM", "Windows")
    monkeypatch.setattr(system.subprocess, "run",
                        lambda cmd, **kw: types.SimpleNamespace(stdout=WINGET_OUTPUT, stderr="", returncode=0))
    monkeypatch.setattr(system, "install_package",
                        lambda pkg, notify: installs.append(pkg["id"]) or f"Installing {pkg['name']} now.")
    monkeypatch.setattr("platform.system", lambda: "Windows")
    return installs


def test_find_package_prefers_exact_winget_match(winget):
    assert system.find_package("docker desktop")["id"] == "Docker.DockerDesktop"


def test_install_voice_command_asks_first(winget):
    b = Brain(Config())
    r = b.handle("install docker desktop")
    assert r.text == "I found Docker Desktop, version 4.43.1. Shall I install it?"
    assert winget == []
    assert b.handle("yes").text == "Installing Docker Desktop now."
    assert winget == ["Docker.DockerDesktop"]


def test_install_voice_command_can_be_declined(winget):
    b = Brain(Config())
    b.handle("please install docker desktop on my laptop")
    assert "Cancelled" in b.handle("no").text
    assert winget == []


def test_ai_install_needs_a_real_spoken_yes(winget):
    brain = ai.Assistant(Config(user_title="Sudarsan"))
    brain.user_text = "install docker desktop"
    text, _ = brain.run_tool("install_app", {"name": "Docker Desktop"})
    assert "Nothing installed yet" in text and winget == []

    # The model tries to skip asking, in the same turn: refused.
    text, _ = brain.run_tool("install_app", {"name": "Docker Desktop", "confirmed": True})
    assert text.startswith("Not confirmed") and winget == []

    brain.memory.add("install docker desktop", "Found it. Install Docker Desktop?", [])
    brain.user_text = "no wait"  # next turn, but the user didn't say yes
    assert brain.run_tool("install_app", {"name": "Docker Desktop", "confirmed": True})[0].startswith("Not confirmed")

    brain.run_tool("install_app", {"name": "Docker Desktop"})
    brain.memory.add("no wait", "Okay. Install Docker Desktop?", [])
    brain.user_text = "yes please go ahead"
    assert brain.run_tool("install_app", {"name": "Docker Desktop", "confirmed": True})[0] == "Installing Docker Desktop now."
    assert winget == ["Docker.DockerDesktop"]


def test_ai_commands_read_only_run_straight_away_others_need_yes(monkeypatch):
    ran = []
    monkeypatch.setattr(system, "run_powershell", lambda cmd, timeout=60: ran.append(cmd) or "output")
    brain = ai.Assistant(Config())
    brain.user_text = "how many processes are running"
    assert brain.run_tool("run_command", {"command": "Get-Process | Measure-Object"})[0] == "output"

    brain.user_text = "turn off the firewall"
    cmd = "Set-NetFirewallProfile -Enabled False"
    assert brain.run_tool("run_command", {"command": cmd, "confirmed": True})[0].startswith("Not run yet")
    brain.memory.add("turn off the firewall", "That disables the firewall. Sure?", [])
    brain.user_text = "yes"
    assert brain.run_tool("run_command", {"command": cmd + "; Remove-Item C:\\x", "confirmed": True})[0] \
        .startswith("Not run yet")  # a different command than the one proposed
    brain.run_tool("run_command", {"command": cmd})
    brain.memory.add("yes", "Just to check: disable the firewall?", [])
    brain.user_text = "yes do it"
    assert brain.run_tool("run_command", {"command": cmd, "confirmed": True})[0] == "output"
    assert ran == ["Get-Process | Measure-Object", cmd]


def test_install_notifies_when_done(monkeypatch):
    notices = []
    monkeypatch.setattr(system, "is_admin", lambda: True)

    class ImmediateThread:
        def __init__(self, target, **kw):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(system.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(system.subprocess, "run", lambda cmd, **kw: types.SimpleNamespace(
        stdout="Successfully installed", stderr="", returncode=0))
    text = system.install_package({"name": "VLC", "id": "VideoLAN.VLC"}, notices.append)
    assert text == "Installing VLC now. I'll tell you when it's done."
    assert notices == ["VLC finished installing."]


@pytest.fixture
def keys(monkeypatch):
    pressed = []
    monkeypatch.setitem(sys.modules, "pyautogui", types.SimpleNamespace(
        press=lambda key, presses=1: pressed.append((key, presses)), click=lambda *a, **k: None,
        write=lambda text, interval=0: pressed.append(("write", text))))
    return pressed


def test_volume_commands(keys):
    b = Brain(Config())
    assert b.handle("set the volume to 40").text == "Volume set to 40."
    assert keys[-2:] == [("volumedown", 50), ("volumeup", 20)]
    assert b.handle("turn the volume up").text == "Volume up a bit."
    assert b.handle("mute the sound").text.startswith("Muted")
    assert b.handle("type the volume is too high").text == "Done."  # dictation isn't a volume command


def test_brightness_and_settings(monkeypatch):
    calls = []
    monkeypatch.setattr(system, "SYSTEM", "Windows")
    monkeypatch.setattr(system, "_powershell", lambda script, timeout=30: calls.append(script) or "60")
    b = Brain(Config())
    assert b.handle("set brightness to 30").text == "Brightness set to 30."
    assert "Brightness=30" in calls[-1]
    assert b.handle("increase the brightness").text == "Brightness set to 80."
    opened = []
    monkeypatch.setattr(system.os, "startfile", opened.append, raising=False)
    assert b.handle("open bluetooth settings").text == "Opening bluetooth settings."
    assert opened == ["ms-settings:bluetooth"]


def test_laptop_info_commands(monkeypatch):
    monkeypatch.setattr(system, "system_info", lambda: "specs")
    monkeypatch.setattr(system, "usage", lambda: "usage")
    monkeypatch.setattr(system, "top_processes", lambda sort="memory": f"top by {sort}")
    monkeypatch.setattr(system, "network", lambda: "network")
    b = Brain(Config())
    assert b.handle("what are my laptop specs").text == "specs"
    assert b.handle("what laptop is this").text == "specs"
    assert b.handle("how much battery is left").text == "usage"
    assert b.handle("what's eating my memory").text == "top by memory"
    assert b.handle("why is my laptop so slow").text == "top by memory"
    assert b.handle("which apps are using the cpu").text == "top by cpu"
    assert b.handle("am I connected").text == "network"


def test_top_processes_adds_up_multi_process_apps(monkeypatch):
    class P:
        def __init__(self, name, cpu, mb):
            self.info, self._cpu, self._mb = {"name": name}, cpu, mb

        def cpu_percent(self, interval):
            return self._cpu

        def memory_info(self):
            return types.SimpleNamespace(rss=self._mb * 1024 ** 2)

    procs = [P("chrome.exe", 8, 300), P("chrome.exe", 4, 200), P("Code.exe", 2, 400), P("System Idle Process", 90, 0)]
    fake_psutil = types.SimpleNamespace(process_iter=lambda attrs: procs, cpu_count=lambda: 4)
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(system.time, "sleep", lambda s: None)
    assert system.top_processes("memory", 2) == \
        "Top apps by memory: chrome: 3% CPU, 500 MB across 2 processes; Code: 0% CPU, 400 MB."


def test_close_it_goes_to_the_ai_with_context():
    asked = []
    b = Brain(Config(), fallback=lambda text: asked.append(text) or "Closed Edge.")
    assert b.handle("close it").text == "Closed Edge."
    assert b.handle("yes please close it").text == "Closed Edge."
    assert asked == ["close it", "yes please close it"]


class Rect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom


def test_dismiss_popup_clicks_the_dialog_button_not_the_window_close(monkeypatch):
    clicks = []
    monkeypatch.setattr(screen, "SYSTEM", "Windows")
    monkeypatch.setattr(screen, "screen_elements", lambda: [
        screen.Element("Button", "Close", 1880, 15),        # the window's own X (top-right corner)
        screen.Element("Text", "Browse faster with Edge", 960, 400),
        screen.Element("Button", "Close", 1200, 330),       # the popup's X
        screen.Element("Button", "Continue", 960, 600),
    ])
    monkeypatch.setattr(screen, "_window_rect", lambda: Rect(0, 0, 1920, 1080))
    monkeypatch.setattr(screen, "click_point", lambda x, y, *a: clicks.append((x, y)))
    monkeypatch.setitem(sys.modules, "pyautogui", types.SimpleNamespace(press=lambda k: clicks.append(k)))
    assert Brain(Config()).handle("close the popup").text == "Dismissed it with 'Close'."
    assert clicks == [(1200, 330)]


def test_dismiss_popup_prefers_not_now_and_falls_back_to_escape(monkeypatch):
    clicks = []
    monkeypatch.setattr(screen, "SYSTEM", "Windows")
    monkeypatch.setattr(screen, "_window_rect", lambda: Rect(0, 0, 1920, 1080))
    monkeypatch.setattr(screen, "click_point", lambda x, y, *a: clicks.append((x, y)))
    monkeypatch.setitem(sys.modules, "pyautogui", types.SimpleNamespace(press=lambda k: clicks.append(k)))
    monkeypatch.setattr(screen, "screen_elements", lambda: [screen.Element("Button", "Close", 900, 300),
                                                           screen.Element("Button", "Not now", 800, 500)])
    assert screen.dismiss_popup() == "Dismissed it with 'Not now'."
    monkeypatch.setattr(screen, "screen_elements", lambda: [])
    assert "Escape" in screen.dismiss_popup(locate=lambda t: None)
    assert clicks[-1] == "esc"
