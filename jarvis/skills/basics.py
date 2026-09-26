"""Greetings, time, date, jokes, help and goodbye."""

import random
from datetime import datetime

from ..brain import Response, skill
from ..config import save_setting

JOKES = [
    "I would tell you a UDP joke, but you might not get it.",
    "There are 10 kinds of people: those who understand binary and those who don't.",
    "I asked the Wi-Fi for a joke. It said the connection was weak.",
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I'm reading a book on anti-gravity. It's impossible to put down.",
]


@skill(r"^(hi|hello|hey|good (morning|afternoon|evening)|what'?s up)$", r"^(are you there|you there|wake up)$")
def greet(m, brain):
    hour = datetime.now().hour
    part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
    return Response(f"Good {part}, {brain.title}. How can I help?")


@skill(r"\bhow are you\b")
def how_are_you(m, brain):
    return Response(f"All systems operational, {brain.title}. Thank you for asking.")


@skill(r"\bwho are you\b", r"\bwhat('?s| is) your name\b", r"\bintroduce yourself\b")
def identity(m, brain):
    return Response(f"I am {brain.config.name}, your personal assistant. Just A Rather Very Intelligent System.")


FILLER_WORDS = {"a", "an", "as", "the", "by", "is", "me", "it's", "its"}


def _set_name(name: str, brain) -> Response:
    words = name.split()
    while words and words[0].lower() in FILLER_WORDS:
        words.pop(0)
    if not words:
        return Response("Sorry, I didn't catch that. What would you like me to call you?",
                        on_reply=lambda text: _set_name(text, brain))
    name = " ".join(w.capitalize() for w in words[:3])
    brain.config.user_title = name
    save_setting("user_title", name)
    return Response(f"Very well. I'll call you {name} from now on.")


@skill(r"\b(?:call me|my name is)(?P<name>(?:\s+[a-z][a-z'-]*){0,4})$")
def call_me(m, brain):
    return _set_name(m["name"], brain)


@skill(r"\bwhat(?:'?s| is) my name\b", r"\bwho am i\b")
def my_name(m, brain):
    return Response(f"You are {brain.title}, of course.")


@skill(r"\bwhat time\b", r"\btime is it\b", r"^(the )?time$")
def tell_time(m, brain):
    return Response(f"It's {datetime.now().strftime('%I:%M %p').lstrip('0')}, {brain.title}.")


@skill(r"\bwhat('?s| is) (the |today'?s )?date\b", r"\bwhat day is (it|today)\b", r"^(the )?date$")
def tell_date(m, brain):
    return Response(f"Today is {datetime.now().strftime('%A, %B %d, %Y').replace(' 0', ' ')}.")


@skill(r"\b(tell me )?a joke\b", r"\bmake me laugh\b")
def joke(m, brain):
    return Response(random.choice(JOKES))


@skill(r"\bthank(s| you)\b")
def thanks(m, brain):
    return Response(f"Always a pleasure, {brain.title}.")


@skill(r"^help$", r"\bwhat can you do\b")
def help_(m, brain):
    return Response(
        "I can tell you the time, date and weather, open websites, search the web, play things on YouTube, "
        "report system status, and shut down, restart, lock or sleep your computer. "
        "Anything else, just ask."
    )


@skill(r"^(?:ok(?:ay)?\s+)?(goodbye|good ?bye|bye( bye)?|good night|see you( later)?|that'?s all|that will be all|"
       r"nothing( else)?|never ?mind|talk (to you )?later)$")
def goodbye(m, brain):
    return Response(f"Very well, {brain.title}. Just say my name if you need me.", sleep=True)


@skill(r"^(exit|quit|go offline|power down|shut (yourself )?down|turn (yourself )?off|"
       r"(close|quit|exit) (yourself|jarvis))$")
def quit_(m, brain):
    return Response(f"Powering down. Goodbye, {brain.title}.", exit=True)
