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


@pytest.fixture
def two_search_boxes(monkeypatch):
    """WhatsApp: the chat list's search on the left, a search inside the open chat on the right."""
    left, right = FakeBox(""), FakeBox("")
    elements = [screen.Element("Edit", "Search", 1300, 90, right),
                screen.Element("Edit", "Search or start a new chat", 250, 100, left)]
    clicked = []
    focus = {"box": None}

    def click(x, y, *a):
        clicked.append((x, y))
        focus["box"] = left if x == 250 else right

    def press(key):
        if key == "backspace" and focus["box"] is not None:
            focus["box"].text = ""

    monkeypatch.setattr(screen, "SYSTEM", "Windows")
    monkeypatch.setattr(screen, "screen_elements", lambda: elements)
    monkeypatch.setattr(screen, "click_point", click)
    monkeypatch.setattr(screen.time, "sleep", lambda s: None)
    monkeypatch.setitem(sys.modules, "pyautogui", types.SimpleNamespace(
        hotkey=lambda *k: None, press=press, write=lambda t, interval=0: setattr(focus["box"], "text", t)))
    monkeypatch.setattr(computer, "type_text", lambda text: setattr(focus["box"], "text", text) or "Done.")
    return left, right, clicked


def test_clear_picks_the_search_box_that_has_text(two_search_boxes):
    left, right, clicked = two_search_boxes
    left.text = "imesai"
    assert screen.clear_field("search") == "Cleared the Search or start a new chat."
    assert left.text == "" and clicked == [(250, 100)]
    right.text = "ideas"
    assert screen.clear_field("search bar") == "Cleared the Search."
    assert right.text == ""


def test_typing_a_search_uses_the_chat_list_search(two_search_boxes):
    left, right, clicked = two_search_boxes
    right.text = "old"
    screen.fill_field("search", "Amma")
    assert left.text == "Amma" and right.text == "old"
    screen.fill_field("search in this chat", "meeting")
    assert right.text == "meeting"


def test_search_stays_inside_the_app_you_are_using(two_search_boxes, monkeypatch):
    from jarvis.skills import web

    left, right, clicked = two_search_boxes
    opened = []
    monkeypatch.setattr(web, "open_url", opened.append)
    b = Brain(Config())
    screen.remember_app("whatsapp")
    r = b.handle("search for IMI")
    assert left.text == "IMI" and opened == [] and r.quiet
    b.handle("search for IMI on google")           # asked for Google explicitly
    screen.remember_app("chrome")
    b.handle("search for cricket scores")         # in a browser: Google is right
    assert len(opened) == 2


def test_pind_is_pinned(monkeypatch):
    from jarvis import messaging

    opened = []
    monkeypatch.setattr(messaging, "open_whatsapp_chat_at", lambda n: opened.append(n) or "Opened the chat with Imesai.")
    assert Brain(Config()).handle("open the Pind chat").text == "Opened the chat with Imesai."
    assert Brain(Config()).handle("open the pinned contact").text == "Opened the chat with Imesai."
    assert opened == [1, 1]


def test_remove_text_from_the_left_search_bar(whatsapp_search):
    box, state = whatsapp_search
    r = Brain(Config()).handle("remove Pind from the left side of the search bar")
    assert box.text == "" and r.quiet


def test_hidden_note_is_never_spoken():
    from jarvis import ai

    assert ai.clean_speech("I couldn't find it. [Right now: Saturday, 07:32 PM; Window in front: WhatsApp]") == \
        "I couldn't find it."
