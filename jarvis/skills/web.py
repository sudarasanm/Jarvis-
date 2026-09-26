"""Search the web and play things on YouTube."""

import urllib.parse
import webbrowser

from ..brain import Response, action, skill


def open_url(url: str) -> None:
    webbrowser.open(url, new=2)


@skill(r"^(?:play|put on)\s+(?P<q>.+?)(?:\s+on youtube)?$")
def play(m, brain):
    q = m["q"]
    open_url("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q))
    return action(f"Playing {q} on YouTube.")


@skill(r"^(?:search|google|look up)(?: for)?\s+(?P<q>.+?)(?:\s+on (?:google|the web))?$",
       r"^search (?:google|the web) for\s+(?P<q>.+)$")
def search(m, brain):
    q = m["q"]
    open_url("https://www.google.com/search?q=" + urllib.parse.quote_plus(q))
    return action(f"Here's what I found for {q}.")

