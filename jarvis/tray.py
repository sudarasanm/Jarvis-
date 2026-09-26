"""The glowing circle in the taskbar tray: its colour shows what Jarvis is doing, its menu controls it.

    blue    waiting for "Hey Jarvis"          cyan    listening (in a conversation)
    amber   thinking                           purple  doing something (opening, clicking, typing)
    green   speaking                           grey    muted (only "Hey Jarvis" wakes it)
    red     microphone off (privacy)
"""

from __future__ import annotations

import os

from .state import LOG_DIR, state

COLOURS = {
    "idle": (30, 120, 255),
    "listening": (0, 220, 255),
    "thinking": (255, 176, 0),
    "acting": (170, 90, 255),
    "speaking": (40, 220, 110),
    "muted": (130, 130, 130),
    "mic_off": (230, 40, 40),
}
LABELS = {
    "idle": 'waiting for "Hey Jarvis"', "listening": "listening", "thinking": "thinking", "acting": "working",
    "speaking": "speaking", "muted": "muted", "mic_off": "microphone off",
}


def circle(colour: tuple[int, int, int], size: int = 64):
    """A glowing dot: a soft halo around a bright core."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    r, g, b = colour
    for i, alpha in enumerate((50, 90, 140)):
        pad = 2 + i * 5
        draw.ellipse((pad, pad, size - pad, size - pad), fill=(r, g, b, alpha))
    core = size // 4 + 4
    draw.ellipse((core, core, size - core, size - core), fill=(min(r + 60, 255), min(g + 60, 255),
                                                               min(b + 60, 255), 255))
    return image


def open_logs() -> None:
    log = LOG_DIR / "jarvis.log"
    try:
        os.startfile(str(log if log.exists() else LOG_DIR))  # type: ignore[attr-defined]
    except Exception as e:
        print(f"(couldn't open the logs: {e!r})")


class Tray:
    def __init__(self, name: str = "Jarvis"):
        import pystray

        self.name = name
        self.pystray = pystray
        item, menu = pystray.MenuItem, pystray.Menu
        self.icon = pystray.Icon(
            name.lower(), circle(COLOURS["idle"]), self.title(),
            menu=menu(
                item("Listen now", lambda: state.listen_now.set(), default=True),
                item("Mute (only \"Hey Jarvis\" wakes me)", lambda: state.set_muted(not state.muted),
                     checked=lambda _: state.muted),
                item("Microphone off (privacy)", lambda: state.set_mic_off(not state.mic_off),
                     checked=lambda _: state.mic_off),
                item("Open logs", open_logs),
                menu.SEPARATOR,
                item(f"Exit {name}", self.exit),
            ))
        self._shown = None
        state.watch(self.update)

    def title(self) -> str:
        return f"{self.name}: {LABELS.get(state.shown, state.shown)}"

    def update(self, _state=None) -> None:
        shown = state.shown
        if shown == self._shown:
            return
        self._shown = shown
        try:
            self.icon.icon = circle(COLOURS.get(shown, COLOURS["idle"]))
            self.icon.title = self.title()
            self.icon.update_menu()
        except Exception:
            pass

    def exit(self) -> None:
        state.exit_requested.set()

    def start(self) -> None:
        self.icon.run_detached()

    def stop(self) -> None:
        try:
            self.icon.stop()
        except Exception:
            pass


def start_tray(name: str) -> Tray | None:
    try:
        tray = Tray(name)
        tray.start()
    except Exception as e:
        print(f"(tray icon unavailable: {e!r})")
        return None
    return tray
