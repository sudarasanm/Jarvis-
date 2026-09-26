import pytest

from jarvis import config


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep tests from reading or writing the real ~/.jarvis.json."""
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "jarvis.json")
    monkeypatch.delenv("JARVIS_USER_TITLE", raising=False)


@pytest.fixture(autouse=True)
def fresh_gemini_limits(monkeypatch):
    from jarvis import free_ai

    monkeypatch.setattr(free_ai, "_gemini_resting", {})
    monkeypatch.setattr(free_ai, "_thinking_choice", {})
    from jarvis import ai, screen

    monkeypatch.setattr(ai, "current_context", lambda: "")
    monkeypatch.setattr(screen, "_working", {"name": None})


@pytest.fixture(autouse=True)
def fresh_state(tmp_path, monkeypatch):
    """A clean shared state and a throwaway action log for every test."""
    from jarvis import actions
    from jarvis.state import State
    import jarvis.state

    fresh = State()
    monkeypatch.setattr(jarvis.state, "state", fresh)
    for module in ("jarvis.ai", "jarvis.__main__", "jarvis.skills.listening", "jarvis.hotkey", "jarvis.tray"):
        mod = __import__(module, fromlist=["state"])
        monkeypatch.setattr(mod, "state", fresh)
    monkeypatch.setattr(actions, "ACTIONS_FILE", tmp_path / "actions.jsonl")
    return fresh
