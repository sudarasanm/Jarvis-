import sys
import types

import pytest

from jarvis import voice
from jarvis.brain import Brain
from jarvis.config import Config


class FakeEdge:
    """Stands in for edge_tts: 'synthesises' by writing the sentence to the file."""

    made = []

    class Communicate:
        def __init__(self, text, voice, rate="+0%", connect_timeout=None, receive_timeout=None):
            self.text, self.voice, self.rate = text, voice, rate

        def save_sync(self, path):
            FakeEdge.made.append((self.text, self.voice, self.rate))
            with open(path, "w") as f:
                f.write(self.text)


class FakePlayer:
    def __init__(self, stop_after=None):
        self.played, self.stop_after = [], stop_after

    def play(self, path, interrupted=None):
        with open(path) as f:
            self.played.append(f.read())
        if self.stop_after is not None and len(self.played) >= self.stop_after:
            return False  # "stop" heard while this sentence played
        return True


@pytest.fixture
def edge(monkeypatch):
    FakeEdge.made = []
    monkeypatch.setitem(sys.modules, "edge_tts", FakeEdge)


def test_neural_voice_speaks_sentence_by_sentence(edge):
    player = FakePlayer()
    nv = voice.NeuralVoice("en-GB-RyanNeural", "+5%", player=player)
    assert nv.say("Good evening, sir. The weather is fine! Shall we begin?")
    assert player.played == ["Good evening, sir.", "The weather is fine!", "Shall we begin?"]
    assert FakeEdge.made[0] == ("Good evening, sir.", "en-GB-RyanNeural", "+5%")


def test_neural_voice_stops_mid_way(edge):
    player = FakePlayer(stop_after=1)
    nv = voice.NeuralVoice(player=player)
    assert nv.say("One. Two. Three.") is False
    assert player.played == ["One."]


def test_windows_voice_takes_over_when_the_neural_voice_fails():
    speaker = voice.Speaker(mute=True)
    spoken = []
    speaker._speak = spoken.append

    class Broken:
        def say(self, text, interrupted=None):
            raise OSError("no internet")

    speaker.neural = Broken()
    assert speaker.say("Hello.")
    assert spoken == ["Hello."]
    speaker.say("Again.")
    speaker.say("And again.")
    assert speaker.neural is None  # after 3 failures, stop trying the online voice


def test_split_sentences():
    assert voice.split_sentences("Hi. I'm Jarvis! Ready? ok") == ["Hi.", "I'm Jarvis!", "Ready? ok"]
    assert voice.split_sentences("Version 3.5 is out.") == ["Version 3.5 is out."]


class FakeSR:
    class UnknownValueError(Exception):
        pass

    class RequestError(Exception):
        pass

    class AudioData:
        def __init__(self, raw, rate, width):
            self.raw, self.sample_rate, self.sample_width = raw, rate, width

        def get_raw_data(self, **kw):
            return self.raw


def make_listener(engine, google):
    listener = voice.Listener.__new__(voice.Listener)
    listener.sr = FakeSR
    listener.engine = engine
    listener.language = "en-IN"
    listener.recognizer = types.SimpleNamespace(recognize_google=google)
    listener.whisper = types.SimpleNamespace(transcribe=lambda audio: "offline words")
    return listener


def audio():
    return FakeSR.AudioData(b"\x00\x10" * 100, 16000, 2)


def test_auto_uses_google_then_whisper_when_offline():
    ok = make_listener("auto", lambda a, language: "online words")
    assert ok.recognize(audio()) == "online words"

    def offline(a, language):
        raise OSError("no internet")

    assert make_listener("auto", offline).recognize(audio()) == "offline words"


def test_auto_does_not_retry_when_google_heard_no_words():
    def silence(a, language):
        raise FakeSR.UnknownValueError()

    assert make_listener("auto", silence).recognize(audio()) is None


def test_whisper_only():
    def never(a, language):
        raise AssertionError("Google shouldn't be used")

    assert make_listener("whisper", never).recognize(audio()) == "offline words"


def test_wake_up_is_a_wake_phrase():
    b = Brain(Config())
    assert b.strip_wake_word("wake up") == (True, "")
    assert b.strip_wake_word("wake up what's the time") == (True, "what's the time")


def test_env_file_settings(tmp_path, monkeypatch):
    pytest.importorskip("dotenv")
    from jarvis import config

    (tmp_path / ".env").write_text("JARVIS_TTS_VOICE=en-IN-PrabhatNeural\nJARVIS_STT_ENGINE=whisper\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JARVIS_TTS_VOICE", raising=False)
    monkeypatch.delenv("JARVIS_STT_ENGINE", raising=False)
    config.load_env_files()
    c = Config()
    assert c.tts_voice == "en-IN-PrabhatNeural" and c.stt_engine == "whisper"
    monkeypatch.delenv("JARVIS_TTS_VOICE")
    monkeypatch.delenv("JARVIS_STT_ENGINE")


def test_log_rotation(tmp_path, monkeypatch):
    from jarvis import __main__ as main

    log = tmp_path / ".jarvis.log"
    monkeypatch.setattr(main, "LOG_FILE", log)
    for generation in range(5):
        log.write_text(f"gen {generation} " + "x" * 2000)
        main.rotate_log(max_bytes=1000, keep=3)
    kept = sorted(p.name for p in tmp_path.iterdir())
    assert kept == [".jarvis.log.1", ".jarvis.log.2", ".jarvis.log.3"]
    assert (tmp_path / ".jarvis.log.1").read_text().startswith("gen 4")
