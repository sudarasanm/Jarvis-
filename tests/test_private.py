import sys
import types

import pytest

from jarvis import ai, computer, dictation, screen
from jarvis.brain import Brain, redact
from jarvis.config import Config, load_settings, profile


@pytest.mark.parametrize("spoken, typed", [
    ("fourteen twenty six", "1426"),
    ("one one four", "114"),
    ("double seven three two", "7732"),
    ("two hundred and five", "205"),
    ("I have three apples and two oranges", "I have 3 apples and 2 oranges"),
    ("salt and pepper", "salt and pepper"),
    ("oh no", "oh no"),
    ("s u d a r a s a n s i v a", "sudarasansiva"),
    ("sudarshan shiva fourteen twenty six at gmail dot com", "sudarshanshiva1426@gmail.com"),
    ("sudarasansiva 1426 at the rate gmail dot com", "sudarasansiva1426@gmail.com"),
    ("meet me at 5 pm", "meet me at 5 pm"),
    ("Hello world", "Hello world"),
])
def test_dictation(spoken, typed):
    assert dictation.prepare(spoken) == typed


@pytest.fixture
def keyboard(monkeypatch):
    typed = []
    monkeypatch.setattr(computer, "type_text", lambda text: typed.append(text) or "Done.")
    return typed


def test_type_command_uses_dictation(monkeypatch):
    written = []
    monkeypatch.setitem(sys.modules, "pyautogui", types.SimpleNamespace(write=lambda t, interval=0: written.append(t)))
    b = Brain(Config())
    r = b.handle("type sudarshan shiva fourteen twenty six at the rate gmail dot com")
    assert written == ["sudarshanshiva1426@gmail.com"] and r.quiet
    b.handle("types s u d a r a s a n")
    assert written[-1] == "sudarasan"


def test_remember_and_type_details(keyboard):
    b = Brain(Config())
    assert b.handle("remember my email is sudarshan shiva fourteen twenty six at gmail dot com").text == \
        "Got it. Your email is sudarshanshiva1426@gmail.com."
    assert b.handle("my phone number is nine eight four one double two three four five six").text == \
        "Got it. Your phone number is 9 8 4 1 2 2 3 4 5 6."
    assert profile() == {"email": "sudarshanshiva1426@gmail.com", "phone": "9841223456"}
    r = b.handle("type my email")
    assert keyboard == ["sudarshanshiva1426@gmail.com"] and r.quiet
    assert b.handle("what's my email id").text == "Your email is sudarshanshiva1426@gmail.com."
    assert b.handle("forget my phone number").text == "Forgotten your phone number."
    assert "don't know your phone number" in b.handle("type my phone number").text


def test_my_name_is_also_sets_what_jarvis_calls_you(keyboard):
    b = Brain(Config())
    b.handle("my name is sudarsan m")
    assert profile()["name"] == "Sudarsan M" and b.config.user_title == "Sudarsan"


def test_password_is_typed_privately(keyboard):
    asked = []
    b = Brain(Config(), fallback=lambda text: asked.append(text) or "ok")
    r = b.handle("password is hunter two two")
    assert keyboard == ["hunter22"] and r.quiet
    assert asked == []                                   # never sent to the AI
    assert "password" not in str(load_settings()).lower()  # never saved
    assert "won't store passwords" in b.handle("remember my password is abc").text
    assert b.handle("pin this tab").text != "Typed the password."
    assert redact("password is hunter two two") == "password is ****"


def test_card_details_are_never_stored_or_sent(keyboard):
    asked = []
    b = Brain(Config(), fallback=lambda text: asked.append(text) or "ok")
    assert "don't store or type card details" in b.handle("remember my credit card number 4111 1111 1111 1111").text
    assert "don't store" in b.handle("my cvv is 123").text
    b.handle("pay with 4111 1111 1111 1111 please")
    assert asked == ["pay with [a long number] please"]
    assert redact("it's 4111 1111 1111 1111") == "it's ****"
    assert keyboard == []


def test_type_into_a_named_field_and_sign_in(keyboard, monkeypatch):
    clicks = []
    monkeypatch.setattr(screen, "SYSTEM", "Windows")
    monkeypatch.setattr(screen, "screen_elements", lambda: [
        screen.Element("Edit", "Account name", 500, 300), screen.Element("Edit", "Password", 500, 360),
        screen.Element("Button", "Sign in", 500, 420)])
    monkeypatch.setattr(screen, "click_point", lambda x, y, *a: clicks.append((x, y)))
    b = Brain(Config())
    r = b.handle("type sudarshan shiva fourteen twenty six in the account name field")
    assert clicks == [(500, 300)] and keyboard == ["sudarshanshiva1426"] and r.quiet
    r = b.handle("sign in")
    assert clicks[-1] == (500, 420) and r.quiet


def test_sign_in_falls_back_to_enter(monkeypatch):
    pressed = []
    monkeypatch.setattr(screen, "SYSTEM", "Windows")
    monkeypatch.setattr(screen, "screen_elements", lambda: [])
    monkeypatch.setitem(sys.modules, "pyautogui", types.SimpleNamespace(press=pressed.append))
    r = Brain(Config()).handle("log in")
    assert pressed == ["enter"] and "pressed Enter" in r.text and not r.quiet


def test_quick_actions_are_quiet_but_failures_speak(monkeypatch):
    monkeypatch.setattr(computer, "open_app", lambda name, settle=1.5, **kw: f"Opening {name}.")
    b = Brain(Config())
    assert b.handle("open steam").quiet
    monkeypatch.setattr(computer, "open_app", lambda name, settle=1.5, **kw: f"I couldn't find an app or website called {name}.")
    assert not b.handle("open blorp").quiet
    assert not b.handle("what time is it").quiet


def test_ai_done_is_quiet_and_other_answers_speak():
    brain = ai.Assistant(Config())
    brain.actions = ["open_app(steam) -> Opening steam."]
    from jarvis.brain import Quiet

    assert isinstance(brain.finish("open steam", "Done."), Quiet)
    brain.actions = ["get_weather() -> sunny"]
    assert not isinstance(brain.finish("weather?", "It's sunny and 31 degrees."), Quiet)


def test_ai_types_saved_details_without_seeing_them(keyboard):
    from jarvis.config import save_profile

    save_profile("email", "me@example.com")
    brain = ai.Assistant(Config())
    text, _ = brain.run_tool("type_my_detail", {"field": "email"})
    assert text == "Typed their email." and "me@example.com" not in text
    assert keyboard == ["me@example.com"]


def test_typing_returns_focus_to_the_working_app(monkeypatch):
    activated = []
    steam = types.SimpleNamespace(title="Sign in to Steam", _hWnd=5, visible=True, isMinimized=False,
                                  activate=lambda: activated.append("steam"))
    console = types.SimpleNamespace(title="Windows PowerShell", _hWnd=9, visible=True)
    pygetwindow = types.ModuleType("pygetwindow")
    pygetwindow.getActiveWindow = lambda: console
    monkeypatch.setitem(sys.modules, "pygetwindow", pygetwindow)
    monkeypatch.setattr(screen, "SYSTEM", "Windows")
    monkeypatch.setattr(screen, "_windows", lambda: [steam])
    monkeypatch.setattr(screen.time, "sleep", lambda s: None)
    screen.remember_app("steam")
    screen.ensure_focus()
    assert activated == ["steam"]  # Jarvis's console was in front: Steam brought back

    activated.clear()
    pygetwindow.getActiveWindow = lambda: types.SimpleNamespace(title="Notepad", _hWnd=7)
    screen.ensure_focus()
    assert activated == []  # the user moved to another app themselves: leave it


def test_everyday_phrases_are_not_hijacked(keyboard, monkeypatch):
    from jarvis.skills import web

    opened = []
    monkeypatch.setattr(web, "open_url", opened.append)
    asked = []
    b = Brain(Config(), fallback=lambda text: asked.append(text) or "Chat.")
    b.handle("search for credit card offers")
    assert opened and "credit+card+offers" in opened[0]
    assert b.handle("my phone is ringing").text == "Chat."
    assert b.handle("the password for wifi is on the router").text == "Chat."
    assert asked == ["my phone is ringing", "the password for wifi is on the router"]
    assert b.handle("remember my email is banana").text == "That doesn't sound like an email. Could you say it again?"
    assert keyboard == [] and profile() == {}
