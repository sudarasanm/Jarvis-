"""Personal details, passwords and forms. Loaded first: none of this is sent to the AI.

- "remember my email is ..." / "type my email" / "what's my phone number" / "forget my address"
- "password is ..."   typed straight into the app; never saved, never sent to the AI, masked in the log
- card numbers        never stored or sent anywhere
- "type X in the email field", "sign in", "submit", "allow"
"""

import re

from .. import computer, dictation, screen, vision
from ..brain import Response, action, skill
from ..config import forget_profile, profile, save_profile

FIELDS = {
    "email": ["email id", "email address", "e-mail id", "e-mail", "email", "mail id", "gmail id", "gmail"],
    "phone": ["phone number", "mobile number", "contact number", "phone", "mobile", "number"],
    "name": ["full name", "name"],
    "address": ["delivery address", "shipping address", "home address", "address"],
    "username": ["user name", "username", "user id"],
}
FIELD_WORDS = "|".join(sorted((re.escape(w) for ws in FIELDS.values() for w in ws), key=len, reverse=True))
SPOKEN = {"email": "email", "phone": "phone number", "name": "name", "address": "address", "username": "username"}


def field_of(words: str) -> str:
    words = words.lower().strip()
    return next(f for f, names in FIELDS.items() if words in names)


def clean_value(field: str, value: str) -> str:
    value = value.strip().rstrip(".")
    if field == "email":
        return dictation.spoken_email(dictation.join_spelled_letters(value))
    if field == "phone":
        return dictation.spoken_phone(value)
    if field == "name":
        return " ".join(w.capitalize() for w in dictation.join_spelled_letters(value).split())
    if field == "username":
        return dictation.prepare(value).replace(" ", "")
    return dictation.words_to_digits(value)


# --- passwords and cards (first, so nothing else ever sees them) --------------------------------

# Only these exact forms: "password is X", "type (my|the) password X", "my pin is X".
PASSWORD = re.compile(r"^(?:please\s+)?(?:(?:type|enter|put in)\s+(?:the\s+|my\s+)?(?:pass\s?word|passcode)\s+"
                      r"(?:is\s+|as\s+|:\s*)?|(?:the\s+|my\s+)?(?:pass\s?word|passcode)\s*(?:is|:)\s+|"
                      r"(?:the\s+|my\s+)?pin\s+(?:is|number is)\s+)(?P<pw>.+)$", re.I)


@skill(PASSWORD.pattern)
def password(m, brain):
    value = m["pw"].strip()
    if re.match(r"^(?:for|of|field|box|in|into|here|there)\b", value, re.I):
        return None  # "type the password in the field" etc.: not a password
    if re.search(r"\b(remember|save|store)\b", m.string, re.I):
        return Response("I won't store passwords. Say \"password is\" and the password when you need it typed.")
    computer.type_text(dictation.secret(value))
    return Response("Typed the password.", quiet=True)


@skill(r"\b(?:remember|save|store)\b.*\b(?:pass\s?words?|passcode|pin)\b")
def no_saved_passwords(m, brain):
    return Response("I won't store passwords. Say \"password is\" and the password whenever you need it typed.")


CARD = re.compile(r"\b(?:(?:credit|debit|atm|visa|master\s?card|rupay)\s*cards?|card\s*(?:number|no|details)|"
                  r"cvv|cvc|card\s+expiry)\b", re.I)


@skill(CARD.pattern)
def cards(m, brain):
    # Only when an actual card is involved, not "search for credit card offers".
    if not re.search(r"\d|\b(?:my|remember|save|store|type|enter|use|add|fill)\b", m.string, re.I):
        return None
    return Response("I don't store or type card details. Amazon and your browser keep your card safely: pick the "
                    "saved card at checkout, or add it there once yourself.")


def saved_detail(field: str) -> str | None:
    value = profile().get(field)
    if not value and field == "email":
        from ..config import load_settings

        value = load_settings().get("email_account")  # the Gmail set up with --setup-email
    return value


# --- remembered details ---------------------------------------------------------------------------

@skill(rf"^(?:please\s+)?(?:remember|save|note|store)\s+(?:that\s+)?my\s+(?P<field>{FIELD_WORDS})\s+(?:is|as)\s+(?P<value>.+)$",
       rf"^my\s+(?P<field>{FIELD_WORDS})\s+is\s+(?P<value>.+)$")
def remember_skill(m, brain):
    return remember(m, brain)


def looks_right(field: str, raw: str, value: str) -> bool:
    """Is this plausibly a value for the field? ("my phone is ringing" isn't a phone number.)"""
    if field == "email":
        return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.\w{2,}", value))
    if field == "phone":
        return len(re.sub(r"\D", "", value)) >= 6
    if field == "address":
        return len(raw.split()) >= 3
    return bool(value)


def remember(m, brain):
    field = field_of(m["field"])
    value = clean_value(field, m["value"])
    if not looks_right(field, m["value"], value):
        if m.string.lower().startswith(("remember", "save", "note", "store", "please")):
            article = "an" if SPOKEN[field][0] in "aeiou" else "a"
            return Response(f"That doesn't sound like {article} {SPOKEN[field]}. Could you say it again?")
        return None  # just conversation
    save_profile(field, value)
    if field == "name":  # "my name is ..." also sets what Jarvis calls you
        from ..config import save_setting

        brain.config.user_title = value.split()[0] if value else brain.config.user_title
        save_setting("user_title", brain.config.user_title)
    spoken = " ".join(value) if field == "phone" else value
    return Response(f"Got it. Your {SPOKEN[field]} is {spoken}.")


@skill(rf"^(?:please\s+)?(?:type|enter|fill in|put|write)\s+(?:in\s+)?my\s+(?P<field>{FIELD_WORDS})"
       r"(?:\s+(?:in|into|on)\s+(?:the\s+)?(?P<target>.+?)(?:\s+(?:field|box|bar))?)?$")
def type_detail(m, brain):
    field = field_of(m["field"])
    value = saved_detail(field)
    if not value:
        return Response(f"I don't know your {SPOKEN[field]} yet. The surest way: in PowerShell run "
                        "python -m jarvis --details and type it in.")
    if m["target"]:
        result = screen.click(m["target"], locate=lambda t: vision.locate(t, brain.config))
        if result.startswith("I couldn't"):
            return Response(result)
    computer.type_text(value)
    return Response(f"Typed your {SPOKEN[field]}.", quiet=True)


@skill(rf"^what(?:'?s| is) my\s+(?P<field>{FIELD_WORDS})$")
def read_detail(m, brain):
    field = field_of(m["field"])
    value = profile().get(field)
    if not value:
        return Response(f"You haven't told me your {SPOKEN[field]} yet.")
    return Response(f"Your {SPOKEN[field]} is {' '.join(value) if field == 'phone' else value}.")


@skill(rf"^(?:please\s+)?(?:forget|delete|remove)\s+my\s+(?P<field>{FIELD_WORDS})$")
def forget_detail(m, brain):
    field = field_of(m["field"])
    if forget_profile(field):
        return Response(f"Forgotten your {SPOKEN[field]}.")
    return Response(f"I didn't have your {SPOKEN[field]} saved.")


# --- forms ----------------------------------------------------------------------------------------

@skill(r"^(?:please\s+)?(?:clear|empty|erase|delete|remove|wipe|reset)\s+(?:out\s+)?(?:all\s+)?(?:of\s+)?(?:the\s+)?"
       r"(?:text|words|everything|writing)?\s*(?:in|from|on|inside)?\s*(?:the\s+|this\s+|my\s+)?"
       r"(?P<field>search(?:\s+(?:bar|box|field))?|address bar|url bar|[\w\s-]+?\s+(?:field|box|bar))$",
       r"^(?:please\s+)?clear\s+(?:the\s+)?search$")
def clear(m, brain):
    field = m.groupdict().get("field") or "search"
    if re.search(r"\bsearch\b", field, re.I) and not re.search(r"\b(?:chat|conversation)\b", field, re.I):
        field = "search"  # "Pind from the left side of the search bar" -> the search box
    return action(screen.clear_field(field))


@skill(r"^(?:please\s+)?(?:remove|delete|clear|erase)\s+(?P<text>.+?)\s+(?:from|in|on)\s+(?:the\s+)?"
       r"(?:left(?:\s+side)?(?:\s+of)?(?:\s+the)?\s+)?search(?:\s+(?:bar|box|field))?$")
def remove_from_search(m, brain):
    return action(screen.clear_field("search"))


@skill(r"^(?:please\s+)?search\s+(?:for\s+)?(?P<text>.+?)\s+in\s+(?:the\s+)?search(?:\s+(?:bar|box))?$")
def search_box(m, brain):
    return action(screen.fill_field("search", dictation.prepare(m["text"])))


@skill(r"^(?:please\s+)?(?:give|put|set|enter|use|fill in|make)\s+(?:me\s+|in\s+)?(?:the\s+|my\s+)?"
       r"(?P<field>account name|user ?name|user id|login|log in|email(?: id| address)?|e-mail)\s+(?:as|to|is|with)\s+(?P<text>.+)$")
def field_as(m, brain):
    return type_into_field(m, brain)


@skill(r"^(?:please\s+)?(?:type|enter|put|fill in|write)\s+(?P<text>.+?)\s+(?:in|into|on)\s+(?:the\s+)?"
       r"(?P<field>[\w\s-]+?)\s+(?:field|box|bar)$")
def type_into_field(m, brain):
    box = None
    try:
        box = screen.find_input(m["field"]) if screen.SYSTEM == "Windows" else None
    except Exception:
        box = None
    if box is not None:  # a real text box by that name: click it (not a same-named button)
        screen.click_point(box.x, box.y)
    else:
        result = screen.click(m["field"], locate=lambda t: vision.locate(t, brain.config))
        if result.startswith("I couldn't"):
            return Response(result)
    text = dictation.prepare(m["text"])
    if re.search(r"\b(?:user|account|login|log in|sign in|e-?mail|id)\b", m["field"], re.I):
        text = text.replace(" ", "")  # usernames and emails have no spaces
    computer.type_text(text)
    return Response(f"Typed it into {m['field']}.", quiet=True)


SUBMIT_NAMES = {"sign in": ["sign in", "log in", "login", "next", "continue"],
                "log in": ["log in", "login", "sign in", "next", "continue"]}


@skill(r"^(?:please\s+)?(?:click\s+(?:on\s+)?|press\s+)?(?:the\s+)?(?P<what>sign in|log in|login|sign up|submit|accept|"
       r"agree|allow|verify)(?:\s+button)?(?:\s+please)?$")
def submit(m, brain):
    what = m["what"].lower().replace("login", "log in")
    names = SUBMIT_NAMES.get(what, [what])
    screen.ensure_focus()
    try:
        elements = screen.screen_elements() if screen.SYSTEM == "Windows" else []
    except Exception:
        elements = []
    for name in names:
        element = screen.find_element(name, elements)
        if element is not None:
            screen.click_point(element.x, element.y)
            return action(f"Clicked {element.name}.")
    point = vision.locate(f"the {what} button", brain.config)
    if point is not None:
        screen.click_point(*point)
        return action(f"Clicked {what}.")
    import pyautogui

    pyautogui.press("enter")
    return Response(f"I couldn't see a {what} button, so I pressed Enter.")
