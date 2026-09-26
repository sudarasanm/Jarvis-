"""Claude fallback for anything Jarvis can't handle natively.

Enabled when the `anthropic` package is installed and credentials are
available (e.g. ANTHROPIC_API_KEY). Keeps a short conversation history so
follow-up questions work.
"""

from __future__ import annotations

from .config import Config

SYSTEM_PROMPT = """You are {name}, a witty, loyal voice assistant in the spirit of J.A.R.V.I.S. from Iron Man. \
Address the user as "{title}". Your replies are spoken aloud by a text-to-speech engine, so:
- Answer in one to three short sentences unless the user asks for more.
- Use plain spoken language: no markdown, lists, code blocks, URLs or emoji.
- Be dryly humorous when it fits, but always helpful.
Latency-sensitive; begin your visible answer immediately."""

MAX_HISTORY_TURNS = 10


class ClaudeFallback:
    def __init__(self, config: Config):
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.config = config
        self.system = SYSTEM_PROMPT.format(name=config.name, title=config.user_title)
        self.history: list[dict] = []

    def __call__(self, text: str) -> str | None:
        messages = self.history + [{"role": "user", "content": text}]
        try:
            response = self.client.beta.messages.create(
                model=self.config.claude_model,
                max_tokens=1024,
                system=self.system,
                messages=messages,
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except self._anthropic.AuthenticationError:
            return "My connection to Claude isn't authorised. Please check the API key."
        except self._anthropic.RateLimitError:
            return "I'm being rate limited at the moment. Give me a few seconds."
        except self._anthropic.APIStatusError as e:
            return f"Claude returned an error, status {e.status_code}."
        except self._anthropic.APIConnectionError:
            return "I can't reach my language servers right now. Check the internet connection."
        except Exception as e:
            print(f"(Claude error: {e!r})")
            return "Something went wrong while I was thinking about that."

        if response.stop_reason == "refusal":
            return "I'm afraid I can't help with that one."
        answer = " ".join(b.text for b in response.content if b.type == "text").strip()
        if not answer:
            return None
        self.history = (messages + [{"role": "assistant", "content": answer}])[-MAX_HISTORY_TURNS * 2:]
        return answer


def make_fallback(config: Config):
    """Return a ClaudeFallback, or None if the SDK or credentials are missing."""
    try:
        fallback = ClaudeFallback(config)
    except Exception:
        return None
    client = fallback.client
    if not (client.api_key or client.auth_token or client.credentials):
        return None
    return fallback
