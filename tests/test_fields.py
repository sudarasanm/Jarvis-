import sys
import types

import pytest

from jarvis import computer, screen
from jarvis.brain import Brain
from jarvis.config import Config


class FakeBox:
    """A text box with a UI Automation value, like WhatsApp's search box."""

    def __init__(self, text, ignores_keyboard=False):
        self.text, self.ignores_keyboard = text, ignores_keyboard
        box = self

        class Pattern:
            @property
            def Value(self):
                return box.text

            def SetValue(self, value):
                box.text = value

        self.pattern = Pattern()

    def GetValuePattern(self):
        return self.pattern


@pytest.fixture
def whatsapp_search(monkeypatch):
    box = FakeBox("old search")
    state = {"focused": None, "selected": False, "log": []}
    elements = [screen.Element("Button", "Search", 100, 40),
                screen.Element("Edit", "Search or start a new chat", 200, 100, box)]

    def click(x, y, *a):
        state["log"].append(("click", x, y))
        state["focused"] = box if (x, y) == (200, 100) else None

    def hotkey(*keys):
        state["log"].append(keys)
        state["selected"] = keys == ("ctrl", "a") and state["focused"] is box

    def press(key):
        state["log"].append(key)
        if key == "backspace" and state["selected"] and not box.ignores_keyboard:
            box.text = ""

    monkeypatch.setattr(screen, "SYSTEM", "Windows")
    monkeypatch.setattr(screen, "screen_elements", lambda: elements)
    monkeypatch.setattr(screen, "click_point", click)
    monkeypatch.setattr(screen.time, "sleep", lambda s: None)
    monkeypatch.setitem(sys.modules, "pyautogui", types.SimpleNamespace(hotkey=hotkey, press=press,
                                                                       write=lambda t, interval=0: state["log"].append(("write", t))))
    return box, state


@pytest.mark.parametrize("phrase", ["clear the search bar", "clear the text in the search bar", "clear search",
                                    "clear the search box", "empty the search field", "delete everything in the search bar"])
def test_clear_the_search_bar(whatsapp_search, phrase):
    box, state = whatsapp_search
    r = Brain(Config()).handle(phrase)
    assert r.text == "Cleared the Search or start a new chat." and r.quiet
    assert box.text == ""
    assert state["log"][0] == ("click", 200, 100)  # the text box, not the Search button


def test_clear_falls_back_to_setting_the_value(whatsapp_search):
    box, state = whatsapp_search
    box.ignores_keyboard = True                  # e.g. keys went somewhere else
    assert screen.clear_field("search") == "Cleared the Search or start a new chat."
    assert box.text == ""


def test_clear_reports_honestly_when_it_cannot(whatsapp_search, monkeypatch):
    box, state = whatsapp_search
    box.ignores_keyboard = True
    box.pattern.SetValue = lambda value: None    # read-only box
    assert screen.clear_field("search") == "I tried to clear the Search or start a new chat, but it still says old search."


def test_clear_when_no_such_box(whatsapp_search):
    assert screen.clear_field("subject") == "I couldn't find a subject box on the screen."


def test_search_in_the_search_bar_replaces_the_text(whatsapp_search):
    box, state = whatsapp_search
    Brain(Config()).handle("search for imesai insight in the search bar")
    assert box.text == "" and ("write", "imesai insight") in state["log"]


def test_type_into_field_prefers_the_text_box_over_a_button(whatsapp_search):
    box, state = whatsapp_search
    Brain(Config()).handle("type Amma in the search box")
    assert state["log"][0] == ("click", 200, 100) and ("write", "Amma") in state["log"]


def test_play_ignores_phrases_about_text_boxes(monkeypatch):
    from jarvis.skills import web

    opened = []
    monkeypatch.setattr(web, "open_url", opened.append)
    asked = []
    b = Brain(Config(), fallback=lambda t: asked.append(t) or "ok")
    b.handle("play the text in the search")
    assert opened == [] and asked == ["play the text in the search"]
    b.handle("play interstellar theme")
    assert opened and "interstellar" in opened[0]
