"""Search the web and play things on YouTube."""

import re
import urllib.parse
import webbrowser

from ..brain import Response, action, skill


def open_url(url: str) -> None:
    webbrowser.open(url, new=2)


@skill(r"^(?:play|put on)\s+(?P<q>.+?)(?:\s+on youtube)?$")
def play(m, brain):
    q = m["q"]
    if re.search(r"\b(?:text|search (?:bar|box)|field|box|bar|this|that|it)\b", q, re.I):
        return None  # "play the text in the search" isn't a song
    open_url("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q))
    return action(f"Playing {q} on YouTube.")


@skill(r"^(?:search|google|look up)(?: for)?\s+(?P<q>.+?)(?:\s+on (?:google|the web))?$",
       r"^search (?:google|the web) for\s+(?P<q>.+)$")
def search(m, brain):
    q = m["q"]
    from .. import screen

    app = screen.working_app()
    said_web = re.search(r"\bon (?:google|the web)\b|^google\b|^search (?:google|the web)\b", m.string, re.I)
    if app and not said_web and app not in screen.BROWSER_LABELS and screen.SYSTEM == "Windows":
        # Working in WhatsApp (or any app): search inside it, don't wander off to Google.
        return action(screen.fill_field("search", q).replace("the search", f"{app}'s search"))
    open_url("https://www.google.com/search?q=" + urllib.parse.quote_plus(q))
    return action(f"Here's what I found for {q}.")

