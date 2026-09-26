"""What Jarvis is doing right now, shared by the voice loop, the AI, the tray icon and the hotkey.

    idle       waiting for "Hey Jarvis" (or push-to-talk)
    listening  in a conversation: everything said is taken as a command
    thinking   working out an answer
    acting     using a tool (opening, clicking, typing...)
    speaking   talking
    muted      only the wake word is listened for ("Jarvis, mute" / "go to sleep")
    mic_off    microphone fully closed (tray privacy switch)
"""

from __future__ import annotations

import threading
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_DIR / "logs"


class State:
    def __init__(self):
        self.status = "idle"
        self.muted = False
        self.mic_off = False
        self.listen_now = threading.Event()   # push-to-talk / tray "Listen now"
        self.exit_requested = threading.Event()
        self._watchers = []
        self._lock = threading.Lock()

    @property
    def shown(self) -> str:
        """What the tray shows: privacy and mute win over activity."""
        if self.mic_off:
            return "mic_off"
        if self.muted and self.status in ("idle", "listening"):
            return "muted"
        return self.status

    def watch(self, callback) -> None:
        self._watchers.append(callback)

    def _changed(self) -> None:
        for callback in list(self._watchers):
            try:
                callback(self)
            except Exception as e:
                print(f"(state watcher failed: {e!r})")

    def set(self, status: str) -> None:
        with self._lock:
            if status == self.status:
                return
            self.status = status
        self._changed()

    def set_muted(self, muted: bool) -> None:
        self.muted = muted
        self._changed()

    def set_mic_off(self, off: bool) -> None:
        self.mic_off = off
        self._changed()


state = State()
