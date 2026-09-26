"""Run Jarvis: `python -m jarvis` (voice) or `python -m jarvis --text` (keyboard)."""

from __future__ import annotations

import argparse

from .ai import make_fallback
from .brain import Brain
from .config import Config
from .voice import Listener, Speaker


def voice_loop(brain: Brain, speaker: Speaker, listener: Listener) -> None:
    print(f'Listening... say "Hey {brain.config.name}" followed by a command. Ctrl+C to quit.')
    awake = False  # True right after the wake word, or while a yes/no confirmation is pending
    while True:
        heard = listener.listen(timeout=8 if awake else None)
        if heard is None:
            awake = False
            continue
        print(f"You: {heard}")
        addressed, command = brain.strip_wake_word(heard)
        if not (addressed or awake):
            continue  # not talking to us
        if addressed and not command:
            speaker.say(f"Yes, {brain.title}?")
            awake = True
            continue
        response = brain.handle(command)
        speaker.say(response.text)
        if response.exit:
            return
        awake = response.on_confirm is not None


def text_loop(brain: Brain, speaker: Speaker) -> None:
    print(f"Type a command for {brain.config.name} (the wake word is optional). Ctrl+C or 'exit' to quit.")
    while True:
        try:
            line = input("You: ")
        except EOFError:
            return
        _, command = brain.strip_wake_word(line)
        response = brain.handle(command)
        speaker.say(response.text)
        if response.exit:
            return


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description="Your personal J.A.R.V.I.S.")
    parser.add_argument("--text", action="store_true", help="type commands instead of speaking")
    parser.add_argument("--mute", action="store_true", help="print replies instead of speaking them")
    parser.add_argument("--dry-run", action="store_true", help="don't actually shut down / restart / sleep")
    args = parser.parse_args(argv)

    config = Config()
    if args.dry_run:
        config.dry_run = True
    fallback = make_fallback(config)
    brain = Brain(config, fallback=fallback)
    speaker = Speaker(config.name, mute=args.mute)
    if fallback is None:
        print("(Claude fallback disabled: install `anthropic` and set ANTHROPIC_API_KEY to enable it.)")

    listener = None
    if not args.text:
        try:
            listener = Listener()
        except Exception as e:
            print(f"(Microphone unavailable: {e}. Falling back to text mode.)")

    speaker.say(f"{config.name} online. At your service, {config.user_title}.")
    try:
        if listener is not None:
            voice_loop(brain, speaker, listener)
        else:
            text_loop(brain, speaker)
    except KeyboardInterrupt:
        print()
        speaker.say(f"Powering down. Goodbye, {config.user_title}.")


if __name__ == "__main__":
    main()
