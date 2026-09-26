"""Run Jarvis.

    python -m jarvis              voice mode (say "Jarvis")
    python -m jarvis --text       type instead of speaking
    pythonw -m jarvis             run silently in the background (Windows; output goes to ~/.jarvis.log)
    python -m jarvis --stop       stop a Jarvis running in the background
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path

from .ai import make_brain
from .brain import Brain, redact
from .config import Config
from .screen import make_dpi_aware
from .voice import Listener, Speaker, list_microphones

# Jarvis listens on this local port so only one copy runs, and so `--stop` can reach it.
CONTROL_PORT = 47631
LOG_FILE = Path.home() / ".jarvis.log"


def voice_loop(brain: Brain, speaker: Speaker, listener: Listener, always_awake: bool = False) -> None:
    name = brain.config.name
    if always_awake:
        print("Listening... just speak (no wake word needed). Ctrl+C to quit.")
    else:
        print(f'Listening... say "{name}" to start a conversation, or "Hey {name}, <command>". Ctrl+C to quit.')

    def say(text: str) -> None:
        listener.mute()  # what's heard now is checked only for "stop" (and our own echo is ignored)
        try:
            if not speaker.say(text, interrupted=lambda: stop_requested(listener, text)):
                print("(stopped talking)")
        finally:
            listener.unmute()

    # In a conversation Jarvis answers without hearing its name, until you're quiet for a while or say "bye".
    in_conversation = always_awake
    last_activity = time.time()
    while True:
        for notice in brain.pop_notices():  # e.g. "Docker finished installing"
            say(notice)
        heard = listener.listen(timeout=0.5)
        if heard is None:
            if in_conversation and not always_awake and time.time() - last_activity > brain.config.conversation_timeout:
                print(f'(conversation ended; say "{name}" when you need me)')
                in_conversation = False
            continue
        print(f"You: {redact(heard)}")
        addressed, command = brain.strip_wake_word(heard)
        if not (addressed or in_conversation):
            print(f'(no "{name}" heard, ignoring)')
            continue
        begun = time.time()
        if addressed and not command:
            say(greeting(brain))
            in_conversation = True
            last_activity = time.time()
            continue
        # Anything slower than a few seconds (a slow AI, a big screen to read) gets a "One moment" so it
        # never seems stuck.
        holding = threading.Timer(4.0, lambda: say("One moment."))
        holding.daemon = True
        holding.start()
        try:
            response = brain.handle(command)
        finally:
            holding.cancel()
        print(f"(answered in {time.time() - begun:.1f}s)")
        if response.quiet and brain.config.quiet_actions:
            print(f"(done: {response.text})")
        else:
            say(response.text)
        last_activity = time.time()
        if response.exit:
            return
        in_conversation = always_awake or not response.sleep


STOP_WORDS = re.compile(r"^(?:(?:ok(?:ay)?|hey|jarvis)[\s,]+)*(?:stop|be quiet|quiet|shut up|enough|cancel|"
                        r"pause|hold on|wait|silence|that's enough)(?:[\s,]+(?:stop|it|talking|jarvis|please|now|"
                        r"there))*[.!]*$", re.I)


def stop_requested(listener, speaking: str) -> bool:
    """Did the user say "stop" (or similar) while Jarvis was talking? Jarvis's own voice doesn't count."""
    heard = listener.heard_while_speaking()
    if not heard:
        return False
    if STOP_WORDS.match(heard.strip()):
        print(f"(heard \"{heard}\" while talking)")
        return True
    return False


def greeting(brain: Brain) -> str:
    """What Jarvis says when you just say its name: Claude opens a conversation if available."""
    start = getattr(brain.fallback, "start_conversation", None)
    if start is not None:
        try:
            opener = start()
            if opener:
                return opener
        except Exception as e:
            print(f"(error: {e!r})")
    return f"Yes, {brain.title}?"


def text_loop(brain: Brain, speaker: Speaker) -> None:
    print(f"Type to {brain.config.name} (the wake word is optional). Ctrl+C or 'exit' to quit.")
    while True:
        try:
            line = input("You: ")
        except EOFError:
            return
        addressed, command = brain.strip_wake_word(line)
        if addressed and not command:
            speaker.say(greeting(brain))
            continue
        response = brain.handle(command)
        if response.quiet and brain.config.quiet_actions:
            print(f"(done: {response.text})")
        else:
            speaker.say(response.text)
        if response.exit or response.sleep:
            return


def claim_single_instance() -> socket.socket | None:
    """Bind the control port. Returns None if another Jarvis already has it."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", CONTROL_PORT))
    except OSError:
        sock.close()
        return None
    sock.listen(1)

    def serve():
        while True:
            conn, _ = sock.accept()
            with conn:
                if conn.recv(16).strip() == b"stop":
                    conn.sendall(b"ok")
                    print("(stopped by --stop)")
                    os._exit(0)

    threading.Thread(target=serve, daemon=True).start()
    return sock


def stop_running_instance() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", CONTROL_PORT), timeout=3) as conn:
            conn.sendall(b"stop")
            return conn.recv(16) == b"ok"
    except OSError:
        return False


class Tee:
    """Write to the console and the log file at once."""

    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]

    def write(self, text):
        for s in self.streams:
            try:
                s.write(text)
                s.flush()
            except Exception:
                pass
        return len(text)

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass


def rotate_log(max_bytes: int = 1_000_000, keep: int = 3) -> None:
    """When the log passes ~1 MB, keep it as .jarvis.log.1 (older ones shift to .2, .3) and start afresh."""
    if not LOG_FILE.exists() or LOG_FILE.stat().st_size <= max_bytes:
        return
    for n in range(keep, 0, -1):
        older = LOG_FILE.with_name(f"{LOG_FILE.name}.{n}")
        newer = LOG_FILE.with_name(f"{LOG_FILE.name}.{n - 1}") if n > 1 else LOG_FILE
        if newer.exists():
            if older.exists():
                older.unlink()
            newer.rename(older)


def log_to_file() -> None:
    """Everything Jarvis prints also goes to ~/.jarvis.log (kept under ~1 MB), so `--logs` can show it live
    in another window. With pythonw there's no console, so it only goes to the file."""
    try:
        rotate_log()
        log = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    log.write(f"\n===== Jarvis started {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    sys.stdout = Tee(sys.stdout, log)
    sys.stderr = Tee(sys.stderr, log)


def dump_window() -> None:
    """For fixing an app Jarvis struggles with: everything UI Automation sees in the window in front."""
    from .screen import foreground_title, make_dpi_aware, screen_elements

    make_dpi_aware()
    print("Switch to the window you want (e.g. WhatsApp) now; reading it in 5 seconds...")
    time.sleep(5)
    elements = screen_elements(max_items=2000, time_limit=30)
    lines = [f"Window: {foreground_title()}  ({len(elements)} items)"]
    lines += [f"{e.kind:12s} x={e.x:5d} y={e.y:5d}  {e.name}" for e in elements]
    out = Path.home() / "jarvis-window-dump.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:80]))
    print(f"\n(Full list saved to {out}; paste it to whoever is fixing Jarvis.)")


def follow_log() -> None:
    """Show the log live, like a second window into what Jarvis is doing."""
    print(f"Showing {LOG_FILE} live. Ctrl+C to stop.\n")
    try:
        with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            print("".join(lines[-40:]), end="")
            while True:
                line = f.readline()
                if line:
                    print(line, end="", flush=True)
                else:
                    time.sleep(0.3)
    except FileNotFoundError:
        print("No log yet: start Jarvis first.")
    except KeyboardInterrupt:
        pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="Your personal J.A.R.V.I.S.")
    parser.add_argument("--text", action="store_true", help="type commands instead of speaking")
    parser.add_argument("--mute", action="store_true", help="print replies instead of speaking them")
    parser.add_argument("--no-wake", action="store_true", help='respond to everything, no "Jarvis" needed')
    parser.add_argument("--dry-run", action="store_true", help="don't actually shut down / restart / sleep")
    parser.add_argument("--background", action="store_true", help="log to ~/.jarvis.log instead of the console")
    parser.add_argument("--stop", action="store_true", help="stop a Jarvis running in the background")
    parser.add_argument("--dump-window", action="store_true",
                        help="after 5 seconds, list everything Jarvis can see in the window in front")
    parser.add_argument("--details", action="store_true", help="type in your email, phone, name... once")
    parser.add_argument("--setup-email", action="store_true", help="connect your Gmail (app password)")
    parser.add_argument("--logs", action="store_true", help="show what Jarvis is doing, live (run in a second window)")
    parser.add_argument("--list-mics", action="store_true", help="list microphones (for the mic_index setting)")
    args = parser.parse_args(argv)
    from .config import load_env_files

    load_env_files()

    if args.stop:
        print("Jarvis stopped." if stop_running_instance() else "Jarvis isn't running.")
        return
    if args.dump_window:
        dump_window()
        return
    if args.details:
        from .config import edit_details_interactive

        edit_details_interactive()
        return
    if args.setup_email:
        from .messaging import setup_email_interactive

        setup_email_interactive()
        return
    if args.logs:
        follow_log()
        return
    if args.list_mics:
        for i, mic in enumerate(list_microphones()):
            print(f"{i}: {mic}")
        return

    make_dpi_aware()
    background = args.background or sys.stdout is None  # pythonw.exe has no stdout
    log_to_file()

    lock = claim_single_instance()
    if lock is None:
        print("Jarvis is already running. Use `python -m jarvis --stop` to stop it.")
        return

    config = Config()
    if args.dry_run:
        config.dry_run = True
    ai = make_brain(config)
    brain = Brain(config, fallback=ai)
    speaker = Speaker(config.name, mute=args.mute, engine=config.tts_engine, voice=config.tts_voice,
                      rate=config.tts_rate)
    if ai is None:
        print("(No AI brain set up, so only built-in commands work. For a free one, add a Gemini key "
              "(\"gemini_api_key\" in ~/.jarvis.json) or install Ollama. See the README.)")
    else:
        print(f"(AI brain: {ai.names})")

    listener = None
    if not args.text:
        # Right after login the microphone may not be ready yet, so keep trying for a minute in the background.
        for attempt in range(12 if background else 1):
            try:
                listener = Listener(config.language, config.mic_sensitivity, config.mic_index,
                                    engine=config.stt_engine, whisper_model=config.whisper_model)
                break
            except Exception as e:
                print(f"(Microphone unavailable: {e!r})")
                if background:
                    time.sleep(5)
        if listener is None:
            if background:
                return  # no console to fall back to
            print("(Falling back to text mode.)")

    speaker.say(f"{config.name} online. At your service, {config.user_title}.")
    try:
        if listener is not None:
            voice_loop(brain, speaker, listener, always_awake=args.no_wake or config.always_listen)
        else:
            text_loop(brain, speaker)
    except KeyboardInterrupt:
        print()
        speaker.say(f"Powering down. Goodbye, {config.user_title}.")


if __name__ == "__main__":
    main()
