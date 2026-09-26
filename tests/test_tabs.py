"""Tab commands against a fake browser that behaves like the real thing: Ctrl+T adds a tab, Ctrl+W closes
the current one, Ctrl+Tab moves right, typing a URL + Enter loads it, window titles follow the active tab."""

import sys
import types

import pytest

from jarvis import computer, screen
from jarvis.brain import Brain
from jarvis.config import Config

SUFFIX = {"edge": " - Microsoft​ Edge", "chrome": " - Google Chrome", "brave": " - Brave"}
SITE_TITLES = {"www.youtube.com": "YouTube", "mail.google.com": "Gmail", "www.hotstar.com": "JioHotstar",
               "www.google.com": "Google Search"}


class Rect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top

    def xcenter(self):
        return (self.left + self.right) // 2

    def ycenter(self):
        return (self.top + self.bottom) // 2


class Node:
    def __init__(self, kind, name="", rect=(0, 0, 0, 0), children=()):
        self.ControlTypeName, self.Name = f"{kind}Control", name
        self.BoundingRectangle = Rect(*rect)
        self.children = list(children)

    def GetChildren(self):
        return list(self.children)


class FakeWindow:
    count = 0

    def __init__(self, desktop, browser, tabs):
        FakeWindow.count += 1
        self._hWnd = FakeWindow.count
        self.desktop, self.browser, self.tabs, self.active = desktop, browser, list(tabs), len(tabs) - 1
        self.visible, self.isMinimized = True, False

    @property
    def title(self):
        return self.tabs[self.active] + SUFFIX[self.browser]

    def activate(self):
        self.desktop.front = self

    def close(self):
        self.desktop.windows.remove(self)

    def control(self):
        items = [Node("TabItem", t, (100 + 200 * i, 5, 300 + 200 * i, 35)) for i, t in enumerate(self.tabs)]
        return Node("Window", children=[Node("Pane", children=[Node("Tab", children=items)]),
                                        Node("Document", self.tabs[self.active])])


class FakeDesktop:
    def __init__(self):
        self.windows, self.front, self.closed, self.typed, self.keys = [], None, [], "", []

    def open(self, browser, *tabs):
        win = FakeWindow(self, browser, tabs or ["New Tab"])
        self.windows.insert(0, win)
        self.front = win
        return win

    def tabs(self, browser="edge"):
        return [t for w in self.windows if w.browser == browser for t in w.tabs]

    # --- keyboard and mouse ---
    def hotkey(self, *keys):
        self.keys.append(keys)
        w = self.front
        if keys == ("ctrl", "t"):
            w.tabs.append("New Tab")
            w.active = len(w.tabs) - 1
        elif keys == ("ctrl", "w"):
            self.closed.append(w.tabs.pop(w.active))
            if not w.tabs:
                self.windows.remove(w)
            w.active = min(w.active, len(w.tabs) - 1)
        elif keys == ("ctrl", "tab"):
            w.active = (w.active + 1) % len(w.tabs)
        elif keys == ("ctrl", "shift", "tab"):
            w.active = (w.active - 1) % len(w.tabs)
        elif keys == ("ctrl", "shift", "t") and self.closed:
            w.tabs.append(self.closed.pop())
            w.active = len(w.tabs) - 1
        elif keys == ("ctrl", "n"):
            self.open(w.browser)
        elif keys == ("ctrl", "l"):
            self.typed = ""

    def write(self, text, interval=0):
        self.typed += text

    def press(self, key, presses=1):
        if key == "enter" and self.typed:
            host = self.typed.split("//")[-1].split("/")[0]
            self.front.tabs[self.front.active] = SITE_TITLES.get(host, host)
            self.typed = ""

    def click(self, x, y, clicks=1, interval=0, button="left"):
        for i in range(len(self.front.tabs)):
            if 100 + 200 * i <= x < 300 + 200 * i:
                self.front.active = i


@pytest.fixture
def desk(monkeypatch):
    d = FakeDesktop()
    uia = types.ModuleType("uiautomation")
    uia.ControlFromHandle = lambda h: next(w.control() for w in d.windows if w._hWnd == h)
    pygetwindow = types.ModuleType("pygetwindow")
    pygetwindow.getActiveWindow = lambda: d.front
    monkeypatch.setitem(sys.modules, "uiautomation", uia)
    monkeypatch.setitem(sys.modules, "pygetwindow", pygetwindow)
    monkeypatch.setitem(sys.modules, "pyautogui", types.SimpleNamespace(
        hotkey=d.hotkey, write=d.write, press=d.press, click=d.click))
    monkeypatch.setattr(screen, "SYSTEM", "Windows")
    monkeypatch.setattr(computer, "SYSTEM", "Windows")
    monkeypatch.setattr(screen, "_windows", lambda: list(d.windows))
    monkeypatch.setattr(screen.time, "sleep", lambda s: None)
    monkeypatch.setattr(computer.time, "sleep", lambda s: None)
    monkeypatch.setattr(computer, "_running", lambda names: [])

    def open_app(name, settle=1.5):
        d.open({"microsoft edge": "edge", "chrome": "chrome", "brave": "brave"}[name])
        return f"Opening {name}."

    monkeypatch.setattr(computer, "open_app", open_app)
    return d


def test_open_a_new_tab_in_edge_the_way_it_was_said(desk):
    desk.open("edge", "Gmail")
    b = Brain(Config())
    assert b.handle("open the new tab in Microsoft edge").text == "Opened a new tab in Edge."
    assert b.handle("open a new tab").text == "Opened a new tab in Edge."
    assert desk.tabs("edge") == ["Gmail", "New Tab", "New Tab"]


def test_open_sites_in_new_tabs_and_specific_browsers(desk):
    desk.open("edge", "Gmail")
    b = Brain(Config())
    assert b.handle("open youtube in a new tab").text == "Opened YouTube in a new Edge tab."
    assert desk.tabs("edge") == ["Gmail", "YouTube"]
    assert b.handle("open a new tab and search for cricket scores").text == \
        "Opened a search for cricket scores in a new Edge tab."
    # Chrome isn't open: it gets opened, and its first tab is used rather than adding a second one.
    assert b.handle("open gmail in chrome").text == "Opened Gmail in a new Chrome tab."
    assert desk.tabs("chrome") == ["Gmail"]


def test_current_tab_commands(desk):
    desk.open("edge", "Gmail", "YouTube", "JioHotstar")
    b = Brain(Config())
    assert b.handle("close this tab").text == "Closed the JioHotstar tab."
    assert b.handle("previous tab").text == "Now on Gmail."
    assert b.handle("go to the next tab").text == "Now on YouTube."
    assert b.handle("reopen the closed tab").text == "Brought back the last closed tab."
    assert desk.tabs("edge") == ["Gmail", "YouTube", "JioHotstar"]


def test_close_tabs_by_name(desk):
    desk.open("edge", "Gmail", "YouTube", "API keys | Claude Platform", "Ollama")
    b = Brain(Config())
    assert b.handle("close youtube").text == "Closed the YouTube tab."        # no app called YouTube: it's a tab
    assert b.handle("close the ollama tab").text == "Closed the Ollama tab."
    assert b.handle("close the API keys tab").text == "Closed the API keys | Claude Platform tab."
    assert desk.tabs("edge") == ["Gmail"]


def test_close_all_tabs_except_one(desk):
    desk.open("edge", "Gmail", "YouTube", "JioHotstar", "New Tab")
    assert Brain(Config()).handle("close all tabs except gmail").text == "Closed 3 tabs and kept Gmail."
    assert desk.tabs("edge") == ["Gmail"]


def test_new_windows(desk):
    desk.open("edge", "Gmail")
    b = Brain(Config())
    assert b.handle("open a new window").text == "Opened a new Edge window."
    assert b.handle("open an incognito window").text == "Opened a private Edge window."
    assert ("ctrl", "shift", "n") in desk.keys


def test_failed_quick_command_goes_to_the_ai(desk, monkeypatch):
    monkeypatch.setattr(computer, "open_app", lambda name, settle=1.5: f"I couldn't find an app or website called {name}.")
    asked = []
    b = Brain(Config(), fallback=lambda text: asked.append(text) or "Done it another way.")
    assert b.handle("open the blue thing").text == "Done it another way."
    assert b.handle("close the purple window").text == "Done it another way."
    assert asked == ["open the blue thing", "close the purple window"]


def test_short_new_tab_phrases(desk):
    desk.open("edge", "Gmail")
    desk.open("chrome", "YouTube")
    b = Brain(Config())
    assert b.handle("new tab in edge").text == "Opened a new tab in Edge."
    assert b.handle("new tab").text == "Opened a new tab in Edge."  # the browser now in front
