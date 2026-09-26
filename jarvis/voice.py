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


class Listener:
    """Wraps SpeechRecognition + the default microphone. Raises on init if unavailable."""

    def __init__(self):
        import speech_recognition as sr

        self.sr = sr
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = 0.8
        self.microphone = sr.Microphone()
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=1)

    def listen(self, timeout: float | None = None, phrase_limit: float = 10) -> str | None:
        """Record one phrase and return its transcript, or None if nothing intelligible was heard."""
        with self.microphone as source:
            try:
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
            except self.sr.WaitTimeoutError:
                return None
        try:
            return self.recognizer.recognize_google(audio)
        except self.sr.UnknownValueError:
            return None
        except self.sr.RequestError:
            print("(speech service unreachable)")
            return None
