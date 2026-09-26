import sys
import types

from jarvis import voice


def test_windows_speaker_speaks_every_sentence(monkeypatch):
    spoken = []

    class FakeVoiceInfo:
        def __init__(self, desc):
            self.desc = desc

        def GetDescription(self):
            return self.desc

    class FakeVoices:
        items = [FakeVoiceInfo("Microsoft David - English (United States)"),
                 FakeVoiceInfo("Microsoft George - English (Great Britain)")]
        Count = 2

        def Item(self, i):
            return self.items[i]

    class FakeSpVoice:
        Voice = None
        Rate = 0

        def GetVoices(self):
            return FakeVoices()

        def Speak(self, text):
            spoken.append(text)

    sapi = FakeSpVoice()
    win32com = types.ModuleType("win32com")
    win32com.client = types.SimpleNamespace(Dispatch=lambda name: sapi)
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", win32com.client)
    monkeypatch.setattr(voice.platform, "system", lambda: "Windows")

    speaker = voice.Speaker()
    for line in ["Jarvis online.", "I'll call you Susan from now on.", "Goodbye."]:
        speaker.say(line)
    assert spoken == ["Jarvis online.", "I'll call you Susan from now on.", "Goodbye."]
    assert "George" in sapi.Voice.GetDescription()


def test_speech_errors_do_not_crash(monkeypatch):
    speaker = voice.Speaker(mute=True)
    speaker._speak = lambda text: 1 / 0
    speaker.say("hello")  # printed, error logged, no exception


def test_stop_words_cut_jarvis_off_but_its_own_voice_does_not():
    from jarvis.__main__ import STOP_WORDS, stop_requested

    for phrase in ["stop", "Stop stop stop", "okay stop", "Jarvis stop", "be quiet", "enough", "shut up please",
                   "wait", "cancel"]:
        assert STOP_WORDS.match(phrase), phrase
    for phrase in ["don't stop me now", "the bus stop is near", "what's the weather", "stop the music in Spotify"]:
        assert not STOP_WORDS.match(phrase), phrase

    class Heard:
        def __init__(self, *phrases):
            self.phrases = list(phrases)

        def heard_while_speaking(self):
            return self.phrases.pop(0) if self.phrases else None

    assert not stop_requested(Heard("the weather today is sunny and warm"), "The weather today is sunny and warm.")
    assert stop_requested(Heard("stop"), "The weather today is sunny and warm.")


def test_windows_speech_stops_when_interrupted(monkeypatch):
    calls = []

    class FakeSapi:
        def __init__(self):
            self.polls = 0

        def Speak(self, text, flags=0):
            calls.append((text, flags))

        def WaitUntilDone(self, ms):
            self.polls += 1
            return self.polls > 50  # a long paragraph

    speaker = voice.Speaker(mute=True)
    speaker._speak = lambda text: None
    speaker._sapi = FakeSapi()
    asked = []
    finished = speaker.say("A very long paragraph...", interrupted=lambda: asked.append(1) or len(asked) >= 3)
    assert not finished
    assert calls == [("A very long paragraph...", 1), ("", 3)]  # spoken in the background, then purged


def test_listener_keeps_what_it_hears_while_speaking():
    import queue
    import types

    from jarvis.voice import Listener

    listener = Listener.__new__(Listener)
    listener.phrases, listener.while_speaking = queue.Queue(), queue.Queue()
    listener.speaking, listener.ignore_before = False, 0.0
    audio = types.SimpleNamespace(frame_data=b"\0" * 32000, sample_rate=16000, sample_width=2)
    listener.mute()
    listener._offer(audio, ended=1000.0)
    assert listener.while_speaking.qsize() == 1 and listener.phrases.empty()
    listener.recognize = lambda audio, duration=0: "stop"
    assert listener.heard_while_speaking() == "stop"
    listener.unmute()
    assert listener.while_speaking.empty()
