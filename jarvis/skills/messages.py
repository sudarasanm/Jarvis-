"""WhatsApp messages and email. Sending always waits for the user's yes."""

import re

from .. import messaging
from ..brain import ASK_AI, Response, action, skill

WA = r"(?:\s+(?:on|in|via|through)\s+whatsapp)?"
SAYS = r"(?:saying|that says|that|telling (?:him|her|them)|to say|:)"


@skill(rf"^(?:please\s+)?(?:send|write)\s+(?:a\s+)?(?:whatsapp\s+)?(?:message|msg|text)\s+to\s+(?P<contact>.+?){WA}\s+"
       rf"{SAYS}\s+(?P<message>.+)$",
       rf"^(?:please\s+)?whatsapp\s+(?P<contact>.+?)\s+{SAYS}\s+(?P<message>.+)$",
       rf"^(?:please\s+)?(?:tell|message|text)\s+(?P<contact>.+?)\s+on\s+whatsapp\s+(?:that\s+|saying\s+)?(?P<message>.+)$")
def whatsapp_send(m, brain):
    contact, message = m["contact"].strip(), m["message"].strip()
    if re.fullmatch(rf"(?:the\s+|my\s+)?{ORDINAL}\s+{CHAT}", contact, re.I):
        return None  # "the first chat" is a position, not a name: whatsapp_send_at handles it
    result = messaging.type_whatsapp_message(contact, message)
    if "not sent yet" not in result:
        return Response(result)
    return Response(f'I typed "{message}" in the chat with {contact}. Shall I send it?',
                    on_confirm=lambda: Response(messaging.send_typed_whatsapp_message()))


ORDINAL = r"(?P<ord>first|second|third|fourth|fifth|sixth|top|last|1st|2nd|3rd|4th|5th|6th)"
CHAT = r"(?:pinned\s+)?(?:whatsapp\s+)?(?:chat|contact|conversation|person)"


PICK = r"(?:open|go to|select|pick|choose|click(?: on)?|tap(?: on)?)"
IN_WA = r"(?:\s+(?:on|in|from)\s+(?:the\s+)?whatsapp)?"


@skill(rf"^(?:please\s+)?{PICK}\s+(?:the\s+|my\s+)?{ORDINAL}\s+{CHAT}{IN_WA}$",
       rf"^(?:please\s+)?{PICK}\s+(?:the\s+|my\s+)?pinned\s+(?:chat|contact|conversation){IN_WA}$")
def whatsapp_chat_at(m, brain):
    which = (m.groupdict().get("ord") or "first").lower()
    return action(messaging.open_whatsapp_chat_at(messaging.ORDINALS[which]))


@skill(rf"^(?:please\s+)?(?:send|write)\s+(?:a\s+)?(?:message\s+)?to\s+(?:the\s+|my\s+)?{ORDINAL}\s+{CHAT}{WA}\s+"
       rf"{SAYS}\s+(?P<message>.+)$")
def whatsapp_send_at(m, brain):
    opened = messaging.open_whatsapp_chat_at(messaging.ORDINALS[m["ord"].lower()])
    if not opened.startswith("Opened"):
        return Response(opened)
    who = opened.removeprefix("Opened the chat with ").rstrip(".")
    return _typed_then_ask(messaging.type_in_open_chat(m["message"].strip()), m["message"].strip(), who)


@skill(r"^(?:please\s+)?(?:send|reply)\s+(?:a\s+message\s+)?(?:saying\s+)?(?P<message>.+?)\s+"
       r"(?:to|in)\s+(?:this|the current|the open|that)\s+chat$")
def whatsapp_send_here(m, brain):
    return _typed_then_ask(messaging.type_in_open_chat(m["message"].strip()), m["message"].strip(), "this chat")


def _typed_then_ask(result: str, message: str, who: str) -> Response:
    if "not sent yet" not in result:
        return Response(result)
    where = who if who == "this chat" else f"the chat with {who}"
    return Response(f'I typed "{message}" in {where}. Shall I send it?',
                    on_confirm=lambda: Response(messaging.send_typed_whatsapp_message()))


@skill(rf"^(?:please\s+)?open\s+(?:the\s+|my\s+)?(?:whatsapp\s+)?chat\s+(?:with|of|for)\s+(?P<contact>.+?){WA}$",
       rf"^(?:please\s+)?open\s+(?P<contact>.+?)'s\s+chat{WA}$")
def whatsapp_chat(m, brain):
    return action(messaging.open_whatsapp_chat(m["contact"].strip()))


@skill(r"\b(?:check|read|summari[sz]e|go through|any|do i have|show)\b.*\b(?:e-?mails?|mails?|inbox|mailbox|gmail)\b")
def check_email(m, brain):
    # Summaries and searches need the AI; without one, at least say what's unread.
    if brain.fallback is not None:
        return ASK_AI
    if not messaging.email_ready():
        return Response("Email isn't set up yet. In PowerShell, run: python -m jarvis --setup-email")
    return Response(messaging.unread_summary())


@skill(r"^(?:please\s+)?(?:(?:send|write|draft)\s+(?:an?\s+)?e-?mail|e-?mail)\b.*$")
def send_email(m, brain):
    # With an AI: it writes the email and sends it (after a yes). Without: the browser draft skill takes it.
    return ASK_AI if brain.fallback is not None and messaging.email_ready() else None


# --- while working in WhatsApp -------------------------------------------------------------------

def _in_whatsapp() -> bool:
    from .. import screen

    return (screen.working_app() or "").lower() == "whatsapp"


@skill(r"^(?:please\s+)?(?:go to|open|select|pick|choose)\s+(?:the\s+|my\s+)?(?:chat\s+(?:with|of)\s+)?"
       r"(?P<contact>[\w .'-]+?)(?:'s)?(?:\s+chat)?$")
def whatsapp_go_to(m, brain):
    # "go to imsai" while in WhatsApp means that chat, not an app or website called "imsai".
    from .. import computer

    contact = m["contact"].strip()
    key = computer._normalize(contact)
    if not _in_whatsapp() or computer._website_key(key) or key in computer.WINDOWS_APPS \
            or key in ("whatsapp", "the chat", "chat", "it", "this", "that") \
            or re.search(r"\b(?:tab|window|settings|page|folder|file|app)\b", key):
        return None
    try:
        if computer.find_installed_app(key):  # "open photoshop" while in WhatsApp still opens Photoshop
            return None
    except Exception:
        pass
    return action(messaging.open_whatsapp_chat(contact))


@skill(r"^(?:please\s+)?(?:clear|delete|erase|remove|undo)\s+(?:all\s+)?(?:the\s+|this\s+|that\s+|my\s+)?"
       r"(?:text|message|typed text|typed message|draft|words|writing|what i (?:typed|wrote))"
       r"(?:\s+(?:in|from|inside)\s+(?:the\s+|this\s+)?(?:chat|message box|text box|compose box|conversation))?$",
       r"^(?:please\s+)?clear\s+(?:the\s+|this\s+)?(?:chat|message)\s+(?:text|box)$")
def clear_message(m, brain):
    # Only ever the message being typed: never the chat history.
    if not _in_whatsapp():
        return None
    return action(messaging.clear_typed_message())


@skill(r"^(?:please\s+)?(?:change|replace|edit)\s+(?:the\s+|this\s+|that\s+|my\s+)?(?:message|text|it)\s+"
       r"(?:to|with|as)\s+(?P<message>.+)$",
       r"^(?:please\s+)?(?:instead\s+)?(?:say|write)\s+(?P<message>.+?)\s+instead$")
def change_message(m, brain):
    if not _in_whatsapp():
        return None
    result = messaging.replace_typed_message(m["message"].strip())
    return _typed_then_ask(result, m["message"].strip(), "this chat")


@skill(r"^(?:yes,?\s+)?(?:please\s+|okay\s+|ok\s+)?send(?:\s+(?:it|that|the message|this))?(?:\s+now)?(?:\s+please)?$")
def send_now(m, brain):
    # Saying "send it" is the go-ahead itself.
    if not _in_whatsapp():
        return None
    return Response(messaging.send_typed_whatsapp_message())
