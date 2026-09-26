import types

import pytest

pytest.importorskip("anthropic")

from jarvis import ai, computer  # noqa: E402
from jarvis.config import Config  # noqa: E402


def block(type_, **kw):
    return types.SimpleNamespace(type=type_, **kw)


def reply(stop_reason, *content):
    return types.SimpleNamespace(stop_reason=stop_reason, content=list(content))


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.api_key, self.auth_token, self.credentials = "sk-test", None, None
        self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def test_tool_loop_runs_tools_and_keeps_history(monkeypatch):
    opened = []
    monkeypatch.setattr(computer, "open_app", lambda name: opened.append(name) or f"Opening {name}.")
    client = FakeClient([
        reply("tool_use", block("text", text="Right away."),
              block("tool_use", id="t1", name="open_app", input={"name": "chrome"})),
        reply("end_turn", block("text", text="Chrome is open, sir.")),
        reply("end_turn", block("text", text="You asked me to open Chrome.")),
    ])
    claude = ai.Claude(Config(), client=client)

    assert claude("open chrome") == "Chrome is open, sir."
    assert opened == ["chrome"]
    tool_result = client.requests[1]["messages"][-1]["content"][0]
    assert tool_result == {"type": "tool_result", "tool_use_id": "t1", "content": "Opening chrome."}

    assert claude("what did I just ask?") == "You asked me to open Chrome."
    # The next request carries the first turn as conversation, with a note of what was done.
    messages = client.requests[2]["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[1]["content"] == "Chrome is open, sir.\n[Actions: open_app(chrome) -> Opening chrome.]"


def test_tool_errors_are_reported_to_claude(monkeypatch):
    def broken(name):
        raise RuntimeError("no display")

    monkeypatch.setattr(computer, "open_app", broken)
    client = FakeClient([
        reply("tool_use", block("tool_use", id="t1", name="open_app", input={"name": "chrome"})),
        reply("end_turn", block("text", text="I couldn't open it.")),
    ])
    assert ai.Claude(Config(), client=client)("open chrome") == "I couldn't open it."
    result = client.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] and "no display" in result["content"]


def test_start_conversation_and_request_shape():
    client = FakeClient([reply("end_turn", block("text", text="Good morning. Sleep well?"))])
    claude = ai.Claude(Config(user_title="Sudarsan"), client=client)
    assert claude.start_conversation() == "Good morning. Sleep well?"
    req = client.requests[0]
    assert req["messages"] == [{"role": "user", "content": "Jarvis."}]
    assert "Sudarsan" in req["system"] and "push back" in req["system"]
    assert req["model"] == "claude-opus-5" and req["fallbacks"] == "default"
    assert {t["name"] for t in req["tools"]} >= {"open_app", "close_app", "type_text", "compose_email"}


def test_refusal_is_spoken_and_not_stored():
    client = FakeClient([reply("refusal")])
    claude = ai.Claude(Config(), client=client)
    assert "can't help" in claude("something")
    assert claude.memory.turns == []


def test_api_key_from_settings_file(monkeypatch):
    from jarvis import config

    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", "/nonexistent")
    assert ai.make_claude(Config()) is None
    config.save_setting("anthropic_api_key", "sk-from-file")
    assert ai.make_claude(Config()).client.api_key == "sk-from-file"


def api_error(cls, status, message):
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(status, request=request)
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    return cls(message, response=response, body=body)


class FailingClient(FakeClient):
    def __init__(self, errors, responses=()):
        super().__init__(responses)
        self.errors = list(errors)

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        if self.errors:
            raise self.errors.pop(0)
        return self.responses.pop(0)


def test_out_of_credit_is_explained():
    import anthropic

    client = FailingClient([api_error(anthropic.BadRequestError, 400,
                                      "Your credit balance is too low to access the Anthropic API.")])
    assert "out of credit" in ai.Claude(Config(), client=client)("hello")


def test_unsupported_optional_features_are_dropped_and_retried():
    import anthropic

    client = FailingClient([api_error(anthropic.BadRequestError, 400, "fallbacks: Extra inputs are not permitted")],
                           [reply("end_turn", block("text", text="Hello, sir."))])
    claude = ai.Claude(Config(), client=client)
    assert claude("hello") == "Hello, sir."
    assert "fallbacks" in client.requests[0] and "fallbacks" not in client.requests[1]
    assert "output_config" not in client.requests[1]


def test_other_errors_say_what_went_wrong():
    import anthropic

    client = FailingClient([api_error(anthropic.BadRequestError, 400, "messages: text content blocks must be non-empty")])
    assert "must be non-empty" in ai.Claude(Config(), client=client)("hello")
