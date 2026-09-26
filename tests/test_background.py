"""v3.0 Phase 1: background service, wake word, push-to-talk, tray state, mute, action log."""

import types

import pytest

from jarvis import actions
from jarvis.brain import Brain
from jarvis.config import Config
from jarvis.voice import WAKE


class WakeListener:
    """A listener with the offline wake word: returns the scripted items, then stops the test."""

    def __init__(self, items, on_empty=None):
        self.items = list(items)
        self.wake = object()
        self.wake_only = True
        self.on_empty = on_empty
        self.modes = []

    def listen(self, timeout=None):
        self.modes.append(self.wake_only)
        if not self.items:
            raise StopIteration
        item = self.items.pop(0)
        return item() if callable(item) else item

    def mute(self):
        pass

    def unmute(self):
        pass

    def heard_while_speaking(self):
        return None


def run(brain, listener, always_awake=False):
    from jarvis.__main__ import voice_loop
    from jarvis.voice import Speaker

    said = []
    speaker = Speaker(mute=True)
    speaker.say = lambda text, interrupted=None: said.append(text) or True
    with pytest.raises(StopIteration):
        voice_loop(brain, speaker, listener, always_awake=always_awake)
    return said


def test_hey_jarvis_opens_a_conversation(fresh_state):
    b = Brain(Config(conversation_timeout=0))
    listener = WakeListener([WAKE, "what time is it", None, "tell me a joke"])
    said = run(b, listener)
    assert len(said) == 1 and said[0].startswith("It's")  # the joke came after the conversation ended
    assert listener.modes[0] is True                       # only the wake word before "Hey Jarvis"
    assert listener.modes[1] is False                      # then the command is heard
    assert listener.wake_only is True                      # and back to the wake word afterwards


def test_push_to_talk_starts_listening(fresh_state):
    b = Brain(Config())
    fresh_state.listen_now.set()
    said = run(b, WakeListener(["what time is it"]))
    assert said[0].startswith("It's") and not fresh_state.listen_now.is_set()


def test_tray_exit_ends_the_loop(fresh_state):
    from jarvis.__main__ import voice_loop
    from jarvis.voice import Speaker

    fresh_state.exit_requested.set()
    voice_loop(Brain(Config()), Speaker(mute=True), WakeListener([]))  # returns at once, no StopIteration


def test_mute_listening_and_wake_word_unmutes(fresh_state):
    b = Brain(Config())
    r = b.handle("mute")
    assert fresh_state.muted and r.sleep and "Hey Jarvis" in r.text
    assert fresh_state.shown == "muted"
    said = run(b, WakeListener(["what time is it", WAKE, "what time is it"]), always_awake=True)
    assert len(said) == 1          # while muted, always_listen was suspended
    assert not fresh_state.muted   # "Hey Jarvis" unmuted


def test_go_to_sleep_and_stop_listening_mute_instead_of_quitting(fresh_state):
    b = Brain(Config())
    for phrase in ("go to sleep", "stop listening"):
        fresh_state.set_muted(False)
        r = b.handle(phrase)
        assert fresh_state.muted and not r.exit
    assert b.handle("unmute").text.startswith("Listening again") and not fresh_state.muted
    assert b.handle("go offline").exit


def test_mute_the_sound_is_still_volume(monkeypatch):
    from jarvis import system

    calls = []
    monkeypatch.setattr(system, "set_volume", lambda level, change: calls.append(change) or "Muted.")
    Brain(Config()).handle("mute the sound")
    assert calls == ["mute"]


def test_action_log_and_what_did_you_do_today(monkeypatch):
    b = Brain(Config(), fallback=lambda text: "Done")
    b.handle("what time is it")
    b.handle("password is hunter22")
    entries = actions.today()
    assert [e["kind"] for e in entries] == ["command", "command"]
    assert "hunter22" not in actions.ACTIONS_FILE.read_text()  # passwords are masked in the log too
    actions.record("tool", tool="open_app", args="chrome", result="Opened Chrome.", ok=True)
    text = b.handle("what did you do today").text
    assert "2 commands" in text and "1 action" in text and "what time is it" in text


def test_ai_tools_are_logged_and_show_acting(monkeypatch, fresh_state):
    from jarvis.ai import Assistant

    seen = []
    fresh_state.watch(lambda s: seen.append(s.status))
    assistant = Assistant.__new__(Assistant)
    assistant.actions = []
    assistant._dispatch = lambda name, args: "Opened Chrome."
    assert assistant.run_tool("open_app", {"name": "chrome"}) == ("Opened Chrome.", False)
    assert seen[:2] == ["acting", "thinking"]
    assert actions.today()[-1]["tool"] == "open_app"


def test_state_shown_priority(fresh_state):
    fresh_state.set("thinking")
    fresh_state.set_muted(True)
    assert fresh_state.shown == "thinking"  # busy still shows while muted
    fresh_state.set("idle")
    assert fresh_state.shown == "muted"
    fresh_state.set_mic_off(True)
    assert fresh_state.shown == "mic_off"


def test_tray_icon_colours():
    from jarvis.tray import COLOURS, circle

    image = circle(COLOURS["listening"])
    assert image.size == (64, 64) and image.getpixel((32, 32))[3] == 255


# --- the watchdog ---------------------------------------------------------------------------------

class FakeChild:
    def __init__(self, code):
        self.code = code

    def wait(self):
        return self.code


def watchdog(codes, clock=None):
    from jarvis.service import Watchdog

    codes = list(codes)
    started = []
    dog = Watchdog(command=["jarvis"], spawn=lambda: started.append(1) or FakeChild(codes.pop(0)),
                   clock=clock or (lambda: 0.0))
    dog.stopping.wait = lambda delay: False  # no real waiting in tests
    return dog, started


def test_watchdog_restarts_after_a_crash_and_stops_on_a_clean_exit():
    dog, started = watchdog([1, 1, 0])
    assert dog.run() == 2 and len(started) == 3


def test_watchdog_gives_up_after_five_quick_crashes():
    dog, started = watchdog([1] * 10)
    dog.run()
    assert len(started) == 5


def test_watchdog_forgets_old_crashes():
    times = iter(range(0, 100000, 400))  # a crash every ~13 minutes: never 5 within 10 minutes
    dog, started = watchdog([1] * 8 + [0], clock=lambda: float(next(times)))
    dog.run()
    assert len(started) == 9


def test_backoff_grows_to_a_minute():
    from jarvis.service import backoff

    assert [backoff(n) for n in (1, 2, 3, 6, 9)] == [2, 4, 8, 60, 60]


# --- the microphone thread -------------------------------------------------------------------------

def test_capture_hears_the_wake_word_then_records_the_command(fresh_state):
    from jarvis.voice import Listener

    class FakeWake:
        def __init__(self):
            self.calls = 0

        def heard(self, chunk):
            self.calls += 1
            return self.calls == 3

    class Recognizer:
        def listen(self, source, timeout=None, phrase_time_limit=None):
            fresh_state.set_mic_off(True)  # stop the loop after one phrase
            return types.SimpleNamespace(frame_data=b"\0" * 3200, sample_rate=16000, sample_width=2)

    listener = Listener.__new__(Listener)
    import queue
    import speech_recognition as sr

    listener.sr, listener.wake, listener.wake_only, listener.speaking = sr, FakeWake(), True, False
    listener.recognizer, listener.phrase_limit, listener.ignore_before = Recognizer(), 15, 0.0
    listener.phrases, listener.while_speaking = queue.Queue(), queue.Queue()
    source = types.SimpleNamespace(CHUNK=1280, stream=types.SimpleNamespace(read=lambda n: b"\0" * n * 2))
    listener._record(source, fresh_state)
    assert listener.phrases.get_nowait() is WAKE
    assert listener.phrases.get_nowait()[1] == pytest.approx(0.1)  # then the command's audio


def test_wake_word_detector_triggers_once(monkeypatch):
    np = pytest.importorskip("numpy")

    from jarvis.wakeword import WakeWord

    detector = WakeWord.__new__(WakeWord)
    scores = iter([0.1, 0.9, 0.2])
    resets = []
    detector.np, detector.threshold, detector.name = np, 0.5, "hey_jarvis"
    detector.model = types.SimpleNamespace(predict=lambda samples: {"hey_jarvis": next(scores)},
                                           reset=lambda: resets.append(1))
    chunk = np.zeros(1280, dtype=np.int16).tobytes()
    assert [detector.heard(chunk) for _ in range(3)] == [False, True, False]
    assert resets == [1]


def test_no_openwakeword_falls_back_to_speech(monkeypatch):
    from jarvis import wakeword

    assert wakeword.make_wake_word("speech", 0.5) is None
    monkeypatch.setattr(wakeword, "WakeWord", lambda threshold: (_ for _ in ()).throw(ImportError("no")))
    assert wakeword.make_wake_word("openwakeword", 0.5) is None


def test_ai_never_fills_password_fields(monkeypatch):
    from jarvis import screen
    from jarvis.ai import Assistant

    filled = []
    monkeypatch.setattr(screen, "fill_field", lambda field, text: filled.append(field) or "Filled.")
    assistant = Assistant.__new__(Assistant)
    assistant.config = Config()
    assert assistant._dispatch("fill_field", {"field": "Password", "text": "x"}).startswith("Refused")
    assert assistant._dispatch("fill_field", {"field": "card number", "text": "x"}).startswith("Refused")
    assert assistant._dispatch("fill_field", {"field": "search", "text": "x"}) == "Filled."
    assert filled == ["search"]


def test_type_into_the_password_field_is_refused(keyboard_typed):
    b = Brain(Config())
    assert "don't handle passwords" in b.handle("type hunter22 in the password field").text
    assert keyboard_typed == []


@pytest.fixture
def keyboard_typed(monkeypatch):
    from jarvis import computer

    typed = []
    monkeypatch.setattr(computer, "type_text", lambda text: typed.append(text) or "Typed.")
    return typed
