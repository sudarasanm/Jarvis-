import pytest

from jarvis.brain import Brain
from jarvis.config import Config
from jarvis.skills import power, weather, web


@pytest.fixture
def brain(monkeypatch):
    opened = []
    monkeypatch.setattr(web, "open_url", opened.append)
    b = Brain(Config(dry_run=True))
    b.opened = opened
    return b


def test_wake_word_is_stripped(brain):
    assert brain.strip_wake_word("Hey Jarvis, what time is it?") == (True, "what time is it?")
    assert brain.strip_wake_word("jarvis") == (True, "")
    assert brain.strip_wake_word("what time is it") == (False, "what time is it")
    # Common mishearings still count
    assert brain.strip_wake_word("hey Jervis what time is it") == (True, "what time is it")
    assert brain.strip_wake_word("hey jarvis") == (True, "")
    assert brain.strip_wake_word("goodbye Jarvis") == (True, "goodbye")


def test_time_and_date(brain):
    assert brain.handle("what time is it").text.startswith("It's")
    assert brain.handle("what's the date today").text.startswith("Today is")


def test_shutdown_requires_confirmation(brain, monkeypatch):
    ran = []
    monkeypatch.setattr(power, "run", lambda action, b: ran.append(action) or True)

    r = brain.handle("turn off my computer")
    assert "sure" in r.text and ran == []
    assert brain.handle("no").text.startswith("Very well")
    assert ran == []

    brain.handle("shut down the computer")
    assert "Shutting down" in brain.handle("yes").text
    assert ran == ["shutdown"]


def test_confirmation_is_dropped_by_a_new_command(brain, monkeypatch):
    ran = []
    monkeypatch.setattr(power, "run", lambda action, b: ran.append(action) or True)
    brain.handle("restart the computer")
    assert brain.handle("tell me a joke").text
    assert brain.handle("yes").text  # no longer confirms the restart
    assert ran == []


def test_cancel_restart_is_not_a_restart(brain, monkeypatch):
    ran = []
    monkeypatch.setattr(power, "run", lambda action, b: ran.append(action) or True)
    assert "cancelled" in brain.handle("cancel the restart").text
    assert ran == ["cancel"]


def test_weather_with_city(brain, monkeypatch):
    calls = {}

    def fake_locate(city):
        calls["city"] = city
        return "London", 51.5, -0.1

    monkeypatch.setattr(weather, "locate", fake_locate)
    monkeypatch.setattr(weather, "forecast", lambda lat, lon, units: {
        "current": {"temperature_2m": 18.4, "apparent_temperature": 17.0, "weather_code": 61, "wind_speed_10m": 12},
        "daily": {"temperature_2m_max": [20], "temperature_2m_min": [11], "precipitation_probability_max": [70]},
    })
    text = brain.handle("tell me the weather in London").text
    assert calls["city"] == "London"
    assert "18 degrees Celsius with light rain" in text
    assert "umbrella" in text


def test_weather_defaults_to_configured_city(brain, monkeypatch):
    brain.config.city = "Chennai"
    seen = []
    monkeypatch.setattr(weather, "locate", lambda city: seen.append(city) or (_ for _ in ()).throw(LookupError(city)))
    brain.handle("what's the weather")
    assert seen == ["Chennai"]


def test_web_commands(brain):
    assert "youtube" in brain.handle("open youtube").text
    assert "Playing interstellar soundtrack" in brain.handle("play interstellar soundtrack").text
    brain.handle("search for iron man suit")
    assert brain.opened == [
        "https://www.youtube.com",
        "https://www.youtube.com/results?search_query=interstellar+soundtrack",
        "https://www.google.com/search?q=iron+man+suit",
    ]


def test_goodbye_exits(brain):
    assert brain.handle("goodbye").exit


def test_unknown_goes_to_fallback():
    b = Brain(Config(), fallback=lambda text: f"echo: {text}")
    assert b.handle("what is the meaning of life").text == "echo: what is the meaning of life"


def test_unknown_without_fallback():
    assert "don't know" in Brain(Config()).handle("recalibrate the arc reactor").text


def test_call_me_sets_and_remembers_name(brain):
    assert "call you Sudarsan" in brain.handle("can you call me as sudarsan").text
    assert brain.handle("what time is it").text.endswith("Sudarsan.")
    assert Config().user_title == "Sudarsan"  # persisted for next launch


def test_call_me_without_a_name_asks_for_it(brain):
    # Speech recognition often cuts the sentence at a pause: "call me a" ... "Sudarsan"
    r = brain.handle("can you call me a")
    assert "What would you like me to call you" in r.text
    assert brain.awaiting_reply
    assert "call you Sudarsan" in brain.handle("Sudarsan").text
    assert not brain.awaiting_reply


def test_broken_skill_does_not_crash():
    b = Brain(Config(), fallback=lambda text: 1 / 0)
    assert "something went wrong" in b.handle("what is the meaning of life").text


def test_claude_disabled_without_credentials(monkeypatch):
    pytest.importorskip("anthropic")
    from jarvis.ai import make_fallback

    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", "/nonexistent")
    assert make_fallback(Config()) is None

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert make_fallback(Config()) is not None
