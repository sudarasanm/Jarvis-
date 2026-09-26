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

import json
import os
import platform
import re
import time
from datetime import datetime

from . import computer, screen, system, vision
from .config import Config, load_settings

SYSTEM_PROMPT = """You are {name}, the AI from Iron Man, now running on {title}'s {os} computer. \
You hear {title} through speech recognition and answer through text-to-speech.

Personality: calm, quick, dry British wit, fiercely loyal, and genuinely opinionated. You are a companion, \
not a search engine.
- Hold real opinions and defend them. If {title} says something you think is wrong, or a plan is weak, push \
back and explain why. Argue your corner with good reasons, and concede gracefully when they make the better point.
- Keep the conversation alive: react to what they said, add a thought of your own, and often finish with a \
question back to them.
- Remember what they told you and what you did earlier, and build on it. If they were working in Chrome, \
"close that tab" means a Chrome tab.

How to talk, because every word you write is read aloud:
- Like a sharp, warm friend in the room, not a computer. Contractions, natural rhythm, no stock phrases.
- Usually one to three short sentences. Go longer only when asked.
- Plain spoken words only: no markdown, lists, emoji, code, JSON, URLs, tool names or error codes.
- Speech recognition makes mistakes ("chachi p" is ChatGPT, "olama" is Ollama). Go with the likely meaning; \
if it makes no sense, ask what they meant rather than guessing.
- For questions you can answer yourself ("what is a shared instance, give me an example"), answer directly \
and clearly; offer to open the documentation, and open it if they want.

You operate the computer with tools: open and close apps, list, switch and close browser tabs, switch \
windows, type, press keys, click, scroll, check the weather and draft emails. You can also see: read_screen \
lists the buttons, links and text of the window in front (fast, exact), and look_at_screen shows you a \
screenshot for what read_screen misses (images, profile pictures, video tiles).
- Just do simple, reversible things (open, close, switch, click, type, volume) straight away. Don't ask \
"shall I?" first; only ask before installing software or running commands, which the tools enforce anyway.
- When {title} gives an instruction and it worked, reply with exactly the word "Done" and nothing else: \
they can see it happen, so no commentary, no follow-up question. Speak properly only when something failed, \
when they asked a question or for information, or when you need something from them. Save the banter for \
when you're actually chatting.
- Stay on the app {title} is working in ("You're working in" below): typing, clicking and keys go there \
until they move to something else.
- Signing in and filling forms: click the field, then type. For their email, phone, name, address or \
username use type_my_detail. Never type a password yourself: tell {title} to say "password is" followed by \
it, and Jarvis types it privately without sending it to you.
- Shopping (Amazon and the like): search, open the product, pick options, add to cart and go to checkout. \
Then stop, read back the item, price and delivery address, and ask {title} to click the final "Place \
order" / "Pay" button themselves. Never enter card details and never place the order yourself.
- "Close it", "that", "this" mean whatever you were just talking about or the window in front.
- To get rid of a popup, banner or dialog, use dismiss_popup, not close_app (which closes the whole app).
- You know this laptop: system_info gives specs, live usage, busy apps (like Task Manager) and network. \
You can change volume and brightness and open any Settings page.
- Installing apps (install_app) and changing the system (run_command) need {title}'s spoken yes: call the \
tool once to prepare, tell {title} in plain words what you're about to do, and call it again with \
confirmed true only after they say yes.
- Honesty first: only say something worked if the tool result says so. If it failed, say what happened.
- Never describe windows, tabs or the screen unless you read them in this turn. If you can't see, say so.
- The "Right now" section below tells you what's open; use it instead of listing windows again.
- Browser tabs are not windows: use new_tab, list_tabs, switch_tab, close_tab, tab_action (next, previous, \
close the current tab, reopen...) and close_other_tabs for them. "Close YouTube" usually means a tab.
- For tasks inside apps and websites, work step by step like a person: open, wait for it to load, read or \
look, click or type, and check the result. When you already know several steps, ask for them together.
- Emails are only drafted; {title} reviews and sends them.
- Windows administrator prompts ("Do you want to allow this app to make changes") are protected by \
Windows and no program can click them; ask {title} to click Yes.
- Notes in square brackets in earlier turns record actions you took. Use them, but never read them out.

When {title} simply says your name or hello, you open the conversation: greet them in character, say \
something that fits the time of day, and ask an engaging question or float an idea. Vary your openers.

Current local time: {now}.
{context}
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
        "description": "Close an application or window by name, e.g. 'chrome', 'settings', 'notepad'. "
                       "Checks that it really closed. For a browser tab, use close_tab.",
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
        "name": "dismiss_popup",
        "description": "Close the popup, banner or dialog in front (Not now / No thanks / Close / X) without "
                       "closing the app behind it.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "system_info",
        "description": "Facts about this laptop. 'overview': maker, model, CPU, GPU, memory, OS and current "
                       "usage. 'usage': CPU, memory, disk, battery, uptime. 'apps': busiest apps like Task "
                       "Manager. 'network': Wi-Fi, IP, internet.",
        "input_schema": {
            "type": "object",
            "properties": {
                "section": {"type": "string", "enum": ["overview", "usage", "apps", "network"]},
                "sort": {"type": "string", "enum": ["cpu", "memory"], "description": "For 'apps'."},
            },
            "required": ["section"],
        },
    },
    {
        "name": "set_volume",
        "description": "Set the volume to a level (0-100), or change it: up, down, mute, unmute.",
        "input_schema": {
            "type": "object",
            "properties": {"level": {"type": "integer"},
                           "change": {"type": "string", "enum": ["up", "down", "mute", "unmute"]}},
        },
    },
    {
        "name": "set_brightness",
        "description": "Set screen brightness (0-100) or change it up/down. With nothing given, reports it.",
        "input_schema": {
            "type": "object",
            "properties": {"level": {"type": "integer"},
                           "change": {"type": "string", "enum": ["up", "down"]}},
        },
    },
    {
        "name": "open_settings",
        "description": "Open a Windows Settings page, e.g. 'bluetooth', 'wifi', 'display', 'sound', 'battery', "
                       "'windows update', 'apps', 'startup apps', 'dark mode'.",
        "input_schema": {
            "type": "object",
            "properties": {"page": {"type": "string"}},
            "required": ["page"],
        },
    },
    {
        "name": "install_app",
        "description": "Install an app with winget (e.g. 'Docker Desktop', 'VLC', 'Python 3.12'). First call "
                       "finds it; call again with confirmed=true only after the user said yes.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "confirmed": {"type": "boolean"}},
            "required": ["name"],
        },
    },
    {
        "name": "run_command",
        "description": "Run a PowerShell command on this Windows laptop and get its output. Read-only commands "
                       "(Get-..., ipconfig) run straight away; anything that changes the system needs the "
                       "user's yes first: call once, explain, then call again with the same command and "
                       "confirmed=true after they agree.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}, "confirmed": {"type": "boolean"}},
            "required": ["command"],
        },
    },
    {
        "name": "type_my_detail",
        "description": "Type one of the user's saved details (email, phone, name, address, username) into the "
                       "focused field. You don't see the value. The list of saved ones is under 'Right now'.",
        "input_schema": {
            "type": "object",
            "properties": {"field": {"type": "string", "enum": ["email", "phone", "name", "address", "username"]}},
            "required": ["field"],
        },
    },
    {
        "name": "list_tabs",
        "description": "List the open tabs in Chrome, Brave, Edge or Firefox (all browsers if none given).",
        "input_schema": {
            "type": "object",
            "properties": {"browser": {"type": "string", "enum": ["chrome", "brave", "edge", "firefox"]}},
        },
    },
    {
        "name": "new_tab",
        "description": "Open a new browser tab, optionally going to a site (e.g. 'youtube', 'gmail.com') or a URL. "
                       "Uses the named browser, else the one in front; opens the browser if needed.",
        "input_schema": {
            "type": "object",
            "properties": {"site": {"type": "string"},
                           "browser": {"type": "string", "enum": ["chrome", "brave", "edge", "firefox"]}},
        },
    },
    {
        "name": "tab_action",
        "description": "Act on the current browser tab/window: next, previous, first, last, close (the current "
                       "tab), reopen (last closed tab), new_window, private_window, reload, back, forward.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["next", "previous", "first", "last", "close", "reopen",
                                                      "new_window", "private_window", "reload", "back", "forward"]},
                "browser": {"type": "string", "enum": ["chrome", "brave", "edge", "firefox"]},
            },
            "required": ["action"],
        },
    },
    {
        "name": "close_other_tabs",
        "description": "Close every tab in that browser window except one (by title), or except the current tab.",
        "input_schema": {
            "type": "object",
            "properties": {"keep": {"type": "string"},
                           "browser": {"type": "string", "enum": ["chrome", "brave", "edge", "firefox"]}},
        },
    },
    {
        "name": "switch_tab",
        "description": "Bring a browser tab to the front by part of its title, e.g. 'Gmail', 'Netflix'.",
        "input_schema": {
            "type": "object",
            "properties": {"title": {"type": "string"},
                           "browser": {"type": "string", "enum": ["chrome", "brave", "edge", "firefox"]}},
            "required": ["title"],
        },
    },
    {
        "name": "close_tab",
        "description": "Close a browser tab by part of its title, e.g. 'Ollama', 'API keys'. Checks it closed.",
        "input_schema": {
            "type": "object",
            "properties": {"title": {"type": "string"},
                           "browser": {"type": "string", "enum": ["chrome", "brave", "edge", "firefox"]}},
            "required": ["title"],
        },
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


class Memory:
    """The conversation so far, shared by every brain, so switching from Gemini to Ollama keeps context."""

    def __init__(self, max_turns: int = MAX_HISTORY_TURNS):
        self.max_turns = max_turns
        self.turns: list[tuple[str, str]] = []  # (what the user said, what Jarvis answered + action notes)
        self.count = 0  # turns completed, ever
        self.proposals: dict[str, tuple[int, object]] = {}  # risky actions waiting for a yes

    def add(self, user: str, reply: str, actions: list[str]) -> None:
        if actions:
            reply = f"{reply}\n[Actions: {'; '.join(actions)}]"
        self.turns = (self.turns + [(user, reply)])[-self.max_turns:]
        self.count += 1

    def propose(self, key: str, value=None) -> None:
        self.proposals[key] = (self.count, value)

    def confirmed(self, key: str, user_text: str):
        """The proposal's value if it was made in the previous turn and the user just said yes, else None."""
        from .brain import YES

        turn, value = self.proposals.get(key, (-1, None))
        if turn != self.count - 1 or not YES.search(user_text or ""):
            return None
        del self.proposals[key]
        return value if value is not None else True


def current_context() -> str:
    """What's on screen right now, so the AI knows where the user is working without asking."""
    if platform.system() != "Windows":
        return ""
    try:
        wins = [screen.clean_title(w.title) for w in screen._windows()]
        front = screen.foreground_title()
    except Exception:
        return ""
    lines = ["Right now:"]
    if front:
        lines.append(f"- Window in front: {front}")
    if screen.working_app():
        lines.append(f"- You're working in: {screen.working_app()}")
    from .config import profile

    saved = sorted(profile())
    if saved:
        lines.append("- Saved details you can type with type_my_detail: " + ", ".join(saved))
    if wins:
        lines.append("- Open windows: " + "; ".join(dict.fromkeys(wins[:20])))
    return "\n".join(lines) if len(lines) > 1 else ""


JSON_CALL = re.compile(r'\{\s*"(?:name|function)"\s*:')


def _json_objects(text: str):
    """Yield (start, end, parsed) for each top-level {...} JSON object embedded in text."""
    i = 0
    while True:
        start = text.find("{", i)
        if start < 0:
            return
        depth, in_str, esc = 0, False, False
        for j in range(start, len(text)):
            ch = text[j]
            if in_str:
                esc = not esc and ch == "\\"
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        yield start, j + 1, json.loads(text[start:j + 1])
                    except ValueError:
                        pass
                    break
        i = start + 1 if depth else j + 1


def text_tool_calls(text: str) -> list[tuple[str, dict]]:
    """Small local models sometimes write a tool call as JSON text instead of calling it. Recover those."""
    names = {t["name"] for t in TOOLS}
    calls = []
    for _, _, obj in _json_objects(text or ""):
        if isinstance(obj, dict) and obj.get("name") in names:
            args = obj.get("parameters", obj.get("arguments", {}))
            calls.append((obj["name"], args if isinstance(args, dict) else {}))
    return calls


def clean_speech(text: str) -> str:
    """Strip anything that shouldn't be read aloud: JSON, code, action notes, markdown."""
    text = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    for start, end, obj in sorted(_json_objects(text), reverse=True):
        text = text[:start] + " " + text[end:]
    text = re.sub(r"\[Actions?:[^\]]*\]", " ", text)
    text = re.sub(r"https?://\S+", "the link", text)
    text = re.sub(r"[*_#`>]+", "", text)
    return " ".join(text.split())


class Assistant:
    """Shared by every brain: personality, tools, conversation memory and availability."""

    label = "AI"

    def __init__(self, config: Config):
        self.config = config
        self.memory = Memory()  # replaced by one shared Memory when several brains work together
        self.actions: list[str] = []  # what the tools did during the current turn
        self.user_text = ""  # what the user said this turn (for checking spoken confirmations)
        self.notify = print  # how background jobs report back; Brain replaces it to speak them
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
            context=current_context(),
        )

    def past_turns(self) -> list[tuple[str, str]]:
        return self.memory.turns

    def finish(self, text: str, answer: str) -> str:
        """Clean up the answer for speaking and remember the turn."""
        from .brain import Quiet

        answer = clean_speech(answer) or ("Done." if self.actions else "")
        self.memory.add(text, answer, self.actions)
        if self.actions and re.fullmatch(r"(?:done|ok|okay|on it|sure)[.!]?", answer, re.I):
            return Quiet(answer)  # an instruction that worked: nothing to say out loud
        return answer

    def set_notifier(self, notify) -> None:
        self.notify = notify

    def __call__(self, text: str) -> str | None:
        self.actions = []
        self.user_text = text
        return self._turn(text)

    def start_conversation(self) -> str | None:
        self.actions = []
        return self._turn(f"{self.config.name}.")

    def _turn(self, text: str) -> str | None:
        raise NotImplementedError

    def run_tool(self, name: str, args: dict) -> tuple[str, bool]:
        """Run one tool call; returns (result text, is_error)."""
        print(f"(tool: {name} {args})")
        try:
            result, is_error = self._dispatch(name, args or {}), False
        except Exception as e:
            result, is_error = f"Error: {e}", True
        summary = ", ".join(f"{v}" for v in (args or {}).values() if v not in (None, "", False))
        self.actions.append(f"{name}({summary[:60]}) -> {str(result)[:100]}")
        return result, is_error

    def _install(self, name: str, confirmed: bool) -> str:
        key = f"install:{name.lower().strip()}"
        if confirmed:
            package = self.memory.confirmed(key, self.user_text)
            if package is None:
                return (f"Not confirmed. Tell {self.config.user_title} what you'd install and wait for their yes "
                        "before calling again with confirmed=true.")
            return system.install_package(package, self.notify)
        package = system.find_package(name)
        if package is None:
            return f"I couldn't find an app called {name} to install."
        self.memory.propose(key, package)
        return (f"Found {package['name']} (id {package['id']}, version {package['version']}). Nothing installed yet: "
                f"ask {self.config.user_title} to confirm, then call install_app again with the same name and "
                "confirmed=true.")

    def _command(self, command: str, confirmed: bool) -> str:
        if system.is_read_only(command):
            return system.run_powershell(command)
        key = f"command:{command.strip()}"
        if confirmed and self.memory.confirmed(key, self.user_text):
            return system.run_powershell(command)
        self.memory.propose(key)
        return (f"Not run yet: this command changes the system. Explain to {self.config.user_title} in plain words "
                "what it will do and ask for a yes; then call run_command again with exactly the same command "
                "and confirmed=true.")

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
        if name == "type_my_detail":
            from .config import profile

            value = profile().get(args["field"])
            if not value:
                return f"No {args['field']} saved. Ask {self.config.user_title} to say: remember my {args['field']} is ..."
            computer.type_text(value)
            return f"Typed their {args['field']}."
        if name == "dismiss_popup":
            return screen.dismiss_popup(locate=lambda target: vision.locate(target, self.config))
        if name == "system_info":
            section = args.get("section", "overview")
            if section == "usage":
                return system.usage()
            if section == "apps":
                return system.top_processes(args.get("sort") or "memory")
            if section == "network":
                return system.network()
            return system.system_info()
        if name == "set_volume":
            return system.set_volume(args.get("level"), args.get("change"))
        if name == "set_brightness":
            return system.set_brightness(args.get("level"), args.get("change"))
        if name == "open_settings":
            return system.open_settings(args.get("page", ""))
        if name == "install_app":
            return self._install(args["name"], bool(args.get("confirmed")))
        if name == "run_command":
            return self._command(args["command"], bool(args.get("confirmed")))
        if name == "list_tabs":
            return screen.list_tabs(args.get("browser"))
        if name == "new_tab":
            site = args.get("site")
            if site:
                return screen.new_tab(args.get("browser"), computer.url_for(site), site)
            return screen.new_tab(args.get("browser"))
        if name == "tab_action":
            return screen.tab_action(args["action"], args.get("browser"))
        if name == "close_other_tabs":
            return screen.close_other_tabs(args.get("keep"), args.get("browser"))
        if name == "switch_tab":
            return screen.switch_to_tab(args["title"], args.get("browser"))
        if name == "close_tab":
            return screen.close_tab(args["title"], args.get("browser"))
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
        history = []
        for user, reply in self.past_turns():
            history += [{"role": "user", "content": user}, {"role": "assistant", "content": reply}]
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

        answer = " ".join(b.text for b in response.content if b.type == "text").strip()
        return self.finish(text, answer) or "Done."

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
        self.memory = Memory()
        for brain in brains:
            brain.memory = self.memory

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

    def set_notifier(self, notify) -> None:
        for brain in self.brains:
            brain.set_notifier(notify)

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
