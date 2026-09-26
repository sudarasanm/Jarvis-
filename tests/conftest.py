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
    from jarvis import ai

    monkeypatch.setattr(ai, "current_context", lambda: "")
