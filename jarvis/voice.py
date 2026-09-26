"""Speech in (microphone → text) and speech out (text → speakers).

Both degrade gracefully: without pyttsx3 Jarvis prints instead of speaking,
and without SpeechRecognition/PyAudio the main loop uses typed input.
"""

from __future__ import annotations

import platform
import queue
import threading
import time


BRITISH_VOICE_HINTS = ("george", "daniel", "hazel", "en-gb", "english (great britain)", "united kingdom")


class Speaker:
    """Text to speech.

    On Windows this talks to the built-in Windows speech engine (SAPI) directly. pyttsx3 has a
    long-standing Windows bug where only the first sentence is spoken and later ones are silent.
    Elsewhere it uses pyttsx3.
    """

    def __init__(self, name: str = "Jarvis", mute: bool = False):
        self.name = name
        self._speak = None
        if mute:
            return
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

    def say(self, text: str) -> None:
        print(f"{self.name}: {text}")
        if self._speak is not None:
            try:
                self._speak(text)
            except Exception as e:
                print(f"(speech error: {e!r})")


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


class Listener:
    """Always-on microphone.

    A background thread records phrases non-stop into a queue, so nothing you say is lost while
    Jarvis is recognising, thinking or talking. Sound recorded while Jarvis itself is speaking is
    thrown away, so it never answers its own voice. Raises on init if no microphone is available.
    """

    def __init__(self, language: str = "en-US", sensitivity: str = "high", device_index: int | None = None,
                 start: bool = True):
        import speech_recognition as sr

        self.sr = sr
        self.language = language
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
        if self.speaking or started < self.ignore_before:
            return  # that was Jarvis talking
        self.phrases.put((started, duration, audio))

    # --- while Jarvis talks ---

    def mute(self) -> None:
        self.speaking = True

    def unmute(self) -> None:
        self.speaking = False
        self.ignore_before = time.time() + 0.25  # the tail of our own voice still echoing
        while True:
            try:
                self.phrases.get_nowait()
            except queue.Empty:
                break

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
        try:
            text = self.recognizer.recognize_google(audio, language=self.language)
        except self.sr.UnknownValueError:
            return None
        except self.sr.RequestError as e:
            print(f"(speech service unreachable: {e})")
            return None
        except Exception as e:  # timeouts and network trouble: never freeze the loop
            print(f"(speech recognition failed: {e!r})")
            return None
        print(f"(heard {duration:.1f}s of speech, recognised in {time.time() - begun:.1f}s)")
        return text
