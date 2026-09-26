"""Offline "Hey Jarvis" detection with openWakeWord.

Runs on this laptop, nothing is sent anywhere, and it's light enough to run all day. Audio is 16 kHz, 16-bit
mono, fed in chunks of 1280 samples (80 ms). The "hey_jarvis" model (~1 MB) downloads once, the first time.
"""

from __future__ import annotations

CHUNK = 1280        # samples per prediction (80 ms at 16 kHz)
SAMPLE_RATE = 16000
MODEL = "hey_jarvis"


class WakeWord:
    """Say "Hey Jarvis": heard(chunk) turns True once. Raises on init if openWakeWord isn't installed."""

    def __init__(self, threshold: float = 0.5, model: str = MODEL):
        import numpy as np
        from openwakeword.model import Model

        self.np = np
        self.threshold = threshold
        self.name = model
        try:
            self.model = Model(wakeword_models=[model], inference_framework="onnx")
        except Exception:
            # First run: the model files aren't there yet.
            from openwakeword.utils import download_models

            print(f'(downloading the offline "{model}" wake word model, once)')
            download_models([model])
            self.model = Model(wakeword_models=[model], inference_framework="onnx")

    def heard(self, chunk: bytes) -> bool:
        samples = self.np.frombuffer(chunk, dtype=self.np.int16)
        if samples.size == 0:
            return False
        scores = self.model.predict(samples)
        score = max(scores.values(), default=0.0)
        if score >= self.threshold:
            print(f'(wake word "{self.name}" heard, score {score:.2f})')
            self.model.reset()  # so one "Hey Jarvis" doesn't trigger twice
            return True
        return False

    def reset(self) -> None:
        self.model.reset()


def make_wake_word(engine: str, threshold: float) -> WakeWord | None:
    """engine: "openwakeword" (offline "Hey Jarvis") or "speech" (listen for the name in recognised speech)."""
    if engine != "openwakeword":
        return None
    try:
        return WakeWord(threshold)
    except Exception as e:
        print(f'(offline wake word unavailable, listening for "Jarvis" in speech instead: {e!r})')
        return None
