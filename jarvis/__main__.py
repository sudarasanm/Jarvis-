"""Run Jarvis.

    python -m jarvis              voice mode (say "Jarvis")
    python -m jarvis --text       type instead of speaking
    pythonw -m jarvis             run silently in the background (Windows; output goes to ~/.jarvis.log)
    python -m jarvis --stop       stop a Jarvis running in the background
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
from pathlib import Path

from .ai import make_brain
from .brain import Brain
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
        listener.mute()  # don't hear ourselves
        try:
            speaker.say(text)
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
        print(f"You: {heard}")
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
        response = brain.handle(command)
        print(f"(answered in {time.time() - begun:.1f}s)")
        say(response.text)
        last_activity = time.time()
        if response.exit:
            return
        in_conversation = always_awake or not response.sleep


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


def redirect_output_to_log() -> None:
    """pythonw has no console; send output to ~/.jarvis.log instead (kept under ~1 MB)."""
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 1_000_000:
            LOG_FILE.unlink()
        log = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    sys.stdout = sys.stderr = log


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="Your personal J.A.R.V.I.S.")
    parser.add_argument("--text", action="store_true", help="type commands instead of speaking")
    parser.add_argument("--mute", action="store_true", help="print replies instead of speaking them")
    parser.add_argument("--no-wake", action="store_true", help='respond to everything, no "Jarvis" needed')
    parser.add_argument("--dry-run", action="store_true", help="don't actually shut down / restart / sleep")
    parser.add_argument("--background", action="store_true", help="log to ~/.jarvis.log instead of the console")
    parser.add_argument("--stop", action="store_true", help="stop a Jarvis running in the background")
    parser.add_argument("--list-mics", action="store_true", help="list microphones (for the mic_index setting)")
    args = parser.parse_args(argv)

    if args.stop:
        print("Jarvis stopped." if stop_running_instance() else "Jarvis isn't running.")
        return
    if args.list_mics:
        for i, mic in enumerate(list_microphones()):
            print(f"{i}: {mic}")
        return

    make_dpi_aware()
    background = args.background or sys.stdout is None  # pythonw.exe has no stdout
    if background:
        redirect_output_to_log()

    lock = claim_single_instance()
    if lock is None:
        print("Jarvis is already running. Use `python -m jarvis --stop` to stop it.")
        return

    config = Config()
    if args.dry_run:
        config.dry_run = True
    ai = make_brain(config)
    brain = Brain(config, fallback=ai)
    speaker = Speaker(config.name, mute=args.mute)
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
                listener = Listener(config.language, config.mic_sensitivity, config.mic_index)
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
