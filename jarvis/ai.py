"""Claude: Jarvis's conversational brain.

Handles everything the quick built-in commands don't: open conversation,
debate, questions, and multi-step computer tasks through tools (open/close
apps, type, press keys, draft emails, weather).

Enabled when the `anthropic` package is installed and an API key is available,
either as the ANTHROPIC_API_KEY environment variable or "anthropic_api_key"
in ~/.jarvis.json.
"""

from __future__ import annotations

import os
import platform
from datetime import datetime

from . import computer
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

You can operate the computer with your tools: open apps and websites, close apps, type into the focused \
window, press keys, check the weather, and draft emails. When {title} asks for something like that, use \
the tools, then say briefly what you did. Emails are only drafted; {title} reviews and sends them. \
If a tool reports a problem, say so plainly.

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
        "name": "get_weather",
        "description": "Current weather and today's forecast. Leave city empty for the user's location.",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
        },
    },
]

MAX_HISTORY_TURNS = 20
MAX_TOOL_ROUNDS = 8


class Claude:
    def __init__(self, config: Config, api_key: str | None = None, client=None):
        import anthropic

        self._anthropic = anthropic
        self.client = client or (anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic())
        self.config = config
        self.turns: list[list[dict]] = []  # each turn: user message, then assistant/tool messages
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

    def _system(self) -> str:
        return SYSTEM_PROMPT.format(
            name=self.config.name,
            title=self.config.user_title,
            os={"Darwin": "Mac", "Windows": "Windows"}.get(platform.system(), platform.system()),
            now=datetime.now().strftime("%A %d %B %Y, %I:%M %p"),
        )

    def __call__(self, text: str) -> str | None:
        return self._turn(text)

    def start_conversation(self) -> str | None:
        return self._turn(f"{self.config.name}.")

    def _turn(self, text: str) -> str | None:
        history = [m for turn in self.turns for m in turn]
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
            return "My connection to Claude isn't authorised. Please check the API key."
        except self._anthropic.RateLimitError:
            return "I'm being rate limited at the moment. Give me a few seconds."
        except self._anthropic.NotFoundError as e:
            print(f"(Claude error: {error_message(e)})")
            return f"The model {self.config.claude_model} isn't available on your account. Try another claude_model."
        except self._anthropic.APIStatusError as e:
            message = error_message(e)
            print(f"(Claude error {e.status_code}: {message})")
            if "credit balance" in message.lower():
                return ("Your Anthropic account is out of credit. Add some at platform dot claude dot com, "
                        "under Billing, and I'll be right with you.")
            return f"Claude rejected that request. It said: {message}"
        except self._anthropic.APIConnectionError:
            return "I can't reach my language servers right now. Check the internet connection."

        self.turns = (self.turns + [turn])[-MAX_HISTORY_TURNS:]
        answer = " ".join(b.text for b in response.content if b.type == "text").strip()
        return answer or "Done."

    def _create(self, messages: list[dict]):
        request = dict(model=self.config.claude_model, max_tokens=4096, system=self._system(),
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
        args = block.input or {}
        print(f"(tool: {block.name} {args})")
        try:
            result = self._dispatch(block.name, args)
            return {"type": "tool_result", "tool_use_id": block.id, "content": result}
        except Exception as e:
            return {"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {e}", "is_error": True}

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
        if name == "get_weather":
            from .skills import weather

            city = args.get("city") or self.config.city
            place, lat, lon = weather.locate(city)
            return weather.describe(place, weather.forecast(lat, lon, self.config.units), self.config.units)
        raise ValueError(f"unknown tool {name}")


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
