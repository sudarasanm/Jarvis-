"""Run Jarvis: `python -m jarvis` (voice) or `python -m jarvis --text` (keyboard)."""

from __future__ import annotations

import argparse

from .ai import make_fallback
from .brain import Brain
from .config import Config
from .voice import Listener, Speaker


def voice_loop(brain: Brain, speaker: Speaker, listener: Listener, always_awake: bool = False) -> None:
    if always_awake:
        print("Listening... just speak a command (no wake word needed). Ctrl+C to quit.")
    else:
        print(f'Listening... say "Hey {brain.config.name}" followed by a command. Ctrl+C to quit.')
    awake = always_awake  # True right after the wake word, or while Jarvis is waiting for an answer
    while True:
        heard = listener.listen(timeout=8 if awake else None)
        if heard is None:
            awake = always_awake
            continue
        print(f"You: {heard}")
        addressed, command = brain.strip_wake_word(heard)
        if not (addressed or awake):
            print(f'(no "{brain.config.name}" heard, ignoring. Start with "Hey {brain.config.name}", '
                  "or run with --no-wake)")
            continue
        if addressed and not command:
            speaker.say(f"Yes, {brain.title}?")
            awake = True
            continue
        response = brain.handle(command)
        speaker.say(response.text)
        if response.exit:
            return
        awake = always_awake or brain.awaiting_reply


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
    parser.add_argument("--no-wake", action="store_true", help='respond to everything, no "Hey Jarvis" needed')
    parser.add_argument("--dry-run", action="store_true", help="don't actually shut down / restart / sleep")
    args = parser.parse_args(argv)

    config = Config()
    if args.dry_run:
        config.dry_run = True
    fallback = make_fallback(config)
    brain = Brain(config, fallback=fallback)
    speaker = Speaker(config.name, mute=args.mute)
    if fallback is None:
        print("(Claude answers are off: set ANTHROPIC_API_KEY so I can answer general questions.)")

    listener = None
    if not args.text:
        try:
            listener = Listener()
        except Exception as e:
            print(f"(Microphone unavailable: {e}. Falling back to text mode.)")

    speaker.say(f"{config.name} online. At your service, {config.user_title}.")
    try:
        if listener is not None:
            voice_loop(brain, speaker, listener, always_awake=args.no_wake)
        else:
            text_loop(brain, speaker)
    except KeyboardInterrupt:
        print()
        speaker.say(f"Powering down. Goodbye, {config.user_title}.")


if __name__ == "__main__":
    main()
