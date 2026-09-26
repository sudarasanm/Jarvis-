"""Open and close apps, type text, press keys and draft emails."""

import re

from .. import computer
from ..brain import Response, skill


def _complex(text: str, brain) -> bool:
    """Multi-step requests ("open chrome and search for...") go to Claude when it's available."""
    return brain.fallback is not None and bool(re.search(r"\b(and|then)\b", text))


@skill(r"\b(?:write|send|compose|draft)\b.*\be-?mail\b")
def email(m, brain):
    if brain.fallback is not None:
        return None  # Claude writes a much better email than a template
    text = m.string
    to = re.search(r"\bto\s+(?P<to>.+?)(?:\s+(?:about|saying|regarding|that)\s+(?P<topic>.+))?$", text, re.I)
    if not to:
        return Response("Who should I send it to?", on_reply=lambda reply: _email_to(reply, "", brain))
    return _email_to(to["to"], to["topic"] or "", brain)


def _email_to(to: str, topic: str, brain) -> Response:
    return Response(computer.compose_email(to, subject=topic.capitalize(), body="", client=brain.config.email_client))


@skill(r"^(?:please\s+)?(?:open|launch|go to)\s+(?P<name>.+?)(?:\s+(?:for me|please))?$")
def open_(m, brain):
    if _complex(m["name"], brain):
        return None
    return Response(computer.open_app(m["name"]))


@skill(r"^(?:please\s+)?(?:close|quit|exit|kill)\s+(?P<name>.+?)(?:\s+(?:for me|please))?$")
def close(m, brain):
    if _complex(m["name"], brain) or m["name"].lower() in {"yourself", "jarvis"}:
        return None  # "close yourself" is handled by the quit skill
    return Response(computer.close_app(m["name"]))


@skill(r"^(?:type|dictate)\s+(?P<text>.+)$")
def type_(m, brain):
    return Response(computer.type_text(m["text"]))


@skill(r"^(?:press|hit)\s+(?P<keys>.+)$")
def press(m, brain):
    return Response(computer.press_keys(m["keys"]))
