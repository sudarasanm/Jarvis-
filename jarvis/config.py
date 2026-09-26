"""Runtime settings.

Each setting is read from an environment variable (JARVIS_<NAME>), then from
~/.jarvis.json, then falls back to a default. ~/.jarvis.json lives outside the
code folder, so it's the right place for your API key too.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# Things Jarvis learns by voice (e.g. "call me Tony") are remembered here.
SETTINGS_FILE = Path.home() / ".jarvis.json"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_setting(key: str, value) -> None:
    data = load_settings()
    data[key] = value
    try:
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def setting(key: str, default=None):
    env = os.environ.get(f"JARVIS_{key.upper()}")
    if env not in (None, ""):
        return env
    return load_settings().get(key, default)


def _flag(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _setting_field(key: str, default=None, cast=None):
    def factory():
        value = setting(key, default)
        return cast(value) if cast is not None and value is not None else value

    return field(default_factory=factory)


@dataclass
class Config:
    name: str = _setting_field("name", "Jarvis")
    user_title: str = _setting_field("user_title", "sir")
    city: str | None = _setting_field("city")
    units: str = _setting_field("units", "metric")
    # When true, power commands (shutdown, restart...) are printed instead of executed.
    dry_run: bool = _setting_field("dry_run", False, _flag)
    # Which AI brain to try first: auto, claude, gemini or ollama. The others (if set up) are backups.
    ai_provider: str = _setting_field("ai_provider", "auto")
    claude_model: str = _setting_field("claude_model", "claude-opus-5")
    gemini_model: str = _setting_field("gemini_model", "gemini-flash-latest")
    # Tried when the main model's free limit is used up; each model has its own free quota.
    gemini_backup_models: str = _setting_field("gemini_backup_models", "gemini-flash-lite-latest")
    ollama_model: str = _setting_field("ollama_model", "llama3.2")
    ollama_url: str = _setting_field("ollama_url", "http://localhost:11434")
    # Optional Ollama model that can see images (e.g. "llama3.2-vision"), used for looking at the
    # screen when there's no Gemini key.
    ollama_vision_model: str | None = _setting_field("ollama_vision_model")
    # Speech recognition language, e.g. en-US, en-GB, en-IN (Indian English), ta-IN (Tamil).
    language: str = _setting_field("language", "en-US")
    # How easily quiet speech is picked up: low, normal, high, max.
    mic_sensitivity: str = _setting_field("mic_sensitivity", "high")
    # Which microphone to use (see `python -m jarvis --list-mics`); empty = system default.
    mic_index: int | None = _setting_field("mic_index", None, int)
    # Answer everything you say, no "Jarvis" needed (same as --no-wake).
    always_listen: bool = _setting_field("always_listen", False, _flag)
    # Seconds of silence before a conversation ends and Jarvis waits for its name again.
    conversation_timeout: float = _setting_field("conversation_timeout", 12, float)
    # Where email drafts open: "gmail" or "default" (your mail app).
    email_client: str = _setting_field("email_client", "gmail")

    @property
    def wake_word(self) -> str:
        return self.name.lower()

    @property
    def wake_words(self) -> list[str]:
        """The name plus common speech-recognition mishearings of it."""
        words = [self.wake_word]
        if self.wake_word == "jarvis":
            words += ["jervis", "javis", "jarves", "jarvi", "jarvys", "travis", "harvis", "garvis", "charvis", "davis"]
        return words
