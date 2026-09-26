"""Speech in (microphone → text) and speech out (text → speakers).

Both degrade gracefully: without pyttsx3 Jarvis prints instead of speaking,
and without SpeechRecognition/PyAudio the main loop uses typed input.
"""

from __future__ import annotations


class Speaker:
    def __init__(self, name: str = "Jarvis", mute: bool = False):
        self.name = name
        self.engine = None
        if mute:
            return
        try:
            import pyttsx3

            self.engine = pyttsx3.init()
            self.engine.setProperty("rate", 180)
            # Prefer a British male voice when one is installed, for that authentic butler feel.
            for voice in self.engine.getProperty("voices"):
                label = f"{voice.name} {voice.id}".lower()
                if any(k in label for k in ("daniel", "george", "en-gb", "english (great britain)")):
                    self.engine.setProperty("voice", voice.id)
                    break
        except Exception:
            self.engine = None

    def say(self, text: str) -> None:
        print(f"{self.name}: {text}")
        if self.engine is not None:
            self.engine.say(text)
            self.engine.runAndWait()


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
    """Wraps SpeechRecognition + a microphone. Raises on init if unavailable."""

    def __init__(self, language: str = "en-US", sensitivity: str = "high", device_index: int | None = None):
        import speech_recognition as sr

        self.sr = sr
        self.language = language
        self.recognizer = sr.Recognizer()
        self.microphone = sr.Microphone(device_index=device_index)
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1.5)
        factor, ratio = SENSITIVITY.get(sensitivity, SENSITIVITY["high"])
        self.recognizer.energy_threshold = max(self.recognizer.energy_threshold * factor, 30)
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.dynamic_energy_adjustment_ratio = ratio
        self.recognizer.non_speaking_duration = 0.6  # audio kept from before speech starts

    def listen(self, timeout: float | None = None, phrase_limit: float = 8, pause: float = 0.8) -> str | None:
        """Record one phrase and return its transcript, or None if nothing intelligible was heard.

        pause: seconds of silence that end a phrase (longer in conversation, so you can think mid-sentence).
        """
        self.recognizer.pause_threshold = pause
        with self.microphone as source:
            print("(listening...)")
            try:
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
            except self.sr.WaitTimeoutError:
                return None
        print("(recognizing...)")
        if audio.sample_width == 2:
            audio = self.sr.AudioData(boost_quiet_audio(audio.get_raw_data()), audio.sample_rate, 2)
        try:
            return self.recognizer.recognize_google(audio, language=self.language)
        except self.sr.UnknownValueError:
            return None
        except self.sr.RequestError:
            print("(speech service unreachable)")
            return None
