"""The laptop itself: popups, "close it", installing apps, volume, brightness, Settings pages, specs,
busy apps and network. Loaded before the other skills so these phrases win."""

import platform
import re

from .. import screen, system, vision
from ..brain import ASK_AI, Response, action, skill

PRONOUNS = r"(?:it|this|that|them|this one|that one|this window|that window|the window)"
# Broad keyword skills must not steal dictation or searches ("type the volume is too high").
NOT_DICTATION = r"^(?!(?:type|dictate|write|search|google|look up|play)\b)"


@skill(r"^(?:please\s+)?(?:close|dismiss|get rid of|remove|skip|hide|cancel)\s+(?:the\s+|this\s+|that\s+)?"
       r"(?:pop[ -]?ups?|dialog(?:ue)?(?: box)?|message(?: box)?|notification|banner|prompt|ad|advert(?:isement)?)\b.*$")
def popup(m, brain):
    return action(screen.dismiss_popup(locate=lambda target: vision.locate(target, brain.config)))


@skill(rf"^(?:please\s+)?(?:yes,?\s+)?(?:please\s+)?(?P<verb>close|open|shut)\s+{PRONOUNS}(?:\s+please)?$")
def pronoun(m, brain):
    # "it" means whatever we were just talking about: the AI knows, the regex doesn't.
    if brain.fallback is not None:
        return ASK_AI
    if m["verb"].lower() == "open":
        return Response("Open what?")
    return action(screen.close_front_window())


@skill(r"^(?:please\s+)?(?:can you\s+)?(?:install|download and install)\s+(?P<name>.+?)"
       r"(?:\s+(?:for me|on (?:my|this) (?:laptop|computer|pc|system)|please))*$")
def install(m, brain):
    if platform.system() != "Windows":
        return Response("Installing apps only works on Windows for now.")
    name = m["name"]
    package = system.find_package(name)
    if package is None:
        return Response(f"I couldn't find {name} in the Windows app catalogue.")
    version = f", version {package['version']}" if package.get("version") else ""
    return Response(f"I found {package['name']}{version}. Shall I install it?",
                    on_confirm=lambda: Response(system.install_package(package, brain.notify)))


def _level(text: str):
    number = re.search(r"\b(\d{1,3})\b", text)
    return int(number.group(1)) if number else None


def _change(text: str):
    text = text.lower()
    if re.search(r"\bunmute\b", text):
        return "unmute"
    if re.search(r"\bmute\b", text):
        return "mute"
    if re.search(r"\b(up|increase|raise|louder|higher|brighter|more)\b", text):
        return "up"
    if re.search(r"\b(down|decrease|lower|reduce|quieter|softer|dimmer|darker|less)\b", text):
        return "down"
    return None


@skill(NOT_DICTATION + r".*\bvolume\b", r"^(?:un)?mute(?:\s+(?:the\s+)?(?:sound|audio|volume|laptop|computer))?$",
       r"^(?:louder|quieter|softer)(?: please)?$")
def volume(m, brain):
    text = m.string
    change = _change(text)
    level = _level(text)
    return action(system.set_volume(level if level is not None else None, None if level is not None else change))


@skill(NOT_DICTATION + r".*\bbrightness\b", r"^(?:make it |make the screen )?(?:brighter|dimmer|darker)(?: please)?$")
def brightness(m, brain):
    text = m.string
    level = _level(text)
    change = None if level is not None else _change(text)
    return action(system.set_brightness(level, change if change in ("up", "down") else None))


@skill(r"^(?:please\s+)?(?:open|show|go to)\s+(?:the\s+|my\s+)?(?P<page>.+?)\s+settings?$")
def settings(m, brain):
    return action(system.open_settings(m["page"]))


@skill(r"\b(?:system|computer|laptop|pc|machine)\s+(?:specs?|specifications|details|info(?:rmation)?|"
       r"configuration|config|hardware)\b",
       r"\bwhat (?:laptop|computer|pc|machine|model) (?:is this|do i have|am i using)\b",
       r"\b(?:my|this) (?:laptop|computer|pc)'?s? (?:specs?|configuration|config)\b")
def specs(m, brain):
    return action(system.system_info())


@skill(r"\b(?:system|computer|laptop|pc)\s+(?:status|report|health|usage)\b", NOT_DICTATION + r".*\bbattery\b",
       r"\b(?:cpu|memory|ram|disk|storage)\s+(?:usage|space|left)\b", r"\bhow much (?:ram|memory|storage|disk)\b",
       r"\bhow long (?:has|have) (?:the )?(?:laptop|computer|pc|it) been (?:on|running|up)\b")
def status(m, brain):
    return action(system.usage())


@skill(r"\bwhat(?:'?s| is)\b.*\b(?:using|eating|hogging|slowing|taking)\b.*\b(?:cpu|memory|ram|laptop|computer|pc|down)\b",
       r"\b(?:top|busiest|heaviest|biggest)\s+(?:apps|processes|programs)\b",
       r"\b(?:which|what)\s+(?:apps|processes|programs)\s+are\s+(?:running|using)\b",
       r"\bwhy is (?:my |the )?(?:laptop|computer|pc) (?:so )?slow\b")
def busy_apps(m, brain):
    return action(system.top_processes("cpu" if "cpu" in m.string.lower() else "memory"))


@skill(r"\b(?:wifi|wi-fi|internet|network)\s+(?:status|connection|name|speed)\b",
       r"\bam i (?:connected|online)\b", r"\bwhat(?:'?s| is) my (?:ip|wifi|wi-fi)\b",
       r"\b(?:is|check) (?:the |my )?(?:internet|wifi|wi-fi)\b")
def network(m, brain):
    return action(system.network())
