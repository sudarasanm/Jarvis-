"""Free brains for Jarvis: Google Gemini (free API tier) and Ollama (runs on your own PC).

Both talk plain HTTP, so they need no extra packages, and both use the same
personality and tools as Claude (see ai.py).
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from .ai import MAX_TOOL_ROUNDS, OLLAMA_SYSTEM_PROMPT, TOOLS, Assistant, text_tool_calls
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


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# model -> time.time() when it may be used again. Shared by chat and screen-reading (vision.py),
# because they draw on the same free quota.
_gemini_resting: dict[str, float] = {}


class GeminiUnavailable(Exception):
    def __init__(self, seconds: float):
        super().__init__(f"all Gemini models are resting for {seconds:.0f}s")
        self.seconds = seconds


def retry_delay(message: str) -> float | None:
    """'Please retry in 426.6ms.' -> 0.43; 'retry in 40.05s' -> 40.05."""
    m = re.search(r"retry in ([\d.]+)\s*(ms|s)\b", message or "", re.I)
    if not m:
        return None
    value = float(m.group(1))
    return value / 1000 if m.group(2).lower() == "ms" else value


def gemini_models(config: Config) -> list[str]:
    models = [config.gemini_model] + [m.strip() for m in str(config.gemini_backup_models or "").split(",")]
    return list(dict.fromkeys(m for m in models if m))


# Less thinking = faster spoken replies. Newer models take thinkingLevel, older ones thinkingBudget;
# each model remembers the first option it accepted.
THINKING_OPTIONS = [{"thinkingLevel": "low"}, {"thinkingBudget": 0}, None]
_thinking_choice: dict[str, int] = {}


def _with_thinking(body: dict, option: dict | None) -> dict:
    if option is None:
        return body
    config = dict(body.get("generationConfig") or {})
    config["thinkingConfig"] = option
    return {**body, "generationConfig": config}


def gemini_generate(config: Config, body: dict, key: str | None = None, post=None, timeout: float = 15) -> dict:
    """Call Gemini, riding out the free tier's limits: wait out very short limits, rotate to the next
    model (each has its own free quota), and raise GeminiUnavailable when they're all resting."""
    post = post or post_json
    key = key or gemini_key()
    last_error = None
    for model in gemini_models(config):
        if time.time() < _gemini_resting.get(model, 0):
            continue
        waited = False
        while True:
            choice = _thinking_choice.get(model, 0)
            try:
                began = time.time()
                reply = post(GEMINI_URL.format(model=model), _with_thinking(body, THINKING_OPTIONS[choice]),
                             {"x-goog-api-key": key}, timeout=timeout)
                print(f"(Gemini {model} replied in {time.time() - began:.1f}s)")
                return reply
            except HTTPError as e:
                last_error = e
                if e.status == 400 and "thinking" in e.message.lower() and choice + 1 < len(THINKING_OPTIONS):
                    _thinking_choice[model] = choice + 1  # this model wants a different thinking setting
                    continue
                if e.status == 429:
                    delay = retry_delay(e.message)
                    if not waited and delay is not None and delay <= 5:
                        waited = True
                        time.sleep(delay + 0.3)
                        continue
                    rest = max(delay or 60, 10)
                    _gemini_resting[model] = time.time() + rest
                    print(f"(Gemini {model}: free limit reached, resting {rest:.0f}s)")
                    break
                if e.status == 404 and model != config.gemini_model:
                    _gemini_resting[model] = time.time() + 3600  # backup model doesn't exist
                    break
                raise
            except (TimeoutError, OSError) as e:  # slow or dropped connection: try the other model
                last_error = e
                _gemini_resting[model] = time.time() + 20
                print(f"(Gemini {model} didn't answer in time: {e})")
                break
    waits = [t - time.time() for t in _gemini_resting.values()]
    raise GeminiUnavailable(max(min(waits) if waits else 60, 5)) from last_error


class Gemini(Assistant):
    """Google Gemini. Free tier: get a key at https://aistudio.google.com/apikey (no card needed)."""

    label = "Gemini"
    URL = GEMINI_URL

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

    def ping(self) -> bool:
        try:
            gemini_generate(self.config, {"contents": [{"role": "user", "parts": [{"text": "Say OK."}]}]},
                            self.api_key, self.post, timeout=10)
            return True
        except Exception:
            return False

    def _turn(self, text: str) -> str | None:
        history = []
        for user, reply in self.past_turns():
            history += [{"role": "user", "parts": [{"text": user}]}, {"role": "model", "parts": [{"text": reply}]}]
        turn = [{"role": "user", "parts": [{"text": self.with_situation(text)}]}]
        try:
            for _ in range(MAX_TOOL_ROUNDS):
                data = gemini_generate(self.config, {
                    "systemInstruction": {"parts": [{"text": self.system()}]},
                    "contents": history + turn,
                    "tools": self.tools,
                }, self.api_key, self.post)
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
        except GeminiUnavailable as e:
            self.pause(max(e.seconds, 60), "free limit reached on every Gemini model")
            return "I've hit Gemini's free limit for the moment. Give me a minute."
        except HTTPError as e:
            print(f"(Gemini error {e.status}: {e.message})")
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
            self.pause(60, "can't reach Gemini")
            return OFFLINE

        answer = " ".join(p["text"] for p in content["parts"] if p.get("text") and not p.get("thought"))
        return self.finish(text, answer) or "Done."


# A small model on a laptop CPU chokes on 40 tools: give it the everyday ones.
OLLAMA_TOOLS = {"open_app", "close_app", "new_tab", "close_tab", "list_tabs", "switch_tab", "tab_action", "switch_window",
                "type_text", "type_my_detail", "press_keys", "click", "read_screen", "get_weather", "system_info",
                "set_volume", "whatsapp_message", "whatsapp_open_chat", "email_list", "clear_field", "fill_field"}


OLLAMA_TOOL_ROUNDS = 6  # each round takes a while on a laptop CPU: keep tasks short


class Ollama(Assistant):
    """A model running on this PC with Ollama (https://ollama.com). Free and offline."""

    label = "Ollama"
    system_prompt = OLLAMA_SYSTEM_PROMPT

    def __init__(self, config: Config, post=post_json):
        super().__init__(config)
        self.post = post
        self._started = False
        self.tools = [{"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
            for t in TOOLS if t["name"] in OLLAMA_TOOLS]

    def _turn(self, text: str) -> str | None:
        history = []
        for user, reply in self.past_turns():
            history += [{"role": "user", "content": user}, {"role": "assistant", "content": reply}]
        turn = [{"role": "user", "content": self.with_situation(text)}]
        try:
            for _ in range(OLLAMA_TOOL_ROUNDS):
                data = self.post(
                    f"{self.config.ollama_url}/api/chat",
                    {
                        "model": self.config.ollama_model,
                        "messages": [{"role": "system", "content": self.system()}] + history + turn,
                        "tools": self.tools,
                        "stream": False,
                        # Room for the instructions and conversation (the default cuts them off), and stay
                        # loaded between questions instead of reloading from disk each time.
                        "options": {"num_ctx": 8192},
                        "keep_alive": "30m",
                    },
                    timeout=90,
                )
                message = data.get("message") or {}
                turn.append({k: v for k, v in message.items() if k in ("role", "content", "tool_calls")})
                calls = []
                for call in message.get("tool_calls") or []:
                    fn = call.get("function", {})
                    args = fn.get("arguments") or {}
                    if isinstance(args, str):
                        args = json.loads(args or "{}")
                    calls.append((fn.get("name", ""), args))
                if not calls:
                    # Small models sometimes write the call as JSON text; run it rather than read it out.
                    calls = text_tool_calls(message.get("content", ""))
                if not calls:
                    break
                for name, args in calls:
                    result, _ = self.run_tool(name, args)
                    turn.append({"role": "tool", "tool_name": name, "content": result})
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

        return self.finish(text, message.get("content") or "") or "Done."


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
