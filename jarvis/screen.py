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
HIDDEN_WINDOWS = {"program manager", "windows input experience", "microsoft text input application"}

# How each browser ends its window titles ("Gmail - Google Chrome").
BROWSER_TITLES = {"chrome": "google chrome", "brave": "brave", "edge": "microsoft edge", "firefox": "mozilla firefox"}
# Spoken names for windows whose titles say something else.
WINDOW_ALIASES = {"system settings": "settings", "windows settings": "settings", "pc settings": "settings",
                  "terminal": "powershell", "command prompt": "command prompt", "vs code": "visual studio code"}
BROWSER_NAMES = {"chrome": "chrome", "google chrome": "chrome", "brave": "brave", "brave browser": "brave",
                 "edge": "edge", "microsoft edge": "edge", "firefox": "firefox", "mozilla firefox": "firefox"}


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

def _own_console() -> int:
    """Handle of the console window Jarvis runs in (0 if none), so it never closes itself."""
    try:
        import ctypes

        return int(ctypes.windll.kernel32.GetConsoleWindow() or 0)
    except Exception:
        return 0


def _windows():
    import pygetwindow  # installed with pyautogui on Windows

    own = _own_console()
    wins = []
    for w in pygetwindow.getAllWindows():
        if own and getattr(w, "_hWnd", None) == own:
            continue
        title = (w.title or "").strip()
        if not title or title.lower() in HIDDEN_WINDOWS or not getattr(w, "visible", True):
            continue
        if getattr(w, "width", 1) <= 0 or getattr(w, "height", 1) <= 0:
            continue
        wins.append(w)
    return wins


def clean_title(title: str) -> str:
    return " ".join((title or "").replace("\u200b", "").split())


def browser_of(title: str) -> str | None:
    """'Gmail - Google Chrome' -> 'chrome'."""
    low = clean_title(title).lower()
    for key, suffix in BROWSER_TITLES.items():
        if low == suffix or low.endswith(" - " + suffix):
            return key
    return None


def matching_windows(name: str) -> list:
    """Open windows the user could mean by `name`.

    A browser window only matches the browser's own name: "close Ollama" must not close Chrome just
    because Chrome is showing an Ollama tab. Tabs are handled by close_tab().
    """
    wanted = _norm(name)
    wanted = WINDOW_ALIASES.get(wanted, wanted)
    browser = BROWSER_NAMES.get(wanted)
    found = []
    for w in _windows():
        title = clean_title(w.title)
        in_browser = browser_of(title)
        if in_browser is not None:
            if in_browser == browser:
                found.append(w)
        elif wanted and wanted in _norm(title):
            found.append(w)
    return found


def activate(win) -> None:
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
    time.sleep(0.4)


# The app the user is working in: set whenever Jarvis opens or switches to something, so typing and clicks
# keep going there.
_working = {"name": None}
CONSOLE_HINTS = ("powershell", "command prompt", "python", "windows terminal", "jarvis")


def remember_app(name: str | None) -> None:
    if name:
        _working["name"] = name


def working_app() -> str | None:
    return _working["name"]


def ensure_focus() -> None:
    """If Jarvis's own console window came to the front, put the user's app back in front before typing."""
    name = _working["name"]
    if SYSTEM != "Windows" or not name or any(h in name.lower() for h in CONSOLE_HINTS):
        return
    try:
        import pygetwindow

        front = pygetwindow.getActiveWindow()
        title = clean_title(front.title).lower() if front is not None else ""
        own = _own_console()
        is_console = (own and getattr(front, "_hWnd", None) == own) or any(h in title for h in CONSOLE_HINTS)
        if front is not None and not is_console:
            return
        wins = matching_windows(name)
        if wins:
            activate(wins[0])
    except Exception:
        pass


def list_windows() -> str:
    if SYSTEM != "Windows":
        return "Listing windows only works on Windows for now."
    titles = list(dict.fromkeys(clean_title(w.title) for w in _windows()))
    if not titles:
        return "No windows are open."
    return "Open windows: " + "; ".join(titles)


def switch_to_window(name: str) -> str:
    if SYSTEM != "Windows":
        return "Switching windows only works on Windows for now."
    matches = matching_windows(name)
    if not matches:
        wanted = _norm(name)
        matches = [w for w in _windows() if wanted and wanted in _norm(w.title)]
    if not matches:
        tab = find_tab(name)
        if tab is not None:
            return switch_to_tab(name)
        return f"I can't see a window called {name}."
    win = matches[0]
    activate(win)
    remember_app(browser_of(win.title) or name)
    return f"Switched to {clean_title(win.title)}."


# --- reading the front window ----------------------------------------------------------------------

def foreground_title() -> str:
    try:
        import pygetwindow

        w = pygetwindow.getActiveWindow()
        return clean_title(w.title) if w else ""
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
    ensure_focus()
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


# Buttons that make a popup, banner or dialog go away without doing anything, best first.
DISMISS_BUTTONS = ["not now", "no thanks", "no, thanks", "maybe later", "skip", "dismiss", "got it", "close",
                   "close dialog", "close popup", "\u00d7", "\u2715", "x", "cancel", "later", "remind me later"]


def _window_rect():
    import uiautomation as auto

    root = auto.GetForegroundControl()
    return root.BoundingRectangle if root is not None else None


def dismiss_popup(locate=None) -> str:
    """Close the popup/dialog/banner in front, without closing the window behind it."""
    import pyautogui

    if SYSTEM == "Windows":
        try:
            elements = [e for e in screen_elements() if e.kind in ("Button", "Hyperlink", "SplitButton")]
            rect = _window_rect()
        except Exception as e:
            print(f"(UI Automation failed: {e!r})")
            elements, rect = [], None

        def is_caption_button(e: Element) -> bool:
            # The window's own minimise/maximise/close buttons sit in the top-right corner.
            return rect is not None and e.y < rect.top + 50 and e.x > rect.right - 200

        for wanted in DISMISS_BUTTONS:
            for e in elements:
                if _norm(e.name) == _norm(wanted) and not is_caption_button(e):
                    click_point(e.x, e.y)
                    return f"Dismissed it with '{e.name}'."
    if locate is not None:
        point = locate("the button that closes or dismisses the popup, dialog or banner (an X, Close, "
                       "Not now or No thanks), not the window's own close button")
        if point is not None:
            click_point(*point)
            return "Closed the popup."
    pyautogui.press("esc")
    return "I pressed Escape, which closes most popups. Is it gone?"


def close_front_window() -> str:
    try:
        import pygetwindow

        win = pygetwindow.getActiveWindow()
    except Exception:
        win = None
    if win is None or not (win.title or "").strip():
        return "There's no window in front to close."
    title = clean_title(win.title)
    win.close()
    return f"Closed {title}."


def scroll(direction: str = "down", amount: str = "normal") -> str:
    import pyautogui

    ensure_focus()
    clicks = {"little": 3, "normal": 8, "lot": 20}.get(amount, 8)
    pyautogui.scroll(clicks * 120 if direction == "up" else -clicks * 120)
    return f"Scrolled {direction}."


# --- browser tabs --------------------------------------------------------------------------------

@dataclass
class Tab:
    browser: str
    title: str
    window: object
    x: int
    y: int


TAB_NOISE = re.compile(r"\s+-\s+(memory usage\b.*|audio playing|pinned|network error.*|crashed|"
                       r"this tab is playing (audio|media).*)$", re.I)


def clean_tab_title(name: str) -> str:
    name = clean_title(name)
    while True:
        cleaned = TAB_NOISE.sub("", name)
        if cleaned == name:
            return name
        name = cleaned


def _walk(control, max_depth: int, skip=("DocumentControl",)):
    """Depth-first walk that doesn't descend into web page content (much faster in browsers)."""
    stack = [(child, 1) for child in reversed(control.GetChildren())]
    while stack:
        node, depth = stack.pop()
        yield node
        try:
            if depth < max_depth and node.ControlTypeName not in skip:
                stack.extend((child, depth + 1) for child in reversed(node.GetChildren()))
        except Exception:
            continue


def _window_control(win):
    import uiautomation as auto

    try:
        control = auto.ControlFromHandle(int(win._hWnd))
        if control is not None:
            return control
    except Exception:
        pass
    activate(win)
    return auto.GetForegroundControl()


def browser_tabs(browser: str | None = None) -> list[Tab]:
    """Every tab in every open browser window (optionally one browser), in tab-strip order."""
    if SYSTEM != "Windows":
        return []
    browser = BROWSER_NAMES.get(_norm(browser), browser) if browser else None
    tabs = []
    for win in _windows():
        which = browser_of(win.title)
        if which is None or (browser and which != browser):
            continue
        start = time.time()
        for control in _walk(_window_control(win), max_depth=16):
            if time.time() - start > 3:
                break
            try:
                if control.ControlTypeName != "TabItemControl":
                    continue
                title = clean_tab_title(control.Name or "")
                rect = control.BoundingRectangle
                if title and rect.width() > 0:
                    tabs.append(Tab(which, title, win, rect.xcenter(), rect.ycenter()))
            except Exception:
                continue
    return tabs


def list_tabs(browser: str | None = None) -> str:
    if SYSTEM != "Windows":
        return "Listing tabs only works on Windows for now."
    tabs = browser_tabs(browser)
    if not tabs:
        return f"I can't see any {browser + ' ' if browser else ''}tabs open."
    by_browser: dict[str, list[str]] = {}
    for t in tabs:
        by_browser.setdefault(t.browser, []).append(t.title)
    names = {"chrome": "Chrome", "brave": "Brave", "edge": "Edge", "firefox": "Firefox"}
    return " ".join(f"{names[b]} has {len(ts)} tab{'s' if len(ts) != 1 else ''}: " + "; ".join(ts) + "."
                    for b, ts in by_browser.items())


def find_tab(title: str, browser: str | None = None) -> Tab | None:
    wanted = _norm(re.sub(r"\btabs?\b", "", title, flags=re.I))
    if not wanted or SYSTEM != "Windows":
        return None
    try:
        tabs = browser_tabs(browser)
    except Exception:
        return None
    for test in (lambda n: n == wanted, lambda n: n.startswith(wanted), lambda n: wanted in n):
        for t in tabs:
            if test(_norm(t.title)):
                return t
    words = wanted.split()
    for t in tabs:  # every word present, in any order: "claude api keys" -> "API keys | Claude Platform"
        if len(words) > 1 and all(w in _norm(t.title) for w in words):
            return t
    return None


def switch_to_tab(title: str, browser: str | None = None) -> str:
    tab = find_tab(title, browser)
    if tab is None:
        return f"I can't find a tab called {title}."
    activate(tab.window)
    click_point(tab.x, tab.y)
    remember_app(tab.browser)
    return f"Switched to the {tab.title} tab."


def close_tab(title: str, browser: str | None = None) -> str:
    tab = find_tab(title, browser)
    if tab is None:
        return f"I can't find a tab called {title}."
    import pyautogui

    activate(tab.window)
    click_point(tab.x, tab.y)
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "w")
    time.sleep(0.6)
    still_there = any(t.title == tab.title and t.window == tab.window for t in browser_tabs(tab.browser))
    if still_there:
        return f"I tried to close the {tab.title} tab, but it's still open."
    return f"Closed the {tab.title} tab."


BROWSER_LABELS = {"chrome": "Chrome", "brave": "Brave", "edge": "Edge", "firefox": "Firefox"}
BROWSER_APPS = {"chrome": "chrome", "brave": "brave", "edge": "microsoft edge", "firefox": "firefox"}


def _browser_key(browser: str | None) -> str | None:
    return BROWSER_NAMES.get(_norm(browser), _norm(browser)) if browser else None


def browser_window(browser: str | None = None):
    """The browser window to act on: the named browser's, else the one in front, else the most recent."""
    key = _browser_key(browser)
    wins = [w for w in _windows() if browser_of(w.title) and (key is None or browser_of(w.title) == key)]
    if not wins:
        return None
    front = foreground_title()
    return next((w for w in wins if clean_title(w.title) == front), wins[0])  # windows come front-to-back


def _front_browser(browser: str | None = None, open_if_missing: bool = True):
    """Bring the right browser window to the front, opening the browser if needed. (window, just_opened)."""
    win = browser_window(browser)
    opened = False
    if win is None and open_if_missing:
        from . import computer

        computer.open_app(BROWSER_APPS.get(_browser_key(browser) or "", "microsoft edge"))
        opened = True
        for _ in range(20):
            win = browser_window(browser)
            if win is not None:
                break
            time.sleep(0.5)
    if win is not None:
        activate(win)
        remember_app(browser_of(win.title))
    return win, opened


def _active_tab_title(win) -> str:
    title = clean_title(win.title)
    return re.sub(r"\s+-\s+(?:[^-]+\s+-\s+)?(?:google chrome|brave|microsoft edge|mozilla firefox)$", "",
                  title, flags=re.I)


def new_tab(browser: str | None = None, url: str | None = None, label: str | None = None) -> str:
    """Open a new tab (optionally at a URL) in the named browser, or the one in front."""
    if SYSTEM != "Windows":
        if url:
            import webbrowser

            webbrowser.open(url, new=2)
            return f"Opened {label or url}."
        return "Tabs only work on Windows for now."
    import pyautogui

    win, just_opened = _front_browser(browser)
    if win is None:
        return f"I couldn't open {BROWSER_LABELS.get(_browser_key(browser) or '', 'a browser')}."
    name = BROWSER_LABELS[browser_of(win.title)]
    if not just_opened:  # a freshly opened browser already shows a new tab
        pyautogui.hotkey("ctrl", "t")
        time.sleep(0.4)
    if url:
        pyautogui.hotkey("ctrl", "l")  # address bar
        pyautogui.write(url, interval=0.01)
        pyautogui.press("enter")
        return f"Opened {label or url} in a new {name} tab."
    return f"Opened a new tab in {name}."


TAB_KEYS = {
    "next": ("ctrl", "tab"), "previous": ("ctrl", "shift", "tab"), "first": ("ctrl", "1"), "last": ("ctrl", "9"),
    "close": ("ctrl", "w"), "reopen": ("ctrl", "shift", "t"), "new_window": ("ctrl", "n"),
    "private_window": ("ctrl", "shift", "n"), "reload": ("f5",), "back": ("alt", "left"), "forward": ("alt", "right"),
}


def tab_action(action: str, browser: str | None = None) -> str:
    """next / previous / first / last / close (the current tab) / reopen / new_window / private_window /
    reload / back / forward."""
    if action not in TAB_KEYS:
        return f"I don't know the tab action {action}."
    if SYSTEM != "Windows":
        return "Tab controls only work on Windows for now."
    import pyautogui

    win, just_opened = _front_browser(browser, open_if_missing=action in ("new_window", "private_window"))
    if win is None:
        return "No browser is open."
    name = BROWSER_LABELS[browser_of(win.title)]
    keys = TAB_KEYS[action]
    if action == "private_window" and browser_of(win.title) == "firefox":
        keys = ("ctrl", "shift", "p")
    current = _active_tab_title(win)
    pyautogui.hotkey(*keys)
    time.sleep(0.4)
    if action == "close":
        return f"Closed the {current} tab." if current else "Closed the tab."
    if action in ("next", "previous", "first", "last"):
        return f"Now on {_active_tab_title(win) or 'the ' + action + ' tab'}."
    return {"reopen": "Brought back the last closed tab.", "new_window": f"Opened a new {name} window.",
            "private_window": f"Opened a private {name} window.", "reload": "Reloaded the page.",
            "back": "Went back.", "forward": "Went forward."}[action]


def close_other_tabs(keep: str | None = None, browser: str | None = None) -> str:
    """Close every tab in that window except `keep` (or except the current tab)."""
    if SYSTEM != "Windows":
        return "Tab controls only work on Windows for now."
    import pyautogui

    if keep:
        kept = find_tab(keep, browser)
        if kept is None:
            return f"I can't find a tab called {keep}."
        window, kept_title = kept.window, kept.title
    else:
        window = browser_window(browser)
        if window is None:
            return "No browser is open."
        kept_title = _active_tab_title(window)
    closed = 0
    for _ in range(50):
        others = [t for t in browser_tabs(browser_of(window.title))
                  if t.window == window and _norm(t.title) != _norm(kept_title)]
        if not others:
            break
        activate(window)
        click_point(others[0].x, others[0].y)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "w")
        time.sleep(0.3)
        closed += 1
    return f"Closed {closed} tab{'s' if closed != 1 else ''} and kept {kept_title}."


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
