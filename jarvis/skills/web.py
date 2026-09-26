"""Open websites, search the web and play things on YouTube."""

import urllib.parse
import webbrowser

from ..brain import Response, skill

SITES = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "maps": "https://maps.google.com",
    "google maps": "https://maps.google.com",
    "wikipedia": "https://www.wikipedia.org",
    "netflix": "https://www.netflix.com",
    "spotify": "https://open.spotify.com",
    "whatsapp": "https://web.whatsapp.com",
    "reddit": "https://www.reddit.com",
    "twitter": "https://x.com",
    "chatgpt": "https://chatgpt.com",
    "claude": "https://claude.ai",
}


def open_url(url: str) -> None:
    webbrowser.open(url, new=2)


@skill(r"^(?:play|put on)\s+(?P<q>.+?)(?:\s+on youtube)?$")
def play(m, brain):
    q = m["q"]
    open_url("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q))
    return Response(f"Playing {q} on YouTube.")


@skill(r"^(?:search|google|look up)(?: for)?\s+(?P<q>.+?)(?:\s+on (?:google|the web))?$",
       r"^search (?:google|the web) for\s+(?P<q>.+)$")
def search(m, brain):
    q = m["q"]
    open_url("https://www.google.com/search?q=" + urllib.parse.quote_plus(q))
    return Response(f"Here's what I found for {q}.")


@skill(r"^(?:open|launch|go to|show me)\s+(?P<site>[\w .-]+?)(?:\.com)?$")
def open_site(m, brain):
    site = m["site"].lower().strip()
    if site in SITES:
        url = SITES[site]
    elif "." in site and " " not in site:
        url = site if site.startswith("http") else f"https://{site}"
    else:
        url = f"https://www.{site.replace(' ', '')}.com"
    open_url(url)
    return Response(f"Opening {site}, {brain.title}.")
