"""Open and close apps, type text, press keys and draft emails."""

import re

from .. import computer, screen, vision
from ..brain import Response, skill

ORDINALS = re.compile(r"\b(first|second|third|fourth|fifth|last|next|previous|top|bottom|\d+(st|nd|rd|th))\b", re.I)


def _complex(text: str, brain) -> bool:
    """Multi-step requests ("open chrome and search for...") go to Claude when it's available."""
    return brain.fallback is not None and bool(re.search(r"\b(and|then)\b", text))


BROWSER = r"(?:(?:in|on|from)\s+(?:the\s+|my\s+)?(?P<browser>chrome|google chrome|brave|edge|microsoft edge|firefox))?"


@skill(rf"^(?:list|show|tell me|what are|which are|read)\b.*\btabs?\b(?:\s+(?:open\s+)?{BROWSER})?(?:\s+open)?$",
       r"^(?:what|which) tabs\b.*$")
def tabs(m, brain):
    browser = m.groupdict().get("browser")
    return Response(screen.list_tabs(browser.split()[-1].lower() if browser else None))


@skill(r"^close\s+(?:the\s+)?(?P<title>.+?)\s+(?:in|on|from)\s+(?:the\s+|my\s+)?"
       r"(?P<browser>chrome|google chrome|brave|edge|microsoft edge|firefox)(?:\s+tabs?)?$",
       rf"^close\s+(?:the\s+|my\s+)?(?P<title>.+?)\s+tab\s*{BROWSER}$",
       rf"^close\s+(?:the\s+)?tab\s+(?:called\s+|named\s+)?(?P<title>.+?)\s*{BROWSER}$")
def close_tab(m, brain):
    if _complex(m["title"], brain):
        return None
    browser = m.groupdict().get("browser")
    return Response(screen.close_tab(m["title"], browser.split()[-1].lower() if browser else None))


@skill(rf"^(?:switch|go)\s+to\s+(?:the\s+)?(?P<title>.+?)\s+tab\s*{BROWSER}$")
def switch_tab(m, brain):
    browser = m.groupdict().get("browser")
    return Response(screen.switch_to_tab(m["title"], browser.split()[-1].lower() if browser else None))


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


@skill(r"^(?:(?P<how>double|right)[ -])?(?:click|tap)(?: on)?\s+(?:the\s+)?(?P<target>.+?)(?:\s+button)?$")
def click(m, brain):
    # "click the second profile" needs judgement about the screen: let the AI look.
    if brain.fallback is not None and ORDINALS.search(m["target"]):
        return None
    how = (m["how"] or "").lower()
    return Response(screen.click(m["target"], double=how == "double", right=how == "right",
                                 locate=lambda target: vision.locate(target, brain.config)))


@skill(r"^scroll (?P<dir>up|down)(?: (?:a )?(?P<amount>little|lot|bit))?$")
def scroll(m, brain):
    amount = {"bit": "little"}.get(m["amount"], m["amount"] or "normal")
    return Response(screen.scroll(m["dir"].lower(), amount))


@skill(r"^switch (?:to|over to)\s+(?P<name>.+)$")
def switch(m, brain):
    return Response(screen.switch_to_window(m["name"]))


@skill(r"\b(?:what|which) windows\b", r"^(?:list|show) (?:all )?(?:the |my )?(?:open )?windows$")
def windows(m, brain):
    return Response(screen.list_windows())


@skill(r"\b(?:list|show|which|what)\b.*\b(?:profiles?|accounts?|users?)\b.*\b(?P<browser>chrome|brave|edge)\b",
       r"\b(?P<browser>chrome|brave|edge)\b.*\b(?:profiles?|accounts?|users?)\b")
def profiles(m, brain):
    return Response(computer.list_browser_profiles(m["browser"].lower()))
