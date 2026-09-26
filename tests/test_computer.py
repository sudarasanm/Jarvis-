import sys
import types

import pytest

from jarvis import computer
from jarvis.brain import Brain
from jarvis.config import Config


@pytest.fixture
def opened(monkeypatch):
    urls = []
    monkeypatch.setattr(computer, "open_url", urls.append)
    return urls


@pytest.fixture
def fake_gui(monkeypatch):
    calls = []
    gui = types.SimpleNamespace(
        write=lambda text, interval=0: calls.append(("write", text)),
        press=lambda key: calls.append(("press", key)),
        hotkey=lambda *keys: calls.append(("hotkey", keys)),
    )
    monkeypatch.setitem(sys.modules, "pyautogui", gui)
    return calls


def test_parse_keys():
    assert computer.parse_keys("enter") == ["enter"]
    assert computer.parse_keys("control shift t") == ["ctrl", "shift", "t"]
    assert computer.parse_keys("ctrl+l") == ["ctrl", "l"]
    assert computer.parse_keys("alt plus F4") == ["alt", "f4"]
    assert computer.parse_keys("page down") == ["pagedown"]
    assert computer.parse_keys("the banana key") is None


def test_spoken_email():
    assert computer.spoken_email("sudar at gmail dot com") == "sudar@gmail.com"
    assert computer.spoken_email("john underscore doe at example dot co dot in") == "john_doe@example.co.in"


def test_compose_email_opens_gmail_draft(opened):
    reply = computer.compose_email("sudar at gmail dot com", "Hello", "See you at 5")
    assert "sudar@gmail.com" in reply
    assert opened[0].startswith("https://mail.google.com/mail/?view=cm")
    assert "to=sudar%40gmail.com" in opened[0] and "su=Hello" in opened[0] and "See+you+at+5" in opened[0]


def test_websites_open_in_browser(opened):
    computer.open_app("hotstar")
    computer.open_app("github.com")
    assert opened == ["https://www.hotstar.com", "https://github.com"]


def test_windows_open_known_app_and_unknown_via_start_menu(monkeypatch, fake_gui, opened):
    started = []
    monkeypatch.setattr(computer, "SYSTEM", "Windows")
    monkeypatch.setattr(computer, "_windows_start", lambda target: started.append(target) or True)
    monkeypatch.setattr(computer.time, "sleep", lambda s: None)

    assert computer.open_app("Google Chrome") == "Opening Google Chrome."
    assert started == ["chrome"]

    monkeypatch.setattr(computer.shutil, "which", lambda cmd: None)
    computer.open_app("the terminal")
    assert started[-1] == "powershell"  # no Windows Terminal installed

    computer.open_app("Photoshop")  # not in the list: typed into the Start menu
    assert fake_gui == [("press", "win"), ("write", "photoshop"), ("press", "enter")]
    assert opened == []


def test_close_app_protects_system_and_jarvis():
    assert "rather not" in computer.close_app("explorer")
    assert "rather not" in computer.close_app("python")


def test_close_app_not_running(monkeypatch):
    monkeypatch.setattr(computer, "_running", lambda names: [])
    assert "doesn't seem to be running" in computer.close_app("chrome")


def test_close_app_windows_uses_polite_taskkill(monkeypatch):
    ran = []
    proc = types.SimpleNamespace(info={"name": "chrome.exe"})
    monkeypatch.setattr(computer, "SYSTEM", "Windows")
    monkeypatch.setattr(computer, "_running", lambda names: [proc, proc])
    monkeypatch.setattr(computer.subprocess, "run", lambda cmd, **kw: ran.append(cmd))
    assert computer.close_app("chrome") == "Closing chrome."
    assert ran == [["taskkill", "/IM", "chrome.exe"]]  # no /F: lets Chrome close cleanly


def test_voice_commands_route_to_computer(monkeypatch, fake_gui, opened):
    b = Brain(Config())
    assert b.handle("open hotstar").text == "Opening hotstar."
    b.handle("type hello world")
    b.handle("press control t")
    assert fake_gui == [("write", "hello world"), ("hotkey", ("ctrl", "t"))]
    b.handle("write an email to sudar at gmail dot com about the project demo")
    assert "to=sudar%40gmail.com" in opened[-1] and "su=The+project+demo" in opened[-1]


def test_multi_step_and_email_go_to_claude_when_available(fake_gui, opened):
    asked = []
    b = Brain(Config(), fallback=lambda text: asked.append(text) or "On it.")
    b.handle("open chrome and search for cricket scores")
    b.handle("write an email to my boss saying I'll be late")
    assert asked == ["open chrome and search for cricket scores", "write an email to my boss saying I'll be late"]
    assert opened == [] and fake_gui == []
