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
2. When asked, pick an AI brain (Gemini is free, see [AI brain](#ai-brain-free-options)) and your accent.

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
| "close chrome" / "close settings" / "close notepad" | close the app politely, check it really closed, and force it if it's stuck (never forces apps with unsaved work) |
| "open a new tab" / "new tab in Edge" / "open YouTube in a new tab" / "open Gmail in Chrome" / "open a new tab and search for cricket scores" | open tabs, in the browser you name or the one in front (opening it if needed) |
| "list the tabs in Chrome" / "close the Gmail tab" / "close YouTube" / "close Ollama in Chrome" / "switch to the Netflix tab" | find tabs by name, switch to them or close them |
| "close this tab" / "next tab" / "previous tab" / "reopen closed tab" / "close all tabs except Gmail" | the current tab |
| "open a new window" / "open an incognito window" / "refresh the page" / "go back" | windows and pages |
| "click Allow" / "click on Amma" / "double click Recycle Bin" / "right click ..." | click things on screen by name (finds them exactly, or looks at the screen) |
| "scroll down" / "scroll up a lot" | scroll |
| "what windows are open" / "switch to Brave" | list or switch windows |
| "open Netflix and tell me the profiles", "pick Amma" | see the screen and act on it step by step |
| "which accounts are in Chrome" / "open Chrome as Work" | list browser profiles (Chrome, Brave, Edge) or open one |
| "open Hotstar and play Jailer" / "open Claude, ask it X and read me the answer" | multi-step tasks in apps and websites |
| "close the popup" / "dismiss that banner" | click the popup's own Not now / No thanks / Close button (not the app's) |
| "close it" | close whatever you were just talking about |
| "install Docker" / "install VLC" | find it in the Windows catalogue (winget), **ask you first**, install it, and tell you when it's done |
| "what are my laptop specs" / "how much battery is left" / "why is my laptop slow" / "am I connected" | specs, live usage, busiest apps (like Task Manager), Wi-Fi and internet |
| "set the volume to 40" / "mute" / "brightness 70" / "open bluetooth settings" | volume, brightness, any Settings page |
| "check my email" / "any unread emails?" / "did I get any job application emails this week?" / "read me the one from HR" | read and summarise your Gmail (needs [email setup](#email-setup)); nothing gets marked as read |
| "email Priya that I'm free tomorrow" | writes the email, reads it back, and **sends only after your yes** |
| "send a WhatsApp message to Amma saying I'll be late" / "open the chat with Ravi" | opens the chat and types it; **sends only after your yes** |
| "open the first pinned contact" / "open the last chat" / "send a message to the first chat saying …" / "send … to this chat" | WhatsApp chats by position, or the one that's open |
| "type hello world" / "type fourteen twenty six" / "type s u d a r s a n" | type into the app you're using: numbers as digits, spelled letters joined, "… at the rate gmail dot com" as an email |
| "remember my email is …" / "type my email" / "what's my phone number" / "forget my address" | remember your email, phone, name, address and username on this computer and type them for you |
| "password is …" | type a password into the focused field: never saved, never sent to the AI, hidden in the log |
| "type X in the username field" / "sign in" / "submit" / "allow" | fill in forms and press their buttons |
| "press enter" / "press control t" / "press alt tab" | press keys |
| "write an email to sudar at gmail dot com about the demo" | draft it in Gmail for you to review and send (never sends by itself) |
| "open chrome and search for today's cricket score" | multi-step tasks (Claude works out the steps) |
| "what's the weather" / "weather in Tokyo" | live forecast (Open-Meteo, no key needed) |
| "turn off my computer" / "restart" / "put the computer to sleep" / "lock the screen" | ask for confirmation, then do it |
| "call me Tony" | call you that from now on |
| "play back in black" / "search for arc reactor designs" | YouTube / Google |
| "system status" / "battery" | CPU, memory, battery |

## AI brain (free options)

Conversation, opinions, arguments, emails, seeing the screen and multi-step tasks need an AI brain. The installer sets up **Gemini as the main brain and Ollama as a free offline backup**:

| Brain | Cost | Setup |
|---|---|---|
| **Google Gemini** (recommended) | **Free** tier, no card needed | Get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) → `"gemini_api_key"` |
| **Ollama** | **Free**, runs on your PC, works offline | Install [Ollama](https://ollama.com), run `ollama pull llama3.2` (needs 8 GB+ RAM) |
| **Claude** | Paid API credit (separate from a Claude Pro subscription) | Key from [platform.claude.com](https://platform.claude.com) → `"anthropic_api_key"` |

Jarvis uses Gemini first. When Gemini's free limit runs out or it stops answering, Jarvis **switches to Ollama and stays there**, checking Gemini quietly in the background every two minutes and switching back only once it answers again, so you never wait on a failing Gemini. To use only Ollama, set `"ai_provider": "ollama"`. Claude is only used if you add a key with credit. Looking at the screen needs Gemini (or an Ollama vision model set as `ollama_vision_model`). Keys live in `%USERPROFILE%\.jarvis.json`, **outside the code folder**, so they never end up on GitHub. Never paste a key into the code itself.

## What it can't do

- **Windows administrator prompts** ("Do you want to allow this app to make changes to your device?") appear on a protected screen that Windows blocks all programs from reading or clicking. When you install something, Jarvis tells you to click **Yes** on it. Normal "Allow / Cancel" popups work.
- Installing apps and running commands that change the system always need your spoken "yes" first. This is enforced in code, not just by asking the AI nicely.
- **No card details, no paying.** Jarvis won't store or type card numbers (Amazon and your browser keep your card safely), and when shopping it goes as far as checkout, reads back the item, price and address, and leaves the final "Place order" click to you.
- Successful instructions happen silently; Jarvis only speaks for answers, questions and problems. Set `"quiet_actions": false` to hear confirmations again.
- Seeing the screen works on the main monitor, and reading buttons by name works on Windows.

## Email setup

Jarvis reads and sends Gmail directly (not by clicking around the website), using a Google **app password**:

1. Turn on [2-Step Verification](https://myaccount.google.com/signinoptions/two-step-verification) for your Google account.
2. Create an app password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) (name it "Jarvis") and copy the 16-letter code.
3. Run `.venv\Scripts\python -m jarvis --setup-email` and paste it when asked.

The app password is stored in Windows Credential Manager, not in a file. You can revoke it any time from the same Google page. Email text you ask Jarvis to summarise goes to the AI brain (Gemini) to be summarised.

## Hearing you better

- **Accent:** set `language` to match how you speak: `en-IN` (Indian English), `en-US`, `en-GB`, or even `ta-IN` / `hi-IN`. This makes a big difference.
- **Quiet voice:** Jarvis boosts quiet speech automatically. If it still misses you, set `mic_sensitivity` to `max`. If it reacts to background noise, use `normal`.
- **Wrong microphone:** run `.venv\Scripts\python -m jarvis --list-mics` and put the right number in `mic_index`.

## Settings

Edit `%USERPROFILE%\.jarvis.json` (on Mac/Linux `~/.jarvis.json`), then restart Jarvis. Environment variables `JARVIS_<NAME>` override the file.

```json
{
  "ai_provider": "gemini",
  "gemini_api_key": "AIza...",
  "language": "en-IN",
  "user_title": "sir",
  "city": "Chennai",
  "mic_sensitivity": "high"
}
```

| Setting | Default | Meaning |
|---|---|---|
| `ai_provider` | `auto` | Brain to try first: `gemini`, `ollama`, `claude` (others are backups) |
| `gemini_api_key` | | Free Gemini key (or set `GEMINI_API_KEY`) |
| `gemini_model` | `gemini-flash-latest` | Gemini model |
| `gemini_backup_models` | `gemini-flash-lite-latest` | Used when the main model's free limit runs out (each has its own quota) |
| `ollama_model` | `llama3.2` | Ollama model. With 16 GB+ RAM, `qwen2.5:7b` is much smarter (`ollama pull qwen2.5:7b`) |
| `ollama_vision_model` | | Ollama model that can see the screen when there's no Gemini key (e.g. `llama3.2-vision`) |
| `anthropic_api_key` | | Claude API key (or set `ANTHROPIC_API_KEY`) |
| `language` | `en-US` | Speech recognition language |
| `mic_sensitivity` | `high` | `low`, `normal`, `high` or `max` |
| `mic_index` | system default | Which microphone (`--list-mics`) |
| `always_listen` | `false` | `true` = answer everything you say, no "Jarvis" needed |
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
.venv\Scripts\python -m jarvis --logs     # in a second window: watch what Jarvis is doing, live
```

The console shows timings for every step, like `(heard 2.1s of speech, recognised in 0.8s)` and `(answered in 3.4s)`, so you can see where any delay comes from. When it runs in the background, everything it hears and does is logged to `%USERPROFILE%\.jarvis.log`. Stop the background copy first (only one Jarvis runs at a time).

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
