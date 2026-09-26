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
