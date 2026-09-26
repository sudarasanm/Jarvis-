# J.A.R.V.I.S.

*Just A Rather Very Intelligent System*: a voice assistant for your computer, inspired by Iron Man. It runs quietly in the background, holds real conversations (and will argue with you), and operates your computer for you.

```
You:    Jarvis.
Jarvis: Good evening, sir. You've been at the keyboard a while. Productive day, or one of those?
You:    Productive. I think I'll learn Rust next.
Jarvis: Bold. I'd argue you should finish the Python project first. Half-built things have a way of haunting people. What's pulling you to Rust?
You:    Open Hotstar and close Chrome.
Jarvis: Hotstar's up and Chrome is closed. Cricket or a film tonight?
You:    Write an email to sudar at gmail dot com saying I'll be late tomorrow.
Jarvis: I've drafted it in Gmail. Have a look and hit send when you're happy.
You:    Bye.
Jarvis: Very well, sir. Just say my name if you need me.
```

## Install on Windows (one time)

1. Install [Git](https://git-scm.com/download/win) if you don't have it, then open PowerShell:
   ```powershell
   git clone -b claude/jarvis-voice-assistant-9m6bmn https://github.com/sudarasanm/Jarvis-.git
   cd Jarvis-
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```
2. When asked, paste your **Anthropic API key** (see [Claude brain](#claude-brain)) and pick your accent.

That's it. The installer:
- installs Python 3.13 if needed (PyAudio, the microphone library, doesn't support 3.14 on Windows yet),
- installs all packages into `.venv`,
- makes Jarvis **start automatically, silently, whenever you log in**,
- adds **Jarvis** and **Stop Jarvis** shortcuts to your desktop,
- starts Jarvis right away.

To update later: `git pull`, then run the installer again.

## Talking to Jarvis

- **Say "Jarvis"** and it starts a conversation. From then on, just talk. No need to repeat its name.
- **"Hey Jarvis, <command>"** does one thing straight away.
- The conversation ends when you say **"bye"** or **"that's all"**, or stay quiet for about 12 seconds. Then it waits for its name again.
- **"Jarvis, go offline"** (or the Stop Jarvis shortcut) shuts Jarvis down completely.

| Say... | Jarvis will... |
|---|---|
| "Jarvis" | start a conversation: chat, debate, brainstorm, ask anything |
| "open chrome" / "open terminal" / "open hotstar" / "open photoshop" | open any app or website (unknown apps are found through the Start menu) |
| "close chrome" / "close notepad" | close the app politely, so nothing is lost |
| "type hello world" | type into whatever text box is focused |
| "press enter" / "press control t" / "press alt tab" | press keys |
| "write an email to sudar at gmail dot com about the demo" | draft it in Gmail for you to review and send (never sends by itself) |
| "open chrome and search for today's cricket score" | multi-step tasks (Claude works out the steps) |
| "what's the weather" / "weather in Tokyo" | live forecast (Open-Meteo, no key needed) |
| "turn off my computer" / "restart" / "put the computer to sleep" / "lock the screen" | ask for confirmation, then do it |
| "call me Tony" | call you that from now on |
| "play back in black" / "search for arc reactor designs" | YouTube / Google |
| "system status" / "battery" | CPU, memory, battery |

## Claude brain

Conversation, opinions, arguments, emails and multi-step tasks come from Claude. This needs an **API key** from the [Claude Console](https://platform.claude.com) (API Keys → Create Key). The API is billed separately from a Claude Pro/Max subscription, so add a few dollars of credit there first. A spoken reply typically costs a fraction of a cent.

The installer saves the key in `%USERPROFILE%\.jarvis.json`, **outside the code folder**, so it never ends up on GitHub. Never paste the key into the code itself.

## Hearing you better

- **Accent:** set `language` to match how you speak: `en-IN` (Indian English), `en-US`, `en-GB`, or even `ta-IN` / `hi-IN`. This makes a big difference.
- **Quiet voice:** Jarvis boosts quiet speech automatically. If it still misses you, set `mic_sensitivity` to `max`. If it reacts to background noise, use `normal`.
- **Wrong microphone:** run `.venv\Scripts\python -m jarvis --list-mics` and put the right number in `mic_index`.

## Settings

Edit `%USERPROFILE%\.jarvis.json` (on Mac/Linux `~/.jarvis.json`), then restart Jarvis. Environment variables `JARVIS_<NAME>` override the file.

```json
{
  "anthropic_api_key": "sk-ant-...",
  "language": "en-IN",
  "user_title": "sir",
  "city": "Chennai",
  "mic_sensitivity": "high"
}
```

| Setting | Default | Meaning |
|---|---|---|
| `anthropic_api_key` | | Claude API key (or set `ANTHROPIC_API_KEY`) |
| `language` | `en-US` | Speech recognition language |
| `mic_sensitivity` | `high` | `low`, `normal`, `high` or `max` |
| `mic_index` | system default | Which microphone (`--list-mics`) |
| `conversation_timeout` | `12` | Seconds of silence before a conversation ends |
| `user_title` | `sir` | What Jarvis calls you (or just say "call me ...") |
| `city` | from your IP | Default weather location |
| `units` | `metric` | `metric` or `imperial` |
| `email_client` | `gmail` | `gmail`, or `default` for your mail app |
| `name` | `Jarvis` | Assistant name, which is also the wake word |
| `claude_model` | `claude-opus-5` | Claude model |
| `dry_run` | `false` | `true` = print power commands instead of running them |

## Running it by hand / troubleshooting

```powershell
.venv\Scripts\python -m jarvis            # with a console window, so you can see what it hears
.venv\Scripts\python -m jarvis --text     # type instead of talking
.venv\Scripts\python -m jarvis --no-wake  # answer everything, no "Jarvis" needed
.venv\Scripts\python -m jarvis --stop     # stop the background copy
```

When it runs in the background, everything it hears and does is logged to `%USERPROFILE%\.jarvis.log`. Stop the background copy first (only one Jarvis runs at a time).

On macOS/Linux: `pip install -r requirements.txt` (macOS: `brew install portaudio` first; Linux: `sudo apt install portaudio19-dev espeak`), then `python -m jarvis`.

## Adding a skill

Drop a function into any module under `jarvis/skills/` (and import that module in `jarvis/skills/__init__.py`):

```python
from ..brain import Response, skill

@skill(r"\bsuit up\b")
def suit_up(match, brain):
    return Response(f"Mark 42 is on its way, {brain.title}.")
```

Patterns are case-insensitive regexes, and the first match wins. Return `Response(text, on_confirm=fn)` to ask yes/no first, or `None` to let Claude handle it instead. To give Claude a new ability, add a tool to `TOOLS` in `jarvis/ai.py`.

## Tests

```bash
pip install pytest && python -m pytest
```
