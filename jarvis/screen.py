"""See and touch the screen: list and switch windows, read the front window's buttons, links
and text, click things by name, scroll, and take screenshots for the AI to look at.

Reading and clicking by name use Windows UI Automation (the accessibility layer screen readers
use), which gives exact button names and positions. When that can't find something (images,
video tiles, some web pages), Jarvis falls back to looking at a screenshot with vision.py.
"""

from __future__ import annotations

import io
import platform
import re
import time
from dataclasses import dataclass

SYSTEM = platform.system()

INTERACTIVE = {"Button", "Hyperlink", "MenuItem", "TabItem", "ListItem", "CheckBox", "RadioButton",
               "Edit", "ComboBox", "TreeItem", "SplitButton", "DataItem"}
READABLE = INTERACTIVE | {"Text", "Header", "HeaderItem"}

# Windows that aren't really "open windows" from the user's point of view.
HIDDEN_WINDOWS = {"program manager", "windows input experience", "settings", "microsoft text input application"}


def make_dpi_aware() -> None:
    """Use real pixels everywhere, so screenshots, UI positions and clicks line up on scaled displays."""
    if SYSTEM != "Windows":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


@dataclass
class Element:
    kind: str
    name: str
    x: int
    y: int

    def __str__(self) -> str:
        return f"{self.kind}: {self.name}"


# --- windows -------------------------------------------------------------------------------------

def _windows():
    import pygetwindow  # installed with pyautogui on Windows

    wins = []
    for w in pygetwindow.getAllWindows():
        title = (w.title or "").strip()
        if not title or title.lower() in HIDDEN_WINDOWS or not getattr(w, "visible", True):
            continue
        if getattr(w, "width", 1) <= 0 or getattr(w, "height", 1) <= 0:
            continue
        wins.append(w)
    return wins


def list_windows() -> str:
    if SYSTEM != "Windows":
        return "Listing windows only works on Windows for now."
    titles = list(dict.fromkeys(w.title.strip() for w in _windows()))
    if not titles:
        return "No windows are open."
    return "Open windows: " + "; ".join(titles)


def switch_to_window(name: str) -> str:
    if SYSTEM != "Windows":
        return "Switching windows only works on Windows for now."
    wanted = name.lower().strip()
    matches = [w for w in _windows() if wanted in w.title.lower()]
    if not matches:
        return f"I can't see a window called {name}."
    win = matches[0]
    try:
        if getattr(win, "isMinimized", False):
            win.restore()
        win.activate()
    except Exception:
        # Windows only lets the foreground app hand over focus; tapping Alt counts as user input.
        import pyautogui

        pyautogui.press("alt")
        try:
            win.activate()
        except Exception:
            pass
    time.sleep(0.5)
    return f"Switched to {win.title.strip()}."


# --- reading the front window ----------------------------------------------------------------------

def foreground_title() -> str:
    try:
        import pygetwindow

        w = pygetwindow.getActiveWindow()
        return (w.title or "").strip() if w else ""
    except Exception:
        return ""


def screen_elements(max_items: int = 200, time_limit: float = 5.0) -> list[Element]:
    """Visible buttons, links, list items and text in the front window, with their centres."""
    import uiautomation as auto

    root = auto.GetForegroundControl()
    if root is None:
        return []
    elements: list[Element] = []
    seen = set()
    start = time.time()
    for control, _depth in auto.WalkControl(root, maxDepth=40):
        if len(elements) >= max_items or time.time() - start > time_limit:
            break
        try:
            kind = re.sub(r"Control$", "", control.ControlTypeName)
            if kind not in READABLE:
                continue
            name = " ".join((control.Name or "").split())
            if not name or control.IsOffscreen:
                continue
            rect = control.BoundingRectangle
            if rect.width() <= 0 or rect.height() <= 0:
                continue
            key = (kind, name, rect.xcenter() // 8, rect.ycenter() // 8)
            if key in seen:
                continue
            seen.add(key)
            elements.append(Element(kind, name[:150], rect.xcenter(), rect.ycenter()))
        except Exception:
            continue
    return elements


def read_screen() -> str:
    """A text summary of the front window that the AI can read."""
    if SYSTEM != "Windows":
        return "Reading the window only works on Windows. Use look_at_screen instead."
    try:
        elements = screen_elements()
    except Exception as e:
        return f"Couldn't read the window ({e}). Use look_at_screen instead."
    title = foreground_title()
    if not elements:
        return f"Front window: {title}. I couldn't read its contents; use look_at_screen to see it."
    lines = [f"Front window: {title}"] + [f"- {e}" for e in elements]
    return "\n".join(lines)


# --- clicking ------------------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


def find_element(target: str, elements: list[Element]) -> Element | None:
    """Best match by name: exact, then starts-with, then contains. Clickable things win ties."""
    wanted = _norm(target)
    if not wanted:
        return None
    for test in (lambda n: n == wanted, lambda n: n.startswith(wanted), lambda n: wanted in n):
        hits = [e for e in elements if test(_norm(e.name))]
        if hits:
            clickable = [e for e in hits if e.kind in INTERACTIVE]
            return (clickable or hits)[0]
    return None


def click_point(x: int, y: int, double: bool = False, right: bool = False) -> None:
    import pyautogui

    pyautogui.click(x, y, clicks=2 if double else 1, interval=0.1, button="right" if right else "left")


def click(target: str, double: bool = False, right: bool = False, locate=None) -> str:
    """Click something on screen by its visible name.

    locate: optional fallback(description) -> (x, y) or None, e.g. vision.locate, used when the
    accessibility layer can't find it.
    """
    what = "Double-clicked" if double else "Right-clicked" if right else "Clicked"
    element = None
    if SYSTEM == "Windows":
        try:
            element = find_element(target, screen_elements())
        except Exception as e:
            print(f"(UI Automation failed: {e!r})")
    if element is not None:
        click_point(element.x, element.y, double, right)
        return f"{what} {element.kind.lower()} '{element.name}'."
    if locate is not None:
        point = locate(target)
        if point is not None:
            click_point(point[0], point[1], double, right)
            return f"{what} what looked like {target}."
    return f"I couldn't find {target} on the screen."


def scroll(direction: str = "down", amount: str = "normal") -> str:
    import pyautogui

    clicks = {"little": 3, "normal": 8, "lot": 20}.get(amount, 8)
    pyautogui.scroll(clicks * 120 if direction == "up" else -clicks * 120)
    return f"Scrolled {direction}."


# --- screenshots ---------------------------------------------------------------------------------

def screenshot_jpeg(max_width: int = 1600, quality: int = 70) -> tuple[bytes, tuple[int, int]]:
    """Primary-screen screenshot as JPEG bytes, plus the real screen size in pixels."""
    from PIL import ImageGrab

    image = ImageGrab.grab()
    size = image.size
    if image.width > max_width:
        image = image.resize((max_width, round(image.height * max_width / image.width)))
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue(), size
