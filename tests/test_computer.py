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


def test_windows_open_known_and_installed_apps(monkeypatch, opened):
    started, launched = [], []
    monkeypatch.setattr(computer, "SYSTEM", "Windows")
    monkeypatch.setattr(computer, "_windows_start", lambda target: started.append(target) or True)
    monkeypatch.setattr(computer.time, "sleep", lambda s: None)
    monkeypatch.setattr(computer.subprocess, "Popen", lambda cmd, **kw: launched.append(cmd))
    monkeypatch.setattr(computer, "_installed", {"adobe photoshop 2024": "Adobe.Photoshop", "ollama": "Ollama.App",
                                                 "wordpad": "WordPad", "microsoft word": "Word.App"})

    assert computer.open_app("Google Chrome") == "Opening Google Chrome."
    assert started == ["chrome"]
    monkeypatch.setattr(computer.shutil, "which", lambda cmd: None)
    computer.open_app("the terminal")
    assert started[-1] == "powershell"  # no Windows Terminal installed

    monkeypatch.setattr(computer, "_windows_start", lambda target: False)
    assert computer.open_app("photoshop") == "Opening Adobe Photoshop 2024."
    assert launched[-1] == ["explorer.exe", "shell:AppsFolder\\Adobe.Photoshop"]
    computer.open_app("ollama")
    assert launched[-1][-1].endswith("Ollama.App")


def test_open_never_acts_on_garbled_speech(monkeypatch, opened):
    monkeypatch.setattr(computer, "SYSTEM", "Windows")
    monkeypatch.setattr(computer, "_windows_start", lambda target: False)
    monkeypatch.setattr(computer, "_installed", {})
    monkeypatch.setattr(computer.time, "sleep", lambda s: None)
    assert "didn't catch" in computer.open_app("close the")
    assert "didn't catch" in computer.open_app("close the system")
    assert "couldn't find" in computer.open_app("purple monkey dishwasher")
    assert opened == []
    computer.open_app("chat gpt")  # spaced-out site names still work
    computer.open_app("hotstr")    # near-miss of a known site
    assert opened == ["https://chatgpt.com", "https://www.hotstar.com"]


def test_close_app_protects_system_and_jarvis():
    assert "rather not" in computer.close_app("explorer")
    assert "rather not" in computer.close_app("python")


class FakeWindow:
    def __init__(self, title, desktop, stubborn=False):
        self.title, self.desktop, self.stubborn = title, desktop, stubborn

    def close(self):
        if not self.stubborn:
            self.desktop.remove(self)


@pytest.fixture
def desktop(monkeypatch):
    """A fake Windows desktop: windows can be closed (or refuse), processes can be force-killed."""
    from jarvis import screen

    wins, killed, procs = [], [], {}
    monkeypatch.setattr(computer, "SYSTEM", "Windows")
    monkeypatch.setattr(screen, "SYSTEM", "Windows")
    monkeypatch.setattr(screen, "_windows", lambda: list(wins))
    clock = [1000.0]
    monkeypatch.setattr(computer, "time", types.SimpleNamespace(time=lambda: clock[0],
                                                                sleep=lambda s: clock.__setitem__(0, clock[0] + s)))

    class Proc:
        def __init__(self, exe):
            self.info, self.dead = {"name": exe}, False

        def is_running(self):
            return not self.dead

    def running(candidates):
        return [p for n, p in procs.items() if n in candidates and not p.dead]

    def taskkill(cmd, **kw):
        killed.append(cmd)
        exe = cmd[-1][:-4].lower()
        if exe in procs:
            procs[exe].dead = True
            wins[:] = []

    monkeypatch.setattr(computer, "_running", running)
    monkeypatch.setattr(computer.subprocess, "run", taskkill)
    monkeypatch.setattr(screen, "find_tab", lambda title, browser=None: None)
    return types.SimpleNamespace(wins=wins, procs=procs, killed=killed, Proc=Proc)


def test_close_app_closes_windows_politely_and_confirms(desktop):
    desktop.wins += [FakeWindow("Inbox - Gmail - Google Chrome", desktop.wins),
                     FakeWindow("Settings", desktop.wins)]
    desktop.procs["chrome"] = desktop.Proc("chrome.exe")
    assert computer.close_app("chrome") == "Closed chrome."
    assert computer.close_app("system settings") == "Closed system settings."
    assert desktop.wins == [] and desktop.killed == []  # no force needed


def test_close_ollama_does_not_close_a_browser_showing_an_ollama_tab(desktop):
    chrome = FakeWindow("Ollama - Google Chrome", desktop.wins)
    desktop.wins.append(chrome)
    assert computer.close_app("ollama") == "I can't see ollama open anywhere."
    assert desktop.wins == [chrome]


def test_close_app_forces_a_stubborn_browser_and_says_so_honestly(desktop):
    desktop.wins.append(FakeWindow("New Tab - Microsoft​ Edge", desktop.wins, stubborn=True))
    desktop.procs["msedge"] = desktop.Proc("msedge.exe")
    assert computer.close_app("microsoft edge") == "Closed microsoft edge."
    assert desktop.killed == [["taskkill", "/F", "/T", "/IM", "msedge.exe"]]


def test_close_app_never_forces_apps_with_unsaved_work(desktop):
    desktop.wins.append(FakeWindow("Report.docx - Word", desktop.wins, stubborn=True))
    desktop.procs["winword"] = desktop.Proc("winword.exe")
    assert "asking whether to save" in computer.close_app("word")
    assert desktop.killed == []


def test_close_app_background_process(desktop):
    desktop.procs["ollama app"] = desktop.Proc("ollama app.exe")
    assert computer.close_app("ollama") == "Closed ollama."
    assert desktop.killed == [["taskkill", "/F", "/T", "/IM", "ollama app.exe"]]


def test_close_app_falls_back_to_browser_tab(desktop, monkeypatch):
    from jarvis import screen

    monkeypatch.setattr(screen, "find_tab", lambda title, browser=None: "tab")
    monkeypatch.setattr(screen, "close_tab", lambda title, browser=None: f"Closed the {title} tab.")
    assert computer.close_app("gmail") == "Closed the gmail tab."


def test_close_app_nothing_open(desktop):
    assert computer.close_app("netflix") == "I can't see netflix open anywhere."


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


def test_normalize_drops_filler_words():
    assert computer._normalize("all the Microsoft Edge") == "microsoft edge"
    assert computer._normalize("the Microsoft edge Windows") == "microsoft edge"
    assert computer._normalize("my Brave browser") == "brave"
    assert computer._normalize("windows") == "windows"


def test_no_website_guessing_when_an_ai_can_decide(monkeypatch, opened):
    monkeypatch.setattr(computer, "SYSTEM", "Windows")
    monkeypatch.setattr(computer, "_windows_start", lambda target: False)
    monkeypatch.setattr(computer, "_installed", {})
    assert "couldn't find" in computer.open_app("string", guess_sites=False)
    assert opened == []
    computer.open_app("string")  # no AI: a one-word name may still be a website
    assert opened == ["https://www.string.com"]


def test_steam_mishearings():
    from jarvis.brain import fix_transcript

    assert fix_transcript("open string") == "open Steam"
    assert fix_transcript("click the plus button in the stream") == "click the plus button in Steam"
    assert fix_transcript("I like to stream on Twitch") == "I like to stream on Twitch"
