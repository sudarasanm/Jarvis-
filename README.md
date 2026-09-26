# J.A.R.V.I.S.

*Just A Rather Very Intelligent System*: a voice assistant for your computer, inspired by Iron Man.

```
You:    Hey Jarvis, what's the weather in London?
Jarvis: Currently in London it's 18 degrees Celsius with light rain, feels like 17...
You:    Jarvis, turn off my computer.
Jarvis: Are you sure you want me to shut down the computer, sir?
You:    Yes.
Jarvis: Shutting down. Goodbye, sir.
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m jarvis            # talk to it
python -m jarvis --text     # type to it (no microphone needed)
python -m jarvis --no-wake  # no "Hey Jarvis" needed, it answers everything it hears
```

Say **"Hey Jarvis"** followed by a command, or just "Jarvis", wait for *"Yes, sir?"*, then speak.

> **PyAudio install tips:** macOS: `brew install portaudio` first. Linux: `sudo apt install portaudio19-dev python3-pyaudio espeak`. Windows: use **Python 3.13 or older**, because PyAudio has no prebuilt Windows package for 3.14 yet and pip would try to compile it (the error says "Microsoft Visual C++ 14.0 or greater is required"). Install 3.13 alongside with `winget install -e --id Python.Python.3.13`, then create the venv with `py -3.13 -m venv .venv`.

## What it can do

| Say... | Jarvis will... |
|---|---|
| "what time is it" / "what's the date" | tell you |
| "what's the weather" / "weather in Tokyo" / "is it going to rain" | fetch a live forecast (Open-Meteo, no API key) |
| "turn off my computer" / "restart" / "put the computer to sleep" | ask for confirmation, then do it |
| "cancel the shutdown" | abort a pending shutdown (Windows/Linux) |
| "lock the screen" | lock it |
| "open youtube" / "open github.com" | open it in your browser |
| "search for arc reactor designs" | Google it |
| "play back in black" | search YouTube |
| "system status" / "battery" | CPU, memory, battery |
| "call me Tony" / "my name is Tony" | call you that from now on (remembered in `~/.jarvis.json`) |
| "tell me a joke", "who are you", "help" | exactly that |
| "goodbye" | shut Jarvis down |
| *anything else* | ask Claude (if configured) |

## Claude brain (optional)

Questions Jarvis doesn't recognise ("how far is the moon?", "give me a pasta recipe") go to Claude, and short follow-ups keep their context.

This needs an **API key** from the [Claude Console](https://platform.claude.com). API usage is billed separately from a Claude Pro/Max subscription, so add some credits there first.

```bash
export ANTHROPIC_API_KEY=sk-ant-...            # macOS / Linux
setx ANTHROPIC_API_KEY "sk-ant-..."            # Windows (then open a new terminal)
```

## Settings

All optional, set as environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `JARVIS_CITY` | *(auto from IP)* | Default city for weather |
| `JARVIS_UNITS` | `metric` | `metric` or `imperial` |
| `JARVIS_USER_TITLE` | `sir` | How Jarvis addresses you |
| `JARVIS_NAME` | `Jarvis` | Assistant name, which is also the wake word |
| `JARVIS_DRY_RUN` | `0` | `1` = print power commands instead of running them (same as `--dry-run`) |
| `JARVIS_CLAUDE_MODEL` | `claude-opus-5` | Claude model for the fallback |

## Adding a skill

Drop a function into any module under `jarvis/skills/` (and import that module in `jarvis/skills/__init__.py`):

```python
from ..brain import Response, skill

@skill(r"\bsuit up\b")
def suit_up(match, brain):
    return Response(f"Mark 42 is on its way, {brain.title}.")
```

Patterns are case-insensitive regexes, and the first match wins. Return `Response(text, on_confirm=fn)` to ask yes/no before doing something risky.

## Tests

```bash
pip install pytest && python -m pytest
```
