"""Open and close apps, type text, press keys and draft emails."""

import re
import urllib.parse

from .. import computer, dictation, screen, vision
from ..brain import ASK_AI, Response, action, skill

ORDINALS = re.compile(r"\b(first|second|third|fourth|fifth|last|next|previous|top|bottom|\d+(st|nd|rd|th))\b", re.I)


def _complex(text: str, brain) -> bool:
    """Multi-step requests ("open chrome and search for...") go to Claude when it's available."""
    return brain.fallback is not None and bool(re.search(r"\b(and|then)\b", text))


BROWSER = r"(?:(?:in|on|from)\s+(?:the\s+|my\s+)?(?P<browser>chrome|google chrome|brave|edge|microsoft edge|firefox))?"


BROWSERS = r"(?:chrome|google chrome|brave|edge|microsoft edge|firefox)"
IN_BROWSER = rf"(?:\s+(?:in|on)\s+(?:the\s+|my\s+)?(?P<browser>{BROWSERS})(?:\s+browser)?)?"


def _browser(m, group="browser"):
    value = m.groupdict().get(group)
    return value.split()[-1].lower() if value else None


def _site(site: str):
    """("youtube") -> (url, label); "search for X" becomes a Google search."""
    site = site.strip()
    query = re.match(r"^(?:search|google|look up)(?:\s+for)?\s+(?P<q>.+)$", site, re.I)
    if query:
        return "https://www.google.com/search?q=" + urllib.parse.quote_plus(query["q"]), f"a search for {query['q']}"
    return computer.url_for(site), site


@skill(rf"^(?:please\s+)?(?:open|start|create|make|add)\s+(?:a\s+|the\s+|another\s+|one\s+)?new\s+tab{IN_BROWSER}"
       r"(?:\s+(?:and\s+|then\s+)?(?P<verb>go\s+to|open|with|for|to|at|load|search(?:\s+for)?|google|look\s+up)"
       r"\s+(?P<site>.+?))?"
       rf"(?:\s+(?:in|on)\s+(?:the\s+|my\s+)?(?P<browser2>{BROWSERS}))?$",
       rf"^(?:a\s+)?new\s+tab{IN_BROWSER}$")
def new_tab(m, brain):
    browser = _browser(m) or _browser(m, "browser2")
    site = m.groupdict().get("site")
    if site:
        verb = (m.groupdict().get("verb") or "").lower()
        url, label = _site(f"search for {site}" if verb.startswith(("search", "google", "look")) else site)
        return action(screen.new_tab(browser, url, label))
    return action(screen.new_tab(browser))


@skill(rf"^(?:please\s+)?(?:open|go to|load)\s+(?P<site>.+?)\s+in\s+(?:a\s+)?new\s+tab{IN_BROWSER}$",
       rf"^(?:please\s+)?(?:open|go to|load)\s+(?P<site>.+?)\s+(?:in|on|with|using)\s+(?:the\s+|my\s+)?"
       rf"(?P<browser>{BROWSERS})(?:\s+browser)?$")
def site_in_browser(m, brain):
    url, label = _site(m["site"])
    return action(screen.new_tab(_browser(m), url, label))


@skill(rf"^(?:please\s+)?close\s+(?:this|the current|current|the|that|my)\s+tab{IN_BROWSER}$", r"^close tab$")
def close_current_tab(m, brain):
    return action(screen.tab_action("close", _browser(m)))


@skill(rf"^(?:please\s+)?(?:go\s+to\s+|switch\s+to\s+|move\s+to\s+)?(?:the\s+)?"
       rf"(?P<which>next|previous|prev|last|first)\s+tab{IN_BROWSER}$")
def next_tab(m, brain):
    which = {"prev": "previous"}.get(m["which"].lower(), m["which"].lower())
    return action(screen.tab_action(which, _browser(m)))


@skill(r"\b(?:reopen|re-open|restore|bring back|undo close)\b.*\btabs?\b")
def reopen_tab(m, brain):
    return action(screen.tab_action("reopen"))


@skill(rf"^(?:please\s+)?(?:open|start|create)\s+(?:a\s+)?new\s+(?:(?P<private>private|incognito|inprivate|in private)\s+)?"
       rf"window{IN_BROWSER}$",
       rf"^(?:please\s+)?(?:open|start|go)\s+(?:an?\s+)?(?:in\s+)?(?P<private2>incognito|private|inprivate|in private)"
       rf"(?:\s+browsing)?(?:\s+(?:window|tab|mode))?{IN_BROWSER}$")
def new_window(m, brain):
    private = m.groupdict().get("private") or m.groupdict().get("private2")
    return action(screen.tab_action("private_window" if private else "new_window", _browser(m)))


@skill(r"^(?:please\s+)?(?:reload|refresh)(?:\s+(?:the|this))?(?:\s+(?:page|tab))?$", r"^go\s+(?P<dir>back|forward)$")
def page_nav(m, brain):
    direction = m.groupdict().get("dir")
    return action(screen.tab_action(direction.lower() if direction else "reload"))


@skill(rf"^(?:please\s+)?close\s+(?:all\s+)?(?:the\s+)?(?:other\s+)?tabs\s+(?:except|but|apart from)\s+(?:the\s+)?"
       rf"(?P<keep>.+?)(?:\s+tab)?{IN_BROWSER}$",
       rf"^(?:please\s+)?close\s+(?:all\s+)?(?:the\s+)?other\s+tabs{IN_BROWSER}$")
def close_other_tabs(m, brain):
    return action(screen.close_other_tabs(m.groupdict().get("keep"), _browser(m)))


@skill(rf"^(?:list|show|tell me|what are|which are|read)\b.*\btabs?\b(?:\s+(?:open\s+)?{BROWSER})?(?:\s+open)?$",
       r"^(?:what|which) tabs\b.*$")
def tabs(m, brain):
    browser = m.groupdict().get("browser")
    return action(screen.list_tabs(browser.split()[-1].lower() if browser else None))


@skill(r"^close\s+(?:the\s+)?(?P<title>.+?)\s+(?:in|on|from)\s+(?:the\s+|my\s+)?"
       r"(?P<browser>chrome|google chrome|brave|edge|microsoft edge|firefox)(?:\s+tabs?)?$",
       rf"^close\s+(?:the\s+|my\s+)?(?P<title>.+?)\s+tab\s*{BROWSER}$",
       rf"^close\s+(?:the\s+)?tab\s+(?:called\s+|named\s+)?(?P<title>.+?)\s*{BROWSER}$")
def close_tab(m, brain):
    if _complex(m["title"], brain):
        return ASK_AI
    browser = m.groupdict().get("browser")
    return action(screen.close_tab(m["title"], browser.split()[-1].lower() if browser else None))


@skill(rf"^(?:switch|go)\s+to\s+(?:the\s+)?(?P<title>.+?)\s+tab\s*{BROWSER}$")
def switch_tab(m, brain):
    browser = m.groupdict().get("browser")
    return action(screen.switch_to_tab(m["title"], browser.split()[-1].lower() if browser else None))


@skill(r"\b(?:write|send|compose|draft)\b.*\be-?mail\b")
def email(m, brain):
    if brain.fallback is not None:
        return ASK_AI  # the AI writes a much better email than a template
    text = m.string
    to = re.search(r"\bto\s+(?P<to>.+?)(?:\s+(?:about|saying|regarding|that)\s+(?P<topic>.+))?$", text, re.I)
    if not to:
        return Response("Who should I send it to?", on_reply=lambda reply: _email_to(reply, "", brain))
    return _email_to(to["to"], to["topic"] or "", brain)


def _email_to(to: str, topic: str, brain) -> Response:
    return action(computer.compose_email(to, subject=topic.capitalize(), body="", client=brain.config.email_client))


@skill(r"^(?:please\s+)?(?:open|launch|go to)\s+(?P<name>.+?)(?:\s+(?:for me|please))?$")
def open_(m, brain):
    if _complex(m["name"], brain):
        return ASK_AI
    result = computer.open_app(m["name"], guess_sites=brain.fallback is None)
    if brain.fallback is not None and result.startswith(("I couldn't find", "Sorry, I didn't catch")):
        return ASK_AI  # nothing was opened; the AI can work out what was meant
    return action(result)


@skill(r"^(?:please\s+)?(?:close|quit|exit|kill)\s+(?P<name>.+?)(?:\s+(?:for me|please))?$")
def close(m, brain):
    if _complex(m["name"], brain):
        return ASK_AI
    if m["name"].lower() in {"yourself", "jarvis"}:
        return None  # "close yourself" is handled by the quit skill
    result = computer.close_app(m["name"])
    if brain.fallback is not None and result.startswith("I can't see"):
        return ASK_AI  # nothing was closed; the AI can look at tabs and the screen
    return action(result)


@skill(r"^(?:type|types|typed|dictate)\s+(?P<text>.+)$")
def type_(m, brain):
    return action(computer.type_text(dictation.prepare(m["text"])))


@skill(r"^(?:press|hit)\s+(?P<keys>.+)$")
def press(m, brain):
    return action(computer.press_keys(m["keys"]))


@skill(r"^(?:(?P<how>double|right)[ -])?(?:click|tap)(?: on)?\s+(?:the\s+)?(?P<target>.+?)(?:\s+button)?$")
def click(m, brain):
    # "click the second profile" needs judgement about the screen: let the AI look.
    if brain.fallback is not None and ORDINALS.search(m["target"]):
        return ASK_AI
    how = (m["how"] or "").lower()
    return action(screen.click(m["target"], double=how == "double", right=how == "right",
                                 locate=lambda target: vision.locate(target, brain.config)))


@skill(r"^scroll (?P<dir>up|down)(?: (?:a )?(?P<amount>little|lot|bit))?$")
def scroll(m, brain):
    amount = {"bit": "little"}.get(m["amount"], m["amount"] or "normal")
    return action(screen.scroll(m["dir"].lower(), amount))


@skill(r"^switch (?:to|over to)\s+(?P<name>.+)$")
def switch(m, brain):
    return action(screen.switch_to_window(m["name"]))


@skill(r"\b(?:what|which) windows\b", r"^(?:list|show) (?:all )?(?:the |my )?(?:open )?windows$")
def windows(m, brain):
    return action(screen.list_windows())


@skill(r"\b(?:list|show|which|what)\b.*\b(?:profiles?|accounts?|users?)\b.*\b(?P<browser>chrome|brave|edge)\b",
       r"\b(?P<browser>chrome|brave|edge)\b.*\b(?:profiles?|accounts?|users?)\b")
def profiles(m, brain):
    return action(computer.list_browser_profiles(m["browser"].lower()))
