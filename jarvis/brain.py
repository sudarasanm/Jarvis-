"""The brain: turns a sentence into an action.

Each skill registers regex patterns with the ``@skill`` decorator. The first
pattern that matches wins; anything unmatched goes to the fallback (Claude,
if configured).
"""

from __future__ import annotations

import queue
import re
from dataclasses import dataclass
from typing import Callable

from .config import Config


@dataclass
class Response:
    text: str
    # If set, Jarvis asks for a yes/no and runs this on "yes".
    on_confirm: Callable[[], "Response"] | None = None
    # If set, Jarvis asked a question and passes the next thing you say to this.
    on_reply: Callable[[str], "Response"] | None = None
    # End the conversation: go back to waiting for "Hey Jarvis".
    sleep: bool = False
    # Quit the program entirely.
    exit: bool = False
    # An instruction that worked: just do it, don't talk about it (see the quiet_actions setting).
    quiet: bool = False


class Quiet(str):
    """An AI reply that only confirms an action ("Done"), so it needn't be spoken."""


# How successful instructions report back; failures ("I couldn't find...") are always spoken.
OK_PREFIXES = ("Opening", "Opened", "Closed", "Closing", "Switched", "Clicked", "Double-clicked", "Right-clicked",
               "Scrolled", "Done", "Dismissed", "Now on", "Brought back", "Volume", "Muted", "Sound's back",
               "Brightness set", "Reloaded", "Went ", "Typed", "Playing", "Here's what I found", "Pressed", "Cleared")


def action(text: str) -> "Response":
    """The Response for an instruction: silent if it worked, spoken if it didn't."""
    return Response(text, quiet=text.startswith(OK_PREFIXES))


# A handler may return None to pass to later skills, or ASK_AI to hand the request straight to the AI
# (it needs the conversation's context, e.g. "close it").
Handler = Callable[[re.Match, "Brain"], "Response | None"]
ASK_AI = object()

_SKILLS: list[tuple[re.Pattern, Handler]] = []


def skill(*patterns: str):
    """Register a handler for one or more regex patterns (matched case-insensitively)."""

    def decorator(fn: Handler) -> Handler:
        for p in patterns:
            _SKILLS.append((re.compile(p, re.IGNORECASE), fn))
        return fn

    return decorator


# What speech recognition typically hears instead of names Jarvis needs. Fixed before anything acts on it.
CORRECTIONS = [
    (r"\b(?:chachi|chachy|chatchi|chaji|chad ?g|chat ?g|cha) ?(?:p|pee|pt|bt|gpt|gbt|jeep(?:ee)?)\b"
     r"|\bchat ?g ?p ?t\b|\bchad ?gpt\b", "ChatGPT"),
    (r"\b(?:o|a)ll?amm?a\b|\bolama\b|\bo lama\b|\bollama\b", "Ollama"),
    (r"\bhot ?star\b", "Hotstar"),
    (r"\b(?:pind|pint|pinch|pinned)\b(?=\s+(?:chat|contact|conversation|message))", "pinned"),
    (r"^((?:please\s+)?(?:open|close|launch|start|switch to|go to)\s+(?:the\s+)?)(?:string|stream|steem|stim|stean|steem)\b",
     r"\1Steam"),
    (r"\bin (?:the )?(?:string|stream)\b", "in Steam"),
    (r"\bnet ?flix\b", "Netflix"),
    (r"\b(?:ip|a p i|app|api) keys\b", "API keys"),
    (r"\b(?:ip|a p i|api) key\b", "API key"),
    (r"\bmicrosoft edges\b", "Microsoft Edge"),
    (r"\bsystem (?:citizens|settle?ings|setting)\b", "system settings"),
    (r"\bg ?mail\b", "Gmail"),
    (r"\byou ?tube\b", "YouTube"),
]


LONG_NUMBER = re.compile(r"\b\d(?:[ -]?\d){11,18}\b")  # card-like numbers
SPOKEN_SECRET = re.compile(r"(\b(?:pass\s?word|passcode|pin)\b\s*(?:is|as|number is|:)?\s*).+", re.I)


def redact(text: str) -> str:
    """For printing what was heard: hide passwords and card-like numbers."""
    return LONG_NUMBER.sub("****", SPOKEN_SECRET.sub(r"\1****", text))


def fix_transcript(text: str) -> str:
    for pattern, replacement in CORRECTIONS:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return text


# Words a spoken command or question typically starts with.
COMMAND_START = (r"(?:what|what's|whats|how|who|when|why|which|can|could|would|will|please|open|close|launch|"
                 r"tell|say|play|type|press|search|write|send|turn|shut|restart|lock|call|set|show|give|"
                 r"is|are|do|does|let's|i)\b")

YES = re.compile(r"^(yes|yeah|yep|sure|confirm|do it|go ahead|affirmative|ok(ay)?)\b", re.I)
NO = re.compile(r"^(no|nope|cancel|stop|never ?mind|abort|negative)\b", re.I)


class Brain:
    def __init__(self, config: Config | None = None, fallback: Callable[[str], str | None] | None = None):
        self.config = config or Config()
        self.fallback = fallback
        self._pending: Callable[[], Response] | None = None
        self._pending_reply: Callable[[str], Response] | None = None
        # Things to say when they happen in the background (e.g. an install finishing).
        self._notices: "queue.Queue[str]" = queue.Queue()
        from . import skills  # noqa: F401  (importing registers every skill)

        if hasattr(fallback, "set_notifier"):
            fallback.set_notifier(self.notify)

    def notify(self, text: str) -> None:
        """Queue something for Jarvis to say at the next chance (safe to call from any thread)."""
        self._notices.put(text)

    def pop_notices(self) -> list[str]:
        out = []
        while True:
            try:
                out.append(self._notices.get_nowait())
            except queue.Empty:
                return out

    @property
    def awaiting_reply(self) -> bool:
        """True when Jarvis just asked a question and expects an answer without the wake word."""
        return self._pending is not None or self._pending_reply is not None

    @property
    def title(self) -> str:
        return self.config.user_title

    def strip_wake_word(self, text: str) -> tuple[bool, str]:
        """Return (was_addressed, command) for text like 'hey jarvis what time is it'."""
        names = "|".join(re.escape(w) for w in self.config.wake_words)
        m = re.search(rf"\b(?:{names})\b[\s,.!?]*", text, re.I)
        if not m and self.config.wake_word == "jarvis":
            # Speech recognition often hears "Jarvis" as "where is". Only trust that at the start of a
            # sentence and followed by a command ("where is what's the time"), not "where is my phone".
            m = re.match(rf"\s*(?:hey\s+|ok\s+)?(?:where is|where's|wear is|jar is|java is)[\s,]+(?={COMMAND_START})",
                         text, re.I)
        if not m:
            return False, text.strip()
        after = text[m.end():].strip()
        if after:
            return True, after
        # Name at the end ("goodbye Jarvis", "thank you Jarvis"): use what came before it.
        before = re.sub(r"^\s*(hey|hi|hello|ok|okay|yo)\b[\s,]*", "", text[:m.start()], flags=re.I)
        return True, before.strip(" ,.!?")

    def handle(self, text: str) -> Response:
        confirm, reply = self._pending, self._pending_reply
        self._pending = self._pending_reply = None
        try:
            response = self._dispatch(fix_transcript(text.strip().rstrip(".!?")), confirm, reply)
        except ModuleNotFoundError as e:
            print(f"(error: {e!r})")
            response = Response(f"I'm missing the {e.name} package, {self.title}. "
                                "Please run the installer again, or pip install -r requirements.txt.")
        except Exception as e:  # a broken skill should never take Jarvis down
            print(f"(error: {e!r})")
            response = Response(f"Apologies, {self.title}, something went wrong there.")
        self._pending, self._pending_reply = response.on_confirm, response.on_reply
        return response

    def _dispatch(self, text: str, confirm, reply) -> Response:
        if not text:
            return Response(f"Yes, {self.title}?", on_confirm=confirm, on_reply=reply)

        if reply is not None:
            return reply(text)

        if confirm is not None:
            if YES.match(text):
                return confirm()
            if NO.match(text):
                return Response(f"Very well, {self.title}. Cancelled.")
            # Anything else: drop the pending action and treat as a new command.

        for pattern, handler in _SKILLS:
            match = pattern.search(text)
            if match:
                response = handler(match, self)
                if response is ASK_AI:
                    break
                if response is not None:
                    return response

        if self.fallback is not None:
            answer = self.fallback(LONG_NUMBER.sub("[a long number]", text))  # card numbers never leave here
            if answer:
                return Response(answer, quiet=isinstance(answer, Quiet))
        return Response(f"I'm afraid I don't know how to do that yet, {self.title}.")
