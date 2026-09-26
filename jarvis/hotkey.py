"""Push-to-talk: a global keyboard shortcut (Ctrl+Alt+J by default) that makes Jarvis listen right away."""

from __future__ import annotations

from .state import state


def start_hotkey(keys: str) -> bool:
    """Returns False (and Jarvis carries on without it) if the shortcut can't be registered."""
    if not keys:
        return False
    try:
        import keyboard

        keyboard.add_hotkey(keys, state.listen_now.set)
    except Exception as e:
        print(f"(push-to-talk {keys} unavailable: {e!r})")
        return False
    print(f"(push-to-talk: {keys})")
    return True
