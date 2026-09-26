import json
import sys
import types

import pytest

from jarvis import ai, computer, screen, vision
from jarvis.brain import Brain
from jarvis.config import Config, save_setting


class Rect:
    def __init__(self, left, top, right, bottom):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top

    def xcenter(self):
        return self.left + self.width() // 2

    def ycenter(self):
        return self.top + self.height() // 2


def control(kind, name, rect=(0, 0, 100, 40), offscreen=False):
    return types.SimpleNamespace(ControlTypeName=f"{kind}Control", Name=name,
                                 BoundingRectangle=Rect(*rect), IsOffscreen=offscreen)


NETFLIX = [
    control("Text", "Who's watching?", (500, 100, 900, 150)),
    control("Hyperlink", "Sudarsan", (300, 400, 450, 550)),
    control("Hyperlink", "Kids", (500, 400, 650, 550)),
    control("Hyperlink", "Amma", (700, 400, 850, 550)),
    control("Button", "Manage Profiles", (550, 700, 750, 740)),
    control("Hyperlink", "Hidden", (0, 0, 10, 10), offscreen=True),
    control("Pane", "", (0, 0, 1920, 1080)),
]


@pytest.fixture
def windows_desktop(monkeypatch):
    """A fake Windows: UI Automation showing the Netflix profile page, and a fake mouse."""
    clicks = []
    uia = types.ModuleType("uiautomation")
    uia.GetForegroundControl = lambda: "root"
    uia.WalkControl = lambda root, maxDepth=0: ((c, 1) for c in NETFLIX)
    gui = types.SimpleNamespace(
        click=lambda x, y, clicks=1, interval=0, button="left": clicks_log(x, y, clicks, button),
        scroll=lambda amount: clicks.append(("scroll", amount)),
        press=lambda key: None,
    )

    def clicks_log(x, y, n, button):
        clicks.append((x, y, n, button))

    active = types.SimpleNamespace(title="Netflix - Brave")
    pygetwindow = types.ModuleType("pygetwindow")
    pygetwindow.getActiveWindow = lambda: active
    monkeypatch.setitem(sys.modules, "uiautomation", uia)
    monkeypatch.setitem(sys.modules, "pyautogui", gui)
    monkeypatch.setitem(sys.modules, "pygetwindow", pygetwindow)
    monkeypatch.setattr(screen, "SYSTEM", "Windows")
    return clicks


def test_read_screen_lists_visible_elements(windows_desktop):
    text = screen.read_screen()
    assert text.splitlines()[0] == "Front window: Netflix - Brave"
    assert "- Hyperlink: Sudarsan" in text and "- Hyperlink: Amma" in text and "- Button: Manage Profiles" in text
    assert "Hidden" not in text  # off-screen elements are skipped


def test_click_by_name(windows_desktop):
    assert screen.click("amma") == "Clicked hyperlink 'Amma'."
    assert windows_desktop[-1] == (775, 475, 1, "left")
    assert screen.click("manage", double=True) == "Double-clicked button 'Manage Profiles'."


def test_click_falls_back_to_vision(windows_desktop):
    assert screen.click("the red play button", locate=lambda t: (960, 540)) == \
        "Clicked what looked like the red play button."
    assert windows_desktop[-1] == (960, 540, 1, "left")
    assert "couldn't find" in screen.click("a unicorn", locate=lambda t: None)


def test_find_element_prefers_exact_then_clickable():
    els = [screen.Element("Text", "Allow notifications?", 1, 1), screen.Element("Button", "Allow", 2, 2),
           screen.Element("Button", "Allow once", 3, 3)]
    assert screen.find_element("allow", els).name == "Allow"
    assert screen.find_element("Allow once!", els).name == "Allow once"
    assert screen.find_element("notifications", els).name == "Allow notifications?"


def test_list_and_switch_windows(monkeypatch):
    activated = []
    wins = [types.SimpleNamespace(title="Netflix - Brave", visible=True, isMinimized=True,
                                  restore=lambda: activated.append("restore"),
                                  activate=lambda: activated.append("activate")),
            types.SimpleNamespace(title="Program Manager", visible=True),
            types.SimpleNamespace(title="Jarvis - PowerShell", visible=True)]
    pygetwindow = types.ModuleType("pygetwindow")
    pygetwindow.getAllWindows = lambda: wins
    monkeypatch.setitem(sys.modules, "pygetwindow", pygetwindow)
    monkeypatch.setattr(screen, "SYSTEM", "Windows")
    monkeypatch.setattr(screen.time, "sleep", lambda s: None)
    assert screen.list_windows() == "Open windows: Netflix - Brave; Jarvis - PowerShell"
    assert screen.switch_to_window("netflix") == "Switched to Netflix - Brave."
    assert activated == ["restore", "activate"]
    assert "can't see" in screen.switch_to_window("excel")


def test_vision_parse_box():
    assert vision.parse_box('{"found": true, "box_2d": [400, 100, 600, 300]}', 1920, 1080) == (384, 540)
    assert vision.parse_box('```json\n{"found": false}\n```', 1920, 1080) is None
    assert vision.parse_box("no idea", 1920, 1080) is None


def test_vision_locate_and_describe_use_gemini(monkeypatch):
    save_setting("gemini_api_key", "g-key")
    monkeypatch.setattr(screen, "screenshot_jpeg", lambda: (b"JPEG", (1920, 1080)))
    sent = []

    def fake_post(url, body, headers=None, timeout=120):
        sent.append(body)
        wants_json = "responseMimeType" in body.get("generationConfig", {})
        text = '{"found": true, "box_2d": [0, 0, 1000, 1000]}' if wants_json else "Three profiles."
        return {"candidates": [{"content": {"parts": [{"text": text}]}}]}

    from jarvis import free_ai
    monkeypatch.setattr(free_ai, "post_json", fake_post)
    assert vision.locate("play button", Config()) == (960, 540)
    assert vision.describe("How many profiles?", Config()) == "Three profiles."
    image_part = sent[0]["contents"][0]["parts"][0]["inlineData"]
    assert image_part == {"mimeType": "image/jpeg", "data": "SlBFRw=="}
    assert sent[0]["generationConfig"] == {"responseMimeType": "application/json",
                                           "thinkingConfig": {"thinkingLevel": "low"}}


def test_vision_without_any_vision_brain(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setattr(screen, "screenshot_jpeg", lambda: (b"x", (1, 1)))
    with pytest.raises(vision.VisionUnavailable):
        vision.describe("what's here?", Config())
    assert vision.locate("x", Config()) is None


@pytest.fixture
def chrome_profiles(tmp_path, monkeypatch):
    data = tmp_path / "Google" / "Chrome" / "User Data"
    data.mkdir(parents=True)
    (data / "Local State").write_text(json.dumps({"profile": {"info_cache": {
        "Default": {"name": "Sudarsan", "user_name": "sudar@gmail.com", "gaia_name": "Sudarsan M"},
        "Profile 1": {"name": "Work", "user_name": "sudarsan@company.com", "gaia_name": "Sudarsan M"},
        "Profile 3": {"name": "Guest-ish", "user_name": "", "gaia_name": ""},
    }}}), encoding="utf-8")
    monkeypatch.setattr(computer, "SYSTEM", "Windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    launched = []
    monkeypatch.setattr(computer.subprocess, "Popen", lambda cmd, **kw: launched.append(cmd))
    monkeypatch.setattr(computer.time, "sleep", lambda s: None)
    return launched


def test_browser_profiles(chrome_profiles):
    text = computer.list_browser_profiles("chrome")
    assert text.startswith("Chrome has 3 profiles: ")
    assert "Sudarsan (Sudarsan M, sudar@gmail.com)" in text and "Work (Sudarsan M, sudarsan@company.com)" in text
    assert "couldn't find any brave profiles" in computer.list_browser_profiles("brave")


def test_open_browser_profile(chrome_profiles):
    assert computer.open_browser_profile("google chrome", "work", "https://netflix.com") == "Opening google chrome as Work."
    assert chrome_profiles[-1] == ["cmd", "/c", "start", "", "chrome", "--profile-directory=Profile 1",
                                   "https://netflix.com"]
    computer.open_browser_profile("chrome", "sudar@gmail.com")
    assert chrome_profiles[-1][-1] == "--profile-directory=Default"
    assert "no chrome profile called Mom" in computer.open_browser_profile("chrome", "Mom")


def test_voice_commands_for_mouse_windows_and_profiles(windows_desktop, chrome_profiles):
    b = Brain(Config())
    assert b.handle("click on Amma").text == "Clicked hyperlink 'Amma'."
    assert b.handle("double click manage profiles").text.startswith("Double-clicked")
    assert b.handle("scroll down a lot").text == "Scrolled down."
    assert windows_desktop[-1] == ("scroll", -2400)
    assert b.handle("tell me the list of users in the chrome which have logged in before").text.startswith(
        "Chrome has 3 profiles")


def test_ordinal_clicks_go_to_the_ai(windows_desktop):
    asked = []
    b = Brain(Config(), fallback=lambda text: asked.append(text) or "Clicked it.")
    b.handle("click the second profile")
    assert asked == ["click the second profile"] and windows_desktop == []


def test_ai_screen_tools(windows_desktop, monkeypatch):
    brain = ai.Assistant(Config())
    monkeypatch.setattr(ai.time, "sleep", lambda s: None)
    text, err = brain.run_tool("read_screen", {})
    assert not err and "Hyperlink: Kids" in text
    assert brain.run_tool("click", {"target": "Kids"}) == ("Clicked hyperlink 'Kids'.", False)
    assert brain.run_tool("wait", {"seconds": 99}) == ("Waited 30 seconds.", False)
    names = {t["name"] for t in ai.TOOLS}
    assert names >= {"read_screen", "look_at_screen", "click", "scroll", "switch_window", "list_windows",
                     "browser_profiles", "open_browser_profile", "wait"}


def test_screenshot_is_resized_jpeg(monkeypatch):
    from PIL import Image

    image_grab = types.ModuleType("PIL.ImageGrab")
    image_grab.grab = lambda: Image.new("RGBA", (3840, 2160), "white")
    monkeypatch.setitem(sys.modules, "PIL.ImageGrab", image_grab)
    import PIL

    monkeypatch.setattr(PIL, "ImageGrab", image_grab, raising=False)
    data, size = screen.screenshot_jpeg()
    assert size == (3840, 2160)  # real size, for mapping vision coordinates to clicks
    import io

    assert Image.open(io.BytesIO(data)).size == (1280, 720) and data[:2] == b"\xff\xd8"


def test_gemini_does_a_multi_step_screen_task(windows_desktop, monkeypatch):
    """"Open Netflix and tell me the profiles, then pick Amma": open, wait, read, answer, click."""
    from jarvis import free_ai

    monkeypatch.setattr(computer, "open_app", lambda name: f"Opening {name}.")
    monkeypatch.setattr(ai.time, "sleep", lambda s: None)

    def call(tool, **args):
        return {"candidates": [{"content": {"role": "model", "parts": [{"functionCall": {"name": tool, "args": args}}]}}]}

    def say(text):
        return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}]}

    replies = [call("open_app", name="netflix"), call("wait", seconds=3), call("read_screen"),
               say("There are three profiles: Sudarsan, Kids and Amma. Which one?"),
               call("click", target="Amma"), say("Done, you're in Amma's profile.")]
    sent = []

    def post(url, body, headers=None, timeout=120):
        sent.append(json.loads(json.dumps(body)))
        return replies.pop(0)

    g = free_ai.Gemini(Config(), "key", post=post)
    assert g("open netflix and list the profiles") == "There are three profiles: Sudarsan, Kids and Amma. Which one?"
    screen_result = sent[3]["contents"][-1]["parts"][0]["functionResponse"]["response"]["result"]
    assert "Hyperlink: Amma" in screen_result
    assert g("Amma") == "Done, you're in Amma's profile."
    assert windows_desktop[-1] == (775, 475, 1, "left")


# --- browser tabs -------------------------------------------------------------------------------

class Node:
    """A fake UI Automation element tree."""

    def __init__(self, kind, name="", rect=(0, 0, 0, 0), children=()):
        self.ControlTypeName, self.Name = f"{kind}Control", name
        self.BoundingRectangle = Rect(*rect)
        self.children = list(children)

    def GetChildren(self):
        return list(self.children)


@pytest.fixture
def browsers(monkeypatch):
    """Chrome with three tabs (one showing extra hover text) and Brave with one, plus a fake keyboard/mouse."""
    actions = []
    chrome_strip = Node("Tab", children=[
        Node("TabItem", "Inbox (9,937) - sudar@gmail.com - Gmail - Memory usage - 324 MB", (10, 5, 210, 35)),
        Node("TabItem", "API keys | Claude Platform", (210, 5, 410, 35)),
        Node("TabItem", "Ollama", (410, 5, 610, 35)),
    ])
    page = Node("Document", "Ollama", children=[Node("TabItem", "Fake tab inside a web page", (1, 1, 2, 2))])
    chrome = Node("Window", children=[Node("Pane", children=[chrome_strip]), page])
    brave = Node("Window", children=[Node("Tab", children=[Node("TabItem", "Netflix", (10, 5, 210, 35))])])
    wins = [types.SimpleNamespace(title="Ollama - Google Chrome", _hWnd=1, visible=True, isMinimized=False,
                                  activate=lambda: actions.append("activate chrome")),
            types.SimpleNamespace(title="Netflix - Brave", _hWnd=2, visible=True, isMinimized=False,
                                  activate=lambda: actions.append("activate brave"))]
    roots = {1: chrome, 2: brave}

    uia = types.ModuleType("uiautomation")
    uia.ControlFromHandle = lambda h: roots[h]

    def hotkey(*keys):
        actions.append(("hotkey", keys))
        if keys == ("ctrl", "w"):  # closes whichever tab was clicked last
            x = actions_last_click[0]
            chrome_strip.children[:] = [t for t in chrome_strip.children if t.BoundingRectangle.xcenter() != x]

    actions_last_click = [None]

    def click(x, y, clicks=1, interval=0, button="left"):
        actions_last_click[0] = x
        actions.append(("click", x, y))

    monkeypatch.setitem(sys.modules, "uiautomation", uia)
    monkeypatch.setitem(sys.modules, "pyautogui", types.SimpleNamespace(click=click, hotkey=hotkey, press=lambda k: None))
    monkeypatch.setattr(screen, "SYSTEM", "Windows")
    monkeypatch.setattr(screen, "_windows", lambda: wins)
    monkeypatch.setattr(screen.time, "sleep", lambda s: None)
    return actions


def test_list_tabs_cleans_titles_and_skips_page_content(browsers):
    assert screen.list_tabs() == ("Chrome has 3 tabs: Inbox (9,937) - sudar@gmail.com - Gmail; "
                                  "API keys | Claude Platform; Ollama. Brave has 1 tab: Netflix.")
    assert screen.list_tabs("brave") == "Brave has 1 tab: Netflix."


def test_close_tab_by_partial_title_and_verifies(browsers):
    assert screen.close_tab("ollama") == "Closed the Ollama tab."
    assert ("click", 510, 20) in browsers and ("hotkey", ("ctrl", "w")) in browsers
    assert screen.close_tab("claude api keys") == "Closed the API keys | Claude Platform tab."  # words in any order
    assert screen.list_tabs("chrome") == "Chrome has 1 tab: Inbox (9,937) - sudar@gmail.com - Gmail."
    assert "can't find" in screen.close_tab("hotstar")


def test_tab_voice_commands(browsers):
    b = Brain(Config())
    assert b.handle("list the tabs in chrome").text.startswith("Chrome has 3 tabs")
    assert b.handle("what tabs are open").text.startswith("Chrome has 3 tabs")
    assert b.handle("switch to the gmail tab").text == "Switched to the Inbox (9,937) - sudar@gmail.com - Gmail tab."
    assert b.handle("close olama in the Google Chrome tab").text == "Closed the Ollama tab."
    assert b.handle("close the IP keys tab").text == "Closed the API keys | Claude Platform tab."


def test_switch_window_falls_back_to_tab(browsers):
    assert screen.switch_to_window("gmail").startswith("Switched to the Inbox")


def test_symbol_buttons_by_spoken_name():
    els = [screen.Element("Text", "Accounts", 1, 1), screen.Element("Button", "+", 50, 50),
           screen.Element("Button", "×", 90, 10)]
    assert screen.find_element("plus", els).name == "+"
    assert screen.find_element("plus button", els).name == "+"
    assert screen.find_element("x", els).name == "×"
    add = [screen.Element("Button", "Add account", 5, 5)]
    assert screen.find_element("plus", add).name == "Add account"


def test_click_says_so_when_it_cannot_look(monkeypatch):
    monkeypatch.setattr(screen, "SYSTEM", "Linux")

    def locate(target):
        raise RuntimeError("Gemini's free limit is used up")

    text = screen.click("the plus button", locate=locate)
    assert "can't look at the screen right now" in text and "free limit" in text
