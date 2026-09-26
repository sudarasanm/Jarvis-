"""Let the AI look at the screen: answer questions about a screenshot, and find where something is.

Uses Gemini (free tier) when a Gemini key is set up, otherwise an Ollama vision model if one is
configured ("ollama_vision_model", e.g. "llama3.2-vision" or "qwen2.5vl"). Only Gemini can point
at things precisely enough to click them.
"""

from __future__ import annotations

import base64
import json
import re

from . import screen
from .config import Config

DESCRIBE_PROMPT = """This is a screenshot of the user's screen. {question}
Answer for a voice assistant: be concise and specific, and read out names exactly as shown."""

LOCATE_PROMPT = """This is a screenshot of the user's screen. Find this on-screen element: "{target}".
Reply with JSON only: {{"found": true, "box_2d": [ymin, xmin, ymax, xmax]}} using coordinates
normalised to 0-1000, or {{"found": false}} if it isn't visible."""


class VisionUnavailable(RuntimeError):
    pass


def _gemini(config: Config, prompt: str, image: bytes, json_reply: bool = False) -> str:
    from .free_ai import GeminiUnavailable, gemini_generate

    body = {"contents": [{"role": "user", "parts": [
        {"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(image).decode()}},
        {"text": prompt},
    ]}]}
    if json_reply:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    try:
        data = gemini_generate(config, body)
    except GeminiUnavailable as e:
        raise VisionUnavailable("I can't see the screen right now: Gemini's free limit is used up "
                                f"for about {e.seconds:.0f} seconds.") from None
    parts = data["candidates"][0]["content"]["parts"]
    return " ".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


def _ollama(config: Config, prompt: str, image: bytes) -> str:
    from .free_ai import post_json

    data = post_json(f"{config.ollama_url}/api/chat", {
        "model": config.ollama_vision_model,
        "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(image).decode()]}],
        "stream": False,
    })
    return (data.get("message", {}).get("content") or "").strip()


def describe(question: str, config: Config) -> str:
    """Answer a question about what's on screen right now."""
    from .free_ai import gemini_key

    image, _ = screen.screenshot_jpeg()
    prompt = DESCRIBE_PROMPT.format(question=question or "Describe what's on screen.")
    if gemini_key():
        return _gemini(config, prompt, image)
    if config.ollama_vision_model:
        return _ollama(config, prompt, image)
    raise VisionUnavailable("Looking at the screen needs a Gemini key (free) or an Ollama vision model.")


def locate(target: str, config: Config) -> tuple[int, int] | None:
    """Screen coordinates of the centre of `target`, or None if it isn't visible."""
    from .free_ai import gemini_key

    if not gemini_key():
        return None
    image, (width, height) = screen.screenshot_jpeg()
    reply = _gemini(config, LOCATE_PROMPT.format(target=target), image, json_reply=True)
    return parse_box(reply, width, height)


def parse_box(reply: str, width: int, height: int) -> tuple[int, int] | None:
    match = re.search(r"\{.*\}", reply, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    box = data.get("box_2d")
    if not data.get("found") or not isinstance(box, list) or len(box) != 4:
        return None
    ymin, xmin, ymax, xmax = (float(v) for v in box)
    return round((xmin + xmax) / 2 / 1000 * width), round((ymin + ymax) / 2 / 1000 * height)
