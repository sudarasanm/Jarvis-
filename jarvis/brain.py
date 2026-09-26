"""The brain: turns a sentence into an action.

Each skill registers regex patterns with the ``@skill`` decorator. The first
pattern that matches wins; anything unmatched goes to the fallback (Claude,
if configured).
"""

from __future__ import annotations

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


# A handler may return None to pass, letting later skills or Claude handle the request.
Handler = Callable[[re.Match, "Brain"], "Response | None"]

_SKILLS: list[tuple[re.Pattern, Handler]] = []


def skill(*patterns: str):
    """Register a handler for one or more regex patterns (matched case-insensitively)."""

    def decorator(fn: Handler) -> Handler:
        for p in patterns:
            _SKILLS.append((re.compile(p, re.IGNORECASE), fn))
        return fn

    return decorator


YES = re.compile(r"^(yes|yeah|yep|sure|confirm|do it|go ahead|affirmative|ok(ay)?)\b", re.I)
NO = re.compile(r"^(no|nope|cancel|stop|never ?mind|abort|negative)\b", re.I)


class Brain:
    def __init__(self, config: Config | None = None, fallback: Callable[[str], str | None] | None = None):
        self.config = config or Config()
        self.fallback = fallback
        self._pending: Callable[[], Response] | None = None
        self._pending_reply: Callable[[str], Response] | None = None
        from . import skills  # noqa: F401  (importing registers every skill)

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
            response = self._dispatch(text.strip().rstrip(".!?"), confirm, reply)
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
                if response is not None:
                    return response

        if self.fallback is not None:
            answer = self.fallback(text)
            if answer:
                return Response(answer)
        return Response(f"I'm afraid I don't know how to do that yet, {self.title}.")
