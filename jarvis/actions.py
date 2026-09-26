"""A log of what Jarvis did (logs/actions.jsonl), for "Jarvis, what did you do today?"."""

from __future__ import annotations

import json
import time
from datetime import datetime

from .state import LOG_DIR

ACTIONS_FILE = LOG_DIR / "actions.jsonl"


def record(kind: str, **details) -> None:
    """kind: 'command' (what the user said and the reply) or 'tool' (an action the AI took)."""
    entry = {"time": datetime.now().isoformat(timespec="seconds"), "kind": kind, **details}
    try:
        ACTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(ACTIONS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def today() -> list[dict]:
    date = time.strftime("%Y-%m-%d")
    try:
        lines = ACTIONS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("time", "").startswith(date):
            entries.append(entry)
    return entries


def summary_today(limit: int = 8) -> str:
    entries = today()
    commands = [e for e in entries if e["kind"] == "command"]
    tools = [e for e in entries if e["kind"] == "tool"]
    if not entries:
        return "Nothing yet today."
    recent = [e.get("heard", "") for e in commands[-limit:] if e.get("heard")]
    text = f"Today you gave me {len(commands)} command{'s' if len(commands) != 1 else ''}"
    text += f" and I took {len(tools)} action{'s' if len(tools) != 1 else ''}."
    if recent:
        text += " The latest: " + "; ".join(recent) + "."
    return text
