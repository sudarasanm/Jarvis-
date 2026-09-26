"""Speech in (microphone → text) and speech out (text → speakers).

Both degrade gracefully: without pyttsx3 Jarvis prints instead of speaking,
and without SpeechRecognition/PyAudio the main loop uses typed input.
"""

from __future__ import annotations

import platform
import re
import queue
import threading
import time


class MciPlayer:
    """Plays an MP3 through Windows' built-in media control interface (no extra packages), and can be stopped
    part-way through."""

    def __init__(self):
        import ctypes

        self._send_raw = ctypes.windll.winmm.mciSendStringW
        self._buffer = ctypes.create_unicode_buffer(128)
        self._count = 0

    def _send(self, command: str) -> tuple[int, str]:
        error = self._send_raw(command, self._buffer, 128, 0)
        return error, self._buffer.value

    def play(self, path: str, interrupted=None) -> bool:
        self._count += 1
        alias = f"jarvis{self._count}"
        error, _ = self._send(f'open "{path}" type mpegvideo alias {alias}')
        if error:
            raise RuntimeError(f"couldn't open audio (MCI error {error})")
        try:
            self._send(f"play {alias}")
            time.sleep(0.05)
            while True:
                _, mode = self._send(f"status {alias} mode")
                if mode != "playing":
                    return True
                if interrupted is not None and interrupted():
                    self._send(f"stop {alias}")
                    return False
                time.sleep(0.1)
        finally:
            self._send(f"close {alias}")


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", text.strip())
    return [p for p in parts if p.strip()]


class NeuralVoice:
    """Microsoft's natural neural voices (free, online, via edge-tts). Speaks sentence by sentence, preparing
    the next sentence while the current one plays, so long answers start quickly and "stop" works mid-way."""

    def __init__(self, voice: str = "en-GB-RyanNeural", rate: str = "+0%", player=None):
        import edge_tts

        self.edge_tts = edge_tts
        self.voice, self.rate = voice, rate
        self.player = player or MciPlayer()
        self._pool = None

    def synthesize(self, text: str) -> str:
        import os
        import tempfile
        import uuid

        path = os.path.join(tempfile.gettempdir(), f"jarvis-{uuid.uuid4().hex}.mp3")
        self.edge_tts.Communicate(text, self.voice, rate=self.rate, connect_timeout=5,
                                  receive_timeout=20).save_sync(path)
        return path

    def say(self, text: str, interrupted=None) -> bool:
        import concurrent.futures
        import os

        sentences = split_sentences(text) or [text]
        if self._pool is None:
            self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        upcoming = self._pool.submit(self.synthesize, sentences[0])
        finished = True
        paths = []
        try:
            for i in range(len(sentences)):
                path = upcoming.result(timeout=30)
                paths.append(path)
                if i + 1 < len(sentences):
                    upcoming = self._pool.submit(self.synthesize, sentences[i + 1])
                if not self.player.play(path, interrupted):
                    finished = False
                    break
                if interrupted is not None and interrupted():
                    finished = False
                    break
        finally:
            for path in paths:
                try:
                    os.remove(path)
                except OSError:
                    pass
        return finished


BRITISH_VOICE_HINTS = ("george", "daniel", "hazel", "en-gb", "english (great britain)", "united kingdom")


class Speaker:
    """Text to speech.

    On Windows this talks to the built-in Windows speech engine (SAPI) directly. pyttsx3 has a
    long-standing Windows bug where only the first sentence is spoken and later ones are silent.
    Elsewhere it uses pyttsx3.
    """

    def __init__(self, name: str = "Jarvis", mute: bool = False, engine: str = "edge",
                 voice: str = "en-GB-RyanNeural", rate: str = "+0%"):
        self.name = name
        self._speak = None
        self._sapi = None  # the Windows voice, which can speak in the background and be cut off
        self.neural = None  # the natural online voice, when available
        self._neural_failures = 0
        if mute:
            return
        if engine == "edge" and platform.system() == "Windows":
            try:
                self.neural = NeuralVoice(voice, rate)
            except Exception as e:
                print(f"(natural voice unavailable, using the Windows voice: {e!r})")
        if platform.system() == "Windows":
            self._speak = self._init_sapi()
        if self._speak is None:
            self._speak = self._init_pyttsx3()

    def _init_sapi(self):
        try:
            import win32com.client

            voice = win32com.client.Dispatch("SAPI.SpVoice")
            voices = voice.GetVoices()
            for i in range(voices.Count):
                if any(k in voices.Item(i).GetDescription().lower() for k in BRITISH_VOICE_HINTS):
                    voice.Voice = voices.Item(i)
                    break
            voice.Rate = 1  # -10 (slow) .. 10 (fast)
            self._sapi = voice
            return lambda text: voice.Speak(text)  # blocks until finished
        except Exception as e:
            print(f"(Windows speech unavailable, trying pyttsx3: {e!r})")
            return None

    def _init_pyttsx3(self):
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", 180)
            # Prefer a British voice when one is installed, for that authentic butler feel.
            for voice in engine.getProperty("voices"):
                label = f"{voice.name} {voice.id}".lower()
                if any(k in label for k in BRITISH_VOICE_HINTS):
                    engine.setProperty("voice", voice.id)
                    break

            def speak(text):
                engine.say(text)
                engine.runAndWait()

            return speak
        except Exception as e:
            print(f"(Speech output unavailable: {e!r})")
            return None

    SPEAK_ASYNC, PURGE = 1, 2  # SAPI flags

    def say(self, text: str, interrupted=None) -> bool:
        """Speak `text`. If `interrupted()` returns True while speaking (the user said "stop"), stop at once.
        Returns False if it was cut off."""
        print(f"{self.name}: {text}")
        if self.neural is not None:
            try:
                return self.neural.say(text, interrupted)
            except Exception as e:  # offline, service hiccup: the Windows voice takes over
                self._neural_failures += 1
                print(f"(natural voice failed, using the Windows voice: {e!r})")
                if self._neural_failures >= 3:
                    self.neural = None
        if self._speak is None:
            return True
        try:
            if self._sapi is not None and interrupted is not None:
                self._sapi.Speak(text, self.SPEAK_ASYNC)
                while not self._sapi.WaitUntilDone(100):
                    if interrupted():
                        self.stop()
                        return False
                return True
            self._speak(text)
        except Exception as e:
            print(f"(speech error: {e!r})")
        return True

    def stop(self) -> None:
        if self._sapi is not None:
            try:
                self._sapi.Speak("", self.SPEAK_ASYNC | self.PURGE)
            except Exception:
                pass


# How much quieter than the room's background noise speech may be and still count, as
# (initial threshold multiplier, dynamic adjustment ratio). Lower = hears quieter voices.
SENSITIVITY = {
    "low": (1.5, 2.0),
    "normal": (1.0, 1.5),
    "high": (0.6, 1.25),
    "max": (0.35, 1.1),
}


def boost_quiet_audio(raw: bytes, target_peak: int = 20000, max_gain: float = 8.0) -> bytes:
    """Amplify quiet 16-bit audio so soft speech reaches the recogniser at a normal level."""
    import sys
    from array import array

    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder == "big":  # audio from the microphone is little-endian
        samples.byteswap()
    peak = max((abs(x) for x in samples), default=0)
    if peak == 0 or peak >= target_peak:
        return raw
    gain = min(target_peak / peak, max_gain)
    boosted = array("h", (max(-32768, min(32767, int(x * gain))) for x in samples))
    if sys.byteorder == "big":
        boosted.byteswap()
    return boosted.tobytes()


def list_microphones() -> list[str]:
    import speech_recognition as sr

    return sr.Microphone.list_microphone_names()


class WhisperEar:
    """Offline speech recognition on this laptop (faster-whisper). The model (~150 MB for base.en) downloads
    once, the first time it's used."""

    def __init__(self, model: str = "base.en", language: str = "en-US"):
        self.model_name = model
        self.language = (language or "en").split("-")[0].lower()
        self._model = None
        self._lock = threading.Lock()

    def load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                print(f"(loading the offline Whisper model {self.model_name}; the first time it downloads)")
                self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        return self._model

    def preload(self) -> None:
        threading.Thread(target=self.load, name="whisper load", daemon=True).start()

    def transcribe(self, audio) -> str | None:
        import numpy as np

        raw = audio.get_raw_data(convert_rate=16000, convert_width=2)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        language = None if self.model_name.endswith(".en") else self.language
        segments, _info = self.load().transcribe(samples, language=language, beam_size=1)
        text = " ".join(s.text.strip() for s in segments).strip()
        return text or None


class Listener:
    """Always-on microphone.

    A background thread records phrases non-stop into a queue, so nothing you say is lost while
    Jarvis is recognising, thinking or talking. Sound recorded while Jarvis itself is speaking is
    thrown away, so it never answers its own voice. Raises on init if no microphone is available.
    """

    def __init__(self, language: str = "en-US", sensitivity: str = "high", device_index: int | None = None,
                 start: bool = True, engine: str = "auto", whisper_model: str = "base.en"):
        import speech_recognition as sr

        self.sr = sr
        self.language = language
        self.engine = engine  # "google", "whisper" or "auto" (Google, Whisper when that fails)
        self.whisper = WhisperEar(whisper_model, language) if engine in ("whisper", "auto") else None
        if engine == "whisper" and start:
            self.whisper.preload()
        self.recognizer = sr.Recognizer()
        self.recognizer.operation_timeout = 8  # never hang waiting for Google's speech service
        self.microphone = sr.Microphone(device_index=device_index)
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1.5)
        factor, ratio = SENSITIVITY.get(sensitivity, SENSITIVITY["high"])
        self.recognizer.energy_threshold = max(self.recognizer.energy_threshold * factor, 30)
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.dynamic_energy_adjustment_ratio = ratio
        self.recognizer.pause_threshold = 0.8  # seconds of silence that end a phrase
        self.recognizer.non_speaking_duration = 0.6  # audio kept from before speech starts
        self.phrase_limit = 15
        self.phrases: "queue.Queue" = queue.Queue()
        self.while_speaking: "queue.Queue" = queue.Queue()  # heard during Jarvis's own speech: checked for "stop"
        self.speaking = False
        self.ignore_before = 0.0
        if start:
            threading.Thread(target=self._capture, name="microphone", daemon=True).start()

    # --- recording (background thread) ---

    def _capture(self) -> None:
        with self.microphone as source:
            while True:
                try:
                    audio = self.recognizer.listen(source, phrase_time_limit=self.phrase_limit)
                except Exception as e:
                    print(f"(microphone error: {e!r})")
                    time.sleep(1)
                    continue
                self._offer(audio, time.time())

    def _offer(self, audio, ended: float) -> None:
        duration = len(audio.frame_data) / float(audio.sample_rate * audio.sample_width)
        started = ended - duration
        if self.speaking:
            self.while_speaking.put((started, duration, audio))  # maybe "stop"; maybe our own echo
            return
        if started < self.ignore_before:
            return  # the tail of Jarvis's own voice
        self.phrases.put((started, duration, audio))

    # --- while Jarvis talks ---

    def mute(self) -> None:
        self.speaking = True

    def unmute(self) -> None:
        self.speaking = False
        self.ignore_before = time.time() + 0.25  # the tail of our own voice still echoing
        for q in (self.phrases, self.while_speaking):
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

    def heard_while_speaking(self) -> str | None:
        """Recognise one phrase caught while Jarvis was talking, if any (doesn't wait)."""
        try:
            _started, duration, audio = self.while_speaking.get_nowait()
        except queue.Empty:
            return None
        return self.recognize(audio, duration)

    # --- recognising (main thread) ---

    def listen(self, timeout: float | None = None) -> str | None:
        """The next thing said, as text. None if nothing arrives within `timeout` or it wasn't words."""
        try:
            _started, duration, audio = self.phrases.get(timeout=timeout)
        except queue.Empty:
            return None
        return self.recognize(audio, duration)

    def recognize(self, audio, duration: float = 0.0) -> str | None:
        begun = time.time()
        if audio.sample_width == 2:
            audio = self.sr.AudioData(boost_quiet_audio(audio.get_raw_data()), audio.sample_rate, 2)
        text, how = None, "Google"
        if self.engine == "whisper":
            text, how = self._whisper(audio), "Whisper"
        else:
            try:
                text = self.recognizer.recognize_google(audio, language=self.language)
            except self.sr.UnknownValueError:
                return None  # Google heard no words: nothing to retry
            except Exception as e:  # offline, timeout, service trouble: never freeze the loop
                print(f"(Google speech recognition failed: {e!r})")
                if self.whisper is None:
                    return None
                text, how = self._whisper(audio), "Whisper (offline)"
        if text:
            print(f"(heard {duration:.1f}s of speech, recognised by {how} in {time.time() - begun:.1f}s)")
        return text

    def _whisper(self, audio) -> str | None:
        try:
            return self.whisper.transcribe(audio)
        except Exception as e:
            print(f"(offline Whisper recognition failed: {e!r})")
            return None
