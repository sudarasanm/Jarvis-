"""Free brains for Jarvis: Google Gemini (free API tier) and Ollama (runs on your own PC).

Both talk plain HTTP, so they need no extra packages, and both use the same
personality and tools as Claude (see ai.py).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .ai import MAX_TOOL_ROUNDS, TOOLS, Assistant
from .config import Config, load_settings


class HTTPError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message


def post_json(url: str, body: dict, headers: dict | None = None, timeout: float = 120) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            err = json.loads(raw)
            message = err.get("error", {}).get("message") if isinstance(err.get("error"), dict) else err.get("error")
        except ValueError:
            message = None
        raise HTTPError(e.code, message or raw[:300]) from None


def get_json(url: str, timeout: float = 2) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.load(resp)


TOO_MANY_STEPS = "That took more steps than I expected, so I stopped. Shall we try it another way?"
OFFLINE = "I can't reach my language servers right now. Check the internet connection."


class Gemini(Assistant):
    """Google Gemini. Free tier: get a key at https://aistudio.google.com/apikey (no card needed)."""

    label = "Gemini"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(self, config: Config, api_key: str, post=post_json):
        super().__init__(config)
        self.api_key = api_key
        self.post = post
        declarations = []
        for t in TOOLS:
            declaration = {"name": t["name"], "description": t["description"]}
            if t["input_schema"].get("properties"):  # Gemini rejects empty parameter objects
                declaration["parameters"] = t["input_schema"]
            declarations.append(declaration)
        self.tools = [{"functionDeclarations": declarations}]

    def _turn(self, text: str) -> str | None:
        turn = [{"role": "user", "parts": [{"text": text}]}]
        try:
            for _ in range(MAX_TOOL_ROUNDS):
                data = self.post(
                    self.URL.format(model=self.config.gemini_model),
                    {
                        "systemInstruction": {"parts": [{"text": self.system()}]},
                        "contents": self.history() + turn,
                        "tools": self.tools,
                    },
                    {"x-goog-api-key": self.api_key},
                )
                candidates = data.get("candidates") or []
                content = candidates[0].get("content") if candidates else None
                if not content or not content.get("parts"):
                    return "I'm afraid I can't help with that one."
                # Echo the model's content back unchanged: it can carry signatures Gemini needs.
                turn.append(content)
                calls = [p["functionCall"] for p in content["parts"] if "functionCall" in p]
                if not calls:
                    break
                responses = []
                for call in calls:
                    result, is_error = self.run_tool(call["name"], call.get("args") or {})
                    responses.append({"functionResponse": {
                        "name": call["name"],
                        "response": {"error": result} if is_error else {"result": result},
                    }})
                turn.append({"role": "user", "parts": responses})
            else:
                return TOO_MANY_STEPS
        except HTTPError as e:
            print(f"(Gemini error {e.status}: {e.message})")
            if e.status == 429:
                self.pause(60, "free quota used up for the moment")
                return "I've hit Gemini's free limit for the moment. Give me a minute."
            if e.status in (400, 401, 403) and "key" in e.message.lower():
                self.pause(3600, "API key not accepted")
                return "Gemini didn't accept the API key. Please check it."
            if e.status == 404:
                return f"The model {self.config.gemini_model} isn't available. Try another gemini_model setting."
            if e.status >= 500:
                self.pause(30, "Gemini is having trouble")
                return "Gemini is having trouble right now."
            return f"Gemini rejected that request. It said: {e.message}"
        except (urllib.error.URLError, TimeoutError, OSError):
            self.pause(30, "can't reach Gemini")
            return OFFLINE

        self.remember(turn)
        answer = " ".join(p["text"] for p in content["parts"] if p.get("text") and not p.get("thought")).strip()
        return answer or "Done."


class Ollama(Assistant):
    """A model running on this PC with Ollama (https://ollama.com). Free and offline."""

    label = "Ollama"

    def __init__(self, config: Config, post=post_json):
        super().__init__(config)
        self.post = post
        self._started = False
        self.tools = [{"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in TOOLS]

    def _turn(self, text: str) -> str | None:
        turn = [{"role": "user", "content": text}]
        try:
            for _ in range(MAX_TOOL_ROUNDS):
                data = self.post(
                    f"{self.config.ollama_url}/api/chat",
                    {
                        "model": self.config.ollama_model,
                        "messages": [{"role": "system", "content": self.system()}] + self.history() + turn,
                        "tools": self.tools,
                        "stream": False,
                    },
                )
                message = data.get("message") or {}
                turn.append({k: v for k, v in message.items() if k in ("role", "content", "tool_calls")})
                calls = message.get("tool_calls") or []
                if not calls:
                    break
                for call in calls:
                    fn = call.get("function", {})
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        args = json.loads(args or "{}")
                    result, _ = self.run_tool(fn.get("name", ""), args)
                    turn.append({"role": "tool", "tool_name": fn.get("name", ""), "content": result})
            else:
                return TOO_MANY_STEPS
        except HTTPError as e:
            print(f"(Ollama error {e.status}: {e.message})")
            if "not found" in e.message.lower():
                return f"The model {self.config.ollama_model} isn't downloaded. Run: ollama pull {self.config.ollama_model}"
            return f"Ollama had a problem: {e.message}"
        except (urllib.error.URLError, TimeoutError, OSError):
            if not self._started and start_ollama(self.config):
                self._started = True
                return self._turn(text)
            self.pause(60, "Ollama isn't running")
            return "I can't reach Ollama. Is it running?"

        self.remember(turn)
        return (message.get("content") or "").strip() or "Done."


def gemini_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or load_settings().get("gemini_api_key")


def make_gemini(config: Config) -> Gemini | None:
    key = gemini_key()
    return Gemini(config, key) if key else None


def ollama_exe() -> str | None:
    import shutil
    from pathlib import Path

    found = shutil.which("ollama")
    if found:
        return found
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    return str(local) if os.environ.get("LOCALAPPDATA") and local.exists() else None


def start_ollama(config: Config, wait: float = 15) -> bool:
    """Start the Ollama server in the background if it's installed. True once it answers."""
    import subprocess
    import time

    exe = ollama_exe()
    if exe is None:
        return False
    print("(starting Ollama...)")
    flags = 0x08000000 if os.name == "nt" else 0  # no console window on Windows
    subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    deadline = time.time() + wait
    while time.time() < deadline:
        try:
            get_json(f"{config.ollama_url}/api/tags")
            return True
        except Exception:
            time.sleep(0.5)
    return False


def make_ollama(config: Config) -> Ollama | None:
    """Return an Ollama brain if Ollama is installed (starting it if needed) with the model downloaded."""
    try:
        tags = get_json(f"{config.ollama_url}/api/tags")
    except Exception:
        if not start_ollama(config):
            return None
        try:
            tags = get_json(f"{config.ollama_url}/api/tags")
        except Exception:
            return None
    names = {m.get("name", "") for m in tags.get("models", [])}
    wanted = config.ollama_model
    if not any(n == wanted or n.split(":")[0] == wanted for n in names):
        print(f"(Ollama is running but {wanted} isn't downloaded. Run: ollama pull {wanted})")
        return None
    return Ollama(config)
