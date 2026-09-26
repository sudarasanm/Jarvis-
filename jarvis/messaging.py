"""Email (Gmail over IMAP/SMTP) and WhatsApp messages.

Email works through the mailbox directly, not by clicking around the Gmail website: reading is reliable and
never marks anything as read. It needs a Google "app password", set up once with
`python -m jarvis --setup-email`; the password is kept in Windows Credential Manager (via `keyring`), not in
a file.

Sending anything (an email, a WhatsApp message) is always a two-step affair: Jarvis prepares it, reads it back,
and only sends after the user says yes.
"""

from __future__ import annotations

import email
import email.policy
import html
import imaplib
import re
import smtplib
import time
from email.message import EmailMessage
from email.utils import parseaddr

from . import computer, screen
from .config import load_settings, profile, save_setting

IMAP_HOST = "imap.gmail.com"
SMTP_HOST = "smtp.gmail.com"
KEYRING_SERVICE = "jarvis-email"


class EmailNotSetUp(RuntimeError):
    pass


# --- email: setup ----------------------------------------------------------------------------------

def email_account() -> str | None:
    return load_settings().get("email_account") or profile().get("email")


def _password(account: str) -> str | None:
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, account)
    except Exception:
        return None


def email_ready() -> bool:
    account = email_account()
    return bool(account and _password(account))


def setup_email_interactive() -> None:
    """Ask for the Gmail address and app password in the console, test them, and store them safely."""
    import getpass

    import keyring

    print("Email setup for Jarvis (Gmail).\n")
    print("1. Turn on 2-Step Verification for your Google account, if it isn't already.")
    print("2. Open https://myaccount.google.com/apppasswords , create an app password called 'Jarvis',")
    print("   and copy the 16-letter code it shows.\n")
    default = email_account() or ""
    account = input(f"Gmail address{f' [{default}]' if default else ''}: ").strip() or default
    password = getpass.getpass("App password (hidden as you type): ").replace(" ", "").strip()
    try:
        conn = imaplib.IMAP4_SSL(IMAP_HOST)
        conn.login(account, password)
        conn.logout()
    except Exception as e:
        print(f"\nThat didn't work: {e}\nCheck the address and the app password, then try again.")
        return
    keyring.set_password(KEYRING_SERVICE, account, password)
    save_setting("email_account", account)
    print(f"\nDone. Jarvis can now read and (with your yes) send email as {account}.")


def _login_imap():
    account = email_account()
    password = _password(account) if account else None
    if not password:
        raise EmailNotSetUp("Email isn't set up yet. In PowerShell run: .venv\\Scripts\\python -m jarvis --setup-email")
    conn = imaplib.IMAP4_SSL(IMAP_HOST, timeout=30)
    conn.login(account, password)
    return conn


# --- email: reading --------------------------------------------------------------------------------

FILTERS = {
    "unread": "is:unread",
    "important": "is:important is:unread",
    "today": "newer_than:1d",
    "all": "",
}


def _text_of(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        text = part.get_content()
    except Exception:
        return ""
    if part.get_content_type() == "text/html":
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
        text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return " ".join(text.split())


def _sender(msg) -> str:
    name, address = parseaddr(msg.get("From", ""))
    return name or address


def fetch_emails(filter: str = "unread", limit: int = 10) -> tuple[int, list[dict]]:
    """(how many match, newest `limit` of them as dicts: id, sender, subject, date, preview). Stays unread."""
    query = FILTERS.get(filter.lower().strip(), filter) if filter else ""
    conn = _login_imap()
    try:
        conn.select("INBOX", readonly=True)
        if query:
            status, data = conn.uid("SEARCH", "X-GM-RAW", f'"{query}"')
        else:
            status, data = conn.uid("SEARCH", None, "ALL")
        uids = (data[0] or b"").split() if status == "OK" else []
        rows = []
        for uid in reversed(uids[-max(1, min(limit, 25)):]):
            status, parts = conn.uid("FETCH", uid, "(BODY.PEEK[])")  # PEEK: stays unread
            raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
            if not raw:
                continue
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            rows.append({"id": uid.decode(), "sender": _sender(msg), "subject": str(msg.get("Subject", "(no subject)")),
                         "date": str(msg.get("Date", ""))[:16], "preview": _text_of(msg)[:200]})
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return len(uids), rows


def list_emails(filter: str = "unread", limit: int = 10) -> str:
    """Newest matching emails: sender, subject, when, and a short preview. `filter` is 'unread', 'important',
    'today', 'all', or any Gmail search ("subject:application", "from:hr@company.com has:attachment")."""
    total, rows = fetch_emails(filter, limit)
    if not rows:
        return f"No emails match {filter!r}."
    lines = [f"[{r['id']}] From {r['sender']}: {r['subject']} ({r['date']}) - {r['preview']}" for r in rows]
    return f"{total} matching email{'s' if total != 1 else ''}; newest {len(rows)}:\n" + "\n".join(lines)


def unread_summary(limit: int = 5) -> str:
    """Spoken, no AI needed: how many unread, and who the newest are from."""
    total, rows = fetch_emails("unread", limit)
    if not total:
        return "No unread emails. Inbox zero, or near enough."
    newest = "; ".join(f"{r['sender']} about {r['subject']}" for r in rows)
    return f"You have {total} unread email{'s' if total != 1 else ''}. The newest: {newest}."


def read_email(uid: str) -> str:
    """The full text of one email (by the number in brackets from list_emails), without marking it read."""
    conn = _login_imap()
    try:
        conn.select("INBOX", readonly=True)
        status, parts = conn.uid("FETCH", str(uid).strip("[] "), "(BODY.PEEK[])")
        raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    if not raw:
        return f"I couldn't find email {uid}."
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    body = _text_of(msg)
    if len(body) > 4000:
        body = body[:4000] + " ... (cut)"
    return f"From: {msg.get('From')}\nTo: {msg.get('To')}\nDate: {msg.get('Date')}\nSubject: {msg.get('Subject')}\n\n{body}"


# --- email: sending (after a yes) ------------------------------------------------------------------

def send_email(to: str, subject: str, body: str) -> str:
    account = email_account()
    password = _password(account) if account else None
    if not password:
        raise EmailNotSetUp("Email isn't set up yet. In PowerShell run: .venv\\Scripts\\python -m jarvis --setup-email")
    to = computer.spoken_email(to) if "@" not in to else to.strip()
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = account, to, subject
    msg.set_content(body)
    with smtplib.SMTP_SSL(SMTP_HOST, 465, timeout=30) as smtp:
        smtp.login(account, password)
        smtp.send_message(msg)
    return f"Sent the email to {to}."


# --- WhatsApp --------------------------------------------------------------------------------------

def _whatsapp_window():
    wins = screen.matching_windows("whatsapp")
    return wins[0] if wins else None


def open_whatsapp_chat(contact: str) -> str:
    """Open WhatsApp and the chat with `contact` (as it appears in WhatsApp). Doesn't type or send anything."""
    import pyautogui

    if screen.SYSTEM != "Windows":
        return "WhatsApp control only works on Windows for now."
    win = _whatsapp_window()
    if win is None:
        computer.open_app("whatsapp")
        for _ in range(20):
            time.sleep(0.5)
            win = _whatsapp_window()
            if win is not None:
                break
    if win is None:
        return "I couldn't open WhatsApp."
    screen.activate(win)
    screen.remember_app("whatsapp")
    pyautogui.hotkey("ctrl", "f")  # search chats
    time.sleep(0.4)
    pyautogui.hotkey("ctrl", "a")
    computer.type_text(contact)
    time.sleep(1.5)
    element = None
    try:
        element = screen.find_element(contact, [e for e in screen.screen_elements() if e.kind == "ListItem"])
    except Exception:
        pass
    if element is not None:
        screen.click_point(element.x, element.y)
    else:  # first search result
        pyautogui.press("down")
        pyautogui.press("enter")
    time.sleep(0.8)
    return f"Opened the chat with {contact}."


def type_whatsapp_message(contact: str, message: str) -> str:
    """Open the chat and type the message, WITHOUT sending it."""
    result = open_whatsapp_chat(contact)
    if not result.startswith("Opened"):
        return result
    try:
        box = screen.find_element("type a message", screen.screen_elements())
        if box is not None:
            screen.click_point(box.x, box.y)
    except Exception:
        pass
    computer.type_text(message)
    return f"Typed the message in the chat with {contact}; not sent yet."


def send_typed_whatsapp_message() -> str:
    import pyautogui

    win = _whatsapp_window()
    if win is None:
        return "WhatsApp isn't open any more, so nothing was sent."
    screen.activate(win)
    pyautogui.press("enter")
    return "Sent."
