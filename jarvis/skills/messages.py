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


@skill(rf"^(?:please\s+)?(?:open|go to)\s+(?:the\s+|my\s+)?{ORDINAL}\s+{CHAT}{WA}$")
def whatsapp_chat_at(m, brain):
    return action(messaging.open_whatsapp_chat_at(messaging.ORDINALS[m["ord"].lower()]))


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
