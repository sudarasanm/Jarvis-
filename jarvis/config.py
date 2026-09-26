"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _flag(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    name: str = field(default_factory=lambda: os.environ.get("JARVIS_NAME", "Jarvis"))
    user_title: str = field(default_factory=lambda: os.environ.get("JARVIS_USER_TITLE", "sir"))
    city: str | None = field(default_factory=lambda: os.environ.get("JARVIS_CITY") or None)
    units: str = field(default_factory=lambda: os.environ.get("JARVIS_UNITS", "metric"))
    # When true, power commands (shutdown, restart...) are printed instead of executed.
    dry_run: bool = field(default_factory=lambda: _flag("JARVIS_DRY_RUN"))
    claude_model: str = field(default_factory=lambda: os.environ.get("JARVIS_CLAUDE_MODEL", "claude-opus-5"))

    @property
    def wake_word(self) -> str:
        return self.name.lower()
