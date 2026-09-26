import sys
import types
from email.message import EmailMessage

import pytest

from jarvis import ai, computer, messaging, screen
from jarvis.brain import Brain
from jarvis.config import Config, save_setting


def make_mail(uid, sender, subject, body, unread=True):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"], msg["Date"] = sender, "me@gmail.com", subject, "Sat, 26 Sep 2026 10:00:00 +0530"
    msg.set_content(body)
    return {"uid": uid, "raw": msg.as_bytes(), "unread": unread}


class FakeIMAP:
    mailbox = []
    fetched = []

    def __init__(self, host, timeout=None):
        assert host == "imap.gmail.com"

    def login(self, user, password):
        assert (user, password) == ("me@gmail.com", "app-password")

    def select(self, box, readonly=False):
        assert readonly  # never changes anything
        return "OK", [b"3"]

    def uid(self, command, *args):
        if command == "SEARCH":
            wanted = [m for m in self.mailbox if m["unread"]] if args and "is:unread" in args[-1] else self.mailbox
            return "OK", [" ".join(str(m["uid"]) for m in wanted).encode()]
        if command == "FETCH":
            FakeIMAP.fetched.append(args[1])
            uid = int(args[0])
            m = next((m for m in self.mailbox if m["uid"] == uid), None)
            return "OK", [(f"{uid} (UID {uid} BODY[] {{1}}".encode(), m["raw"]), b")"] if m else [None]

    def logout(self):
        pass


@pytest.fixture
def gmail(monkeypatch):
    FakeIMAP.mailbox = [
        make_mail(1, "Newsletter <news@shop.com>", "Big sale", "50% off everything", unread=False),
        make_mail(2, "Priya HR <hr@acme.com>", "Your application for Data Analyst", "We'd like to schedule an interview."),
        make_mail(3, "Amma <amma@gmail.com>", "Dinner", "Come home by 8."),
    ]
    FakeIMAP.fetched = []
    monkeypatch.setattr(messaging.imaplib, "IMAP4_SSL", FakeIMAP)
    store = {("jarvis-email", "me@gmail.com"): "app-password"}
    keyring = types.ModuleType("keyring")
    keyring.get_password = lambda service, user: store.get((service, user))
    keyring.set_password = lambda service, user, pw: store.__setitem__((service, user), pw)
    monkeypatch.setitem(sys.modules, "keyring", keyring)
    save_setting("email_account", "me@gmail.com")
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            assert (host, port) == ("smtp.gmail.com", 465)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, password):
            assert password == "app-password"

        def send_message(self, msg):
            sent.append(msg)

    monkeypatch.setattr(messaging.smtplib, "SMTP_SSL", FakeSMTP)
    return sent


def test_list_and_read_emails_without_marking_them_read(gmail):
    text = messaging.list_emails("unread")
    assert text.startswith("2 matching emails; newest 2:")
    assert "[3] From Amma: Dinner" in text and "[2] From Priya HR: Your application for Data Analyst" in text
    assert "Big sale" not in text
    assert all("PEEK" in f for f in FakeIMAP.fetched)
    assert "We'd like to schedule an interview." in messaging.read_email("2")
    assert messaging.unread_summary() == ("You have 2 unread emails. The newest: Amma about Dinner; "
                                          "Priya HR about Your application for Data Analyst.")


def test_email_not_set_up(monkeypatch):
    keyring = types.ModuleType("keyring")
    keyring.get_password = lambda service, user: None
    monkeypatch.setitem(sys.modules, "keyring", keyring)
    assert not messaging.email_ready()
    with pytest.raises(messaging.EmailNotSetUp):
        messaging.list_emails()
    assert "--setup-email" in Brain(Config()).handle("check my email").text


def test_ai_sends_exactly_the_confirmed_draft(gmail):
    brain = ai.Assistant(Config(user_title="Sudarsan"))
    brain.user_text = "email priya that I'm available tomorrow"
    text, _ = brain.run_tool("email_send", {"to": "hr@acme.com", "subject": "Interview", "body": "I'm free tomorrow."})
    assert "NOT sent" in text and gmail == []
    # Same turn: the model can't send without the user's yes.
    assert brain.run_tool("email_send", {"to": "x", "subject": "x", "body": "x", "confirmed": True})[0].startswith("Not sent")
    brain.memory.add("email priya that I'm available tomorrow", "Draft to hr@acme.com: I'm free tomorrow. Send?", [])
    brain.user_text = "yes send it"
    # Even if the model passes different text now, the approved draft is what goes out.
    assert brain.run_tool("email_send", {"to": "evil@x.com", "subject": "x", "body": "x", "confirmed": True})[0] == \
        "Sent the email to hr@acme.com."
    assert gmail[0]["To"] == "hr@acme.com" and gmail[0].get_content().strip() == "I'm free tomorrow."


def test_email_requests_go_to_the_ai_when_available(gmail):
    asked = []
    b = Brain(Config(), fallback=lambda text: asked.append(text) or "You have two unread emails...")
    b.handle("check my mailbox is there any application received")
    b.handle("send an email to priya saying thanks")
    assert len(asked) == 2


def test_email_without_ai_reads_the_unread_summary(gmail):
    assert Brain(Config()).handle("do I have any new emails").text.startswith("You have 2 unread emails.")


@pytest.fixture
def whatsapp(monkeypatch):
    log = []
    win = types.SimpleNamespace(title="WhatsApp", _hWnd=3, visible=True, isMinimized=False,
                                activate=lambda: log.append("activate"))
    monkeypatch.setattr(screen, "SYSTEM", "Windows")
    monkeypatch.setattr(screen, "_windows", lambda: [win])
    monkeypatch.setattr(screen.time, "sleep", lambda s: None)
    monkeypatch.setattr(messaging.time, "sleep", lambda s: None)
    monkeypatch.setattr(screen, "screen_elements", lambda: [
        screen.Element("ListItem", "Amma, Come home by 8", 200, 150),
        screen.Element("Edit", "Type a message", 700, 900)])
    monkeypatch.setattr(screen, "click_point", lambda x, y, *a: log.append(("click", x, y)))
    monkeypatch.setattr(computer, "type_text", lambda text: log.append(("type", text)) or "Done.")
    monkeypatch.setitem(sys.modules, "pyautogui", types.SimpleNamespace(
        hotkey=lambda *k: log.append(("hotkey",) + k), press=lambda k: log.append(("press", k))))
    return log


def test_whatsapp_message_is_typed_then_sent_only_after_yes(whatsapp):
    b = Brain(Config())
    r = b.handle("send a whatsapp message to Amma saying I'll be late tonight")
    assert r.text == 'I typed "I\'ll be late tonight" in the chat with Amma. Shall I send it?'
    assert ("hotkey", "ctrl", "f") in whatsapp and ("type", "Amma") in whatsapp
    assert ("click", 200, 150) in whatsapp and ("type", "I'll be late tonight") in whatsapp
    assert ("press", "enter") not in whatsapp  # not sent yet
    assert b.handle("yes").text == "Sent."
    assert whatsapp[-1] == ("press", "enter")


def test_whatsapp_declined(whatsapp):
    b = Brain(Config())
    b.handle("whatsapp Amma saying on my way")
    assert "Cancelled" in b.handle("no").text
    assert ("press", "enter") not in whatsapp


def test_ai_whatsapp_needs_yes(whatsapp):
    brain = ai.Assistant(Config())
    brain.user_text = "tell amma on whatsapp I'm on my way"
    text, _ = brain.run_tool("whatsapp_message", {"contact": "Amma", "message": "On my way"})
    assert "not sent yet" in text
    assert brain.run_tool("whatsapp_message", {"contact": "Amma", "message": "x", "confirmed": True})[0].startswith("Not sent")
    brain.memory.add("tell amma", "Typed it. Send?", [])
    brain.user_text = "yes"
    assert brain.run_tool("whatsapp_message", {"contact": "Amma", "message": "x", "confirmed": True})[0] == "Sent."
