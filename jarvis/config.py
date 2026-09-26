"""Runtime settings, read from environment variables and ~/.jarvis.json."""

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


def _flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    name: str = field(default_factory=lambda: os.environ.get("JARVIS_NAME", "Jarvis"))
    user_title: str = field(
        default_factory=lambda: os.environ.get("JARVIS_USER_TITLE") or load_settings().get("user_title", "sir")
    )
    city: str | None = field(default_factory=lambda: os.environ.get("JARVIS_CITY") or None)
    units: str = field(default_factory=lambda: os.environ.get("JARVIS_UNITS", "metric"))
    # When true, power commands (shutdown, restart...) are printed instead of executed.
    dry_run: bool = field(default_factory=lambda: _flag("JARVIS_DRY_RUN"))
    claude_model: str = field(default_factory=lambda: os.environ.get("JARVIS_CLAUDE_MODEL", "claude-opus-5"))

    @property
    def wake_word(self) -> str:
        return self.name.lower()
