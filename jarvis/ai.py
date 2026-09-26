"""Jarvis's conversational brain.

Handles everything the quick built-in commands don't: open conversation,
debate, questions, and multi-step computer tasks through tools (open/close
apps, type, press keys, draft emails, weather).

Three interchangeable brains, all sharing the same personality and tools:
  - Claude (paid API)            ANTHROPIC_API_KEY or "anthropic_api_key" in ~/.jarvis.json
  - Gemini (free tier)           GEMINI_API_KEY or "gemini_api_key" in ~/.jarvis.json   (free_ai.py)
  - Ollama (free, runs locally)  install Ollama and `ollama pull llama3.2`              (free_ai.py)
make_brain() uses every one that's set up, and switches to the next when one
runs out of credit or quota.
"""

from __future__ import annotations

import os
import platform
import time
from datetime import datetime

from . import computer, screen, vision
from .config import Config, load_settings

SYSTEM_PROMPT = """You are {name}, the AI from Iron Man, now running on {title}'s {os} computer. \
You hear {title} through speech recognition and answer through text-to-speech.

Personality: calm, quick, dry British wit, fiercely loyal, and genuinely opinionated. You are a companion, \
not a search engine.
- Hold real opinions and defend them. If {title} says something you think is wrong, or a plan is weak, push \
back and explain why. Argue your corner with good reasons, and concede gracefully when they make the better point.
- Keep the conversation alive: react to what they said, add a thought of your own, and usually finish with a \
question back to them.
- Remember what they told you earlier and bring it back up when it's relevant.

Speaking rules, because every word you write is read aloud:
- Usually one to three short sentences. Go longer only when asked.
- Plain spoken language. No markdown, lists, emoji, code or URLs.
- Speech recognition makes mistakes. If a sentence is garbled, go with the likely meaning or ask.

You can operate the computer with your tools: open apps and websites, close apps, switch windows, type \
into the focused window, press keys, click and scroll, check the weather, and draft emails. You can also see: \
read_screen lists the buttons, links and text of the window in front (fast and exact), and look_at_screen \
shows you a screenshot for anything read_screen misses, like profile pictures, video tiles or images.
- For tasks inside apps and websites, work step by step like a person would: open it, wait for it to \
load, read or look at the screen, click or type, then check the result before moving on. For example, to \
play a film on Hotstar: open the Hotstar search page, wait, read the screen, click the film, click play.
- When {title} asks what's on screen (the Netflix profiles, the accounts in Chrome, an answer on a web \
page), read or look, then tell them. For accounts saved in Chrome, Brave or Edge, use browser_profiles.
- Say briefly what you did. Emails are only drafted; {title} reviews and sends them.
- Never type passwords or payment details and never buy anything; ask {title} to do those parts.
- Windows administrator prompts ("Do you want to allow this app to make changes") are protected by \
Windows and no program can click them; ask {title} to click those.
- If a tool reports a problem, say so plainly.

When {title} simply says your name or hello, you open the conversation: greet them in character, say \
something that fits the time of day, and ask an engaging question or float an idea. Vary your openers.

Current local time: {now}.
Latency-sensitive; begin your visible answer immediately."""

TOOLS = [
    {
        "name": "open_app",
        "description": "Open an application or website by name, e.g. 'chrome', 'terminal', 'notepad', "
                       "'spotify', 'hotstar', 'youtube', 'github.com'. Waits briefly for it to appear.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "App or website name."}},
            "required": ["name"],
        },
    },
    {
        "name": "open_url",
        "description": "Open a specific URL in the default browser, such as a YouTube or Google search "
                       "results URL.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "close_app",
        "description": "Close a running application by name, e.g. 'chrome', 'notepad', 'spotify'.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "type_text",
        "description": "Type text into whichever window or text box currently has keyboard focus.",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "press_keys",
        "description": "Press a key or key combination, e.g. 'enter', 'tab', 'ctrl+t', 'ctrl+l', 'alt+tab', "
                       "'alt+f4'.",
        "input_schema": {
            "type": "object",
            "properties": {"keys": {"type": "string"}},
            "required": ["keys"],
        },
    },
    {
        "name": "compose_email",
        "description": "Open a pre-filled email draft for the user to review and send. Does not send it. "
                       "Write the subject and body yourself from what the user asked for.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address."},
                "subject": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "list_windows",
        "description": "List the titles of all open windows.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "switch_window",
        "description": "Bring an open window to the front, by part of its title (e.g. 'Brave', 'Netflix').",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "read_screen",
        "description": "Read the window in front: its title plus the visible buttons, links, list items, text "
                       "fields and text. Fast and exact. Use it before clicking, and to read answers on pages.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "look_at_screen",
        "description": "Look at a screenshot of the screen and answer a question about it. Use when "
                       "read_screen isn't enough: images, profile pictures, video thumbnails, layout.",
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "What you want to know."}},
            "required": ["question"],
        },
    },
    {
        "name": "click",
        "description": "Click something on screen by its visible name or a short description, e.g. 'Allow', "
                       "'Sign in', 'Sudarsan' (a profile), 'the play button'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "double": {"type": "boolean", "description": "Double-click instead."},
                "right": {"type": "boolean", "description": "Right-click instead."},
            },
            "required": ["target"],
        },
    },
    {
        "name": "scroll",
        "description": "Scroll the window under the mouse.",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down"]},
                "amount": {"type": "string", "enum": ["little", "normal", "lot"]},
            },
            "required": ["direction"],
        },
    },
    {
        "name": "wait",
        "description": "Wait a few seconds, e.g. for a page or app to load or an answer to appear.",
        "input_schema": {
            "type": "object",
            "properties": {"seconds": {"type": "number", "description": "1 to 30."}},
            "required": ["seconds"],
        },
    },
    {
        "name": "browser_profiles",
        "description": "List the profiles (accounts) saved in Chrome, Brave or Edge on this computer.",
        "input_schema": {
            "type": "object",
            "properties": {"browser": {"type": "string", "enum": ["chrome", "brave", "edge"]}},
            "required": ["browser"],
        },
    },
    {
        "name": "open_browser_profile",
        "description": "Open Chrome, Brave or Edge as a specific profile (by profile name or email), "
                       "optionally at a URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "browser": {"type": "string", "enum": ["chrome", "brave", "edge"]},
                "profile": {"type": "string"},
                "url": {"type": "string"},
            },
            "required": ["browser", "profile"],
        },
    },
    {
        "name": "get_weather",
        "description": "Current weather and today's forecast. Leave city empty for the user's location.",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
        },
    },
]

MAX_HISTORY_TURNS = 20
MAX_TOOL_ROUNDS = 25  # multi-step screen tasks need room: open, wait, read, click...


class Assistant:
    """Shared by every brain: personality, tools, conversation memory and availability."""

    label = "AI"

    def __init__(self, config: Config):
        self.config = config
        self.turns: list[list] = []  # each turn: the user message, then assistant/tool messages
        self.unavailable_until = 0.0  # set when out of credit/quota, so make_brain() can switch

    @property
    def available(self) -> bool:
        return time.time() >= self.unavailable_until

    def pause(self, seconds: float, reason: str) -> None:
        print(f"({self.label} unavailable for now: {reason})")
        self.unavailable_until = time.time() + seconds

    def system(self) -> str:
        return SYSTEM_PROMPT.format(
            name=self.config.name,
            title=self.config.user_title,
            os={"Darwin": "Mac", "Windows": "Windows"}.get(platform.system(), platform.system()),
            now=datetime.now().strftime("%A %d %B %Y, %I:%M %p"),
        )

    def history(self) -> list:
        return [m for turn in self.turns for m in turn]

    def remember(self, turn: list) -> None:
        self.turns = (self.turns + [turn])[-MAX_HISTORY_TURNS:]

    def __call__(self, text: str) -> str | None:
        return self._turn(text)

    def start_conversation(self) -> str | None:
        return self._turn(f"{self.config.name}.")

    def _turn(self, text: str) -> str | None:
        raise NotImplementedError

    def run_tool(self, name: str, args: dict) -> tuple[str, bool]:
        """Run one tool call; returns (result text, is_error)."""
        print(f"(tool: {name} {args})")
        try:
            return self._dispatch(name, args or {}), False
        except Exception as e:
            return f"Error: {e}", True

    def _dispatch(self, name: str, args: dict) -> str:
        if name == "open_app":
            return computer.open_app(args["name"])
        if name == "open_url":
            computer.open_url(args["url"])
            return "Opened."
        if name == "close_app":
            return computer.close_app(args["name"])
        if name == "type_text":
            return computer.type_text(args["text"])
        if name == "press_keys":
            return computer.press_keys(args["keys"])
        if name == "compose_email":
            return computer.compose_email(args["to"], args.get("subject", ""), args.get("body", ""),
                                          client=self.config.email_client)
        if name == "list_windows":
            return screen.list_windows()
        if name == "switch_window":
            return screen.switch_to_window(args["name"])
        if name == "read_screen":
            return screen.read_screen()
        if name == "look_at_screen":
            return vision.describe(args.get("question", ""), self.config)
        if name == "click":
            return screen.click(args["target"], bool(args.get("double")), bool(args.get("right")),
                                locate=lambda target: vision.locate(target, self.config))
        if name == "scroll":
            return screen.scroll(args.get("direction", "down"), args.get("amount", "normal"))
        if name == "wait":
            seconds = min(max(float(args.get("seconds", 2)), 0.5), 30)
            time.sleep(seconds)
            return f"Waited {seconds:g} seconds."
        if name == "browser_profiles":
            return computer.list_browser_profiles(args["browser"])
        if name == "open_browser_profile":
            return computer.open_browser_profile(args["browser"], args["profile"], args.get("url", ""))
        if name == "get_weather":
            from .skills import weather

            city = args.get("city") or self.config.city
            place, lat, lon = weather.locate(city)
            return weather.describe(place, weather.forecast(lat, lon, self.config.units), self.config.units)
        raise ValueError(f"unknown tool {name}")


class Claude(Assistant):
    label = "Claude"

    def __init__(self, config: Config, api_key: str | None = None, client=None):
        import anthropic

        super().__init__(config)
        self._anthropic = anthropic
        self.client = client or (anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic())
        # Optional request features. Dropped automatically if the account or model rejects them.
        self._extras = {
            "output_config": {"effort": "low"},
            "betas": ["server-side-fallback-2026-07-01"],
            "fallbacks": "default",
        }

    @property
    def configured(self) -> bool:
        c = self.client
        return bool(c.api_key or c.auth_token or c.credentials)

    def _turn(self, text: str) -> str | None:
        history = self.history()
        turn: list[dict] = [{"role": "user", "content": text}]
        try:
            for _ in range(MAX_TOOL_ROUNDS):
                response = self._create(history + turn)
                if response.stop_reason == "refusal":
                    return "I'm afraid I can't help with that one."
                turn.append({"role": "assistant", "content": response.content})
                tool_uses = [b for b in response.content if b.type == "tool_use"]
                if response.stop_reason != "tool_use" or not tool_uses:
                    break
                turn.append({"role": "user", "content": [self._run_tool(b) for b in tool_uses]})
            else:
                return "That took more steps than I expected, so I stopped. Shall we try it another way?"
        except self._anthropic.AuthenticationError:
            self.pause(3600, "API key not accepted")
            return "My connection to Claude isn't authorised. Please check the API key."
        except self._anthropic.RateLimitError:
            self.pause(60, "rate limited")
            return "I'm being rate limited at the moment. Give me a few seconds."
        except self._anthropic.NotFoundError as e:
            print(f"(Claude error: {error_message(e)})")
            return f"The model {self.config.claude_model} isn't available on your account. Try another claude_model."
        except self._anthropic.APIStatusError as e:
            message = error_message(e)
            print(f"(Claude error {e.status_code}: {message})")
            if "credit balance" in message.lower():
                self.pause(3600, "out of credit")
                return ("Your Anthropic account is out of credit. Add some at platform dot claude dot com, "
                        "under Billing, and I'll be right with you.")
            return f"Claude rejected that request. It said: {message}"
        except self._anthropic.APIConnectionError:
            return "I can't reach my language servers right now. Check the internet connection."

        self.remember(turn)
        answer = " ".join(b.text for b in response.content if b.type == "text").strip()
        return answer or "Done."

    def _create(self, messages: list[dict]):
        request = dict(model=self.config.claude_model, max_tokens=4096, system=self.system(),
                       tools=TOOLS, messages=messages)
        try:
            return self.client.beta.messages.create(**request, **self._extras)
        except self._anthropic.BadRequestError as e:
            message = error_message(e).lower()
            if not self._extras or not any(k in message for k in ("fallback", "beta", "output_config", "effort")):
                raise
            print(f"(Claude rejected optional features, retrying without them: {error_message(e)})")
            self._extras = {}
            return self.client.beta.messages.create(**request)

    def _run_tool(self, block) -> dict:
        result, is_error = self.run_tool(block.name, block.input)
        out = {"type": "tool_result", "tool_use_id": block.id, "content": result}
        if is_error:
            out["is_error"] = True
        return out


def error_message(e) -> str:
    """The human-readable message inside an API error response."""
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
    return str(getattr(e, "message", e))


def make_claude(config: Config) -> Claude | None:
    """Return Claude, or None if the SDK or an API key is missing."""
    api_key = os.environ.get("ANTHROPIC_API_KEY") or load_settings().get("anthropic_api_key")
    try:
        claude = Claude(config, api_key=api_key)
    except Exception:
        return None
    return claude if claude.configured else None


class Failover:
    """Uses the first available brain, moving on to the next when one is out of credit or quota."""

    def __init__(self, brains: list[Assistant]):
        self.brains = brains

    @property
    def names(self) -> str:
        return ", then ".join(b.label for b in self.brains)

    def _ask(self, method: str, *args) -> str | None:
        answer = None
        for brain in self.brains:
            if not brain.available:
                continue
            answer = getattr(brain, method)(*args)
            if brain.available:
                return answer
            # This brain just ran out; try the next one with the same request.
        return answer or "All my AI brains are unavailable right now. Try again in a little while."

    def __call__(self, text: str) -> str | None:
        return self._ask("__call__", text)

    def start_conversation(self) -> str | None:
        return self._ask("start_conversation")


def make_brain(config: Config) -> Failover | None:
    """Every brain that's set up, preferred one first. None if there are none."""
    from .free_ai import make_gemini, make_ollama

    makers = {"claude": make_claude, "gemini": make_gemini, "ollama": make_ollama}
    order = ["gemini", "ollama", "claude"]  # free first; Claude only if it's set up and has credit
    preferred = str(config.ai_provider).lower()
    if preferred in makers:
        order.remove(preferred)
        order.insert(0, preferred)
    brains = [b for b in (makers[name](config) for name in order) if b is not None]
    return Failover(brains) if brains else None
