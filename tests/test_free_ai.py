import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from jarvis import ai, computer, free_ai
from jarvis.config import Config, save_setting


class FakePost:
    """Stands in for post_json: records requests, returns canned replies or raises errors."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, url, body, headers=None, timeout=120):
        self.requests.append((url, json.loads(json.dumps(body)), headers))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def gemini_reply(*parts):
    return {"candidates": [{"content": {"role": "model", "parts": list(parts)}}]}


def test_gemini_tool_loop(monkeypatch):
    monkeypatch.setattr(computer, "open_app", lambda name: f"Opening {name}.")
    post = FakePost(
        gemini_reply({"functionCall": {"name": "open_app", "args": {"name": "brave"}}, "thoughtSignature": "sig"}),
        gemini_reply({"text": "Brave is open. What are we browsing?"}),
    )
    g = free_ai.Gemini(Config(), "key-123", post=post)
    assert g("open brave") == "Brave is open. What are we browsing?"

    url, body, headers = post.requests[1]
    assert url.endswith("/models/gemini-flash-latest:generateContent")
    assert headers == {"x-goog-api-key": "key-123"}
    assert "Jarvis" in body["systemInstruction"]["parts"][0]["text"]
    assert {f["name"] for f in body["tools"][0]["functionDeclarations"]} >= {"open_app", "compose_email"}
    # The model's function call is echoed back unchanged (signature included), followed by the result.
    assert body["contents"][1]["parts"][0]["thoughtSignature"] == "sig"
    assert body["contents"][2]["parts"][0]["functionResponse"] == {
        "name": "open_app", "response": {"result": "Opening brave."}}


def test_gemini_quota_pauses_it_after_trying_every_model():
    post = FakePost(free_ai.HTTPError(429, "Quota exceeded. Please retry in 40.05s."),
                    free_ai.HTTPError(429, "Quota exceeded. Please retry in 20s."))
    g = free_ai.Gemini(Config(), "k", post=post)
    assert "free limit" in g("hello")
    assert not g.available
    assert [u.split("/models/")[1] for u, _, _ in post.requests] == [
        "gemini-flash-latest:generateContent", "gemini-flash-lite-latest:generateContent"]
    assert 55 < g.unavailable_until - __import__("time").time() <= 60  # rests; the other brain takes over


def test_gemini_waits_out_a_tiny_limit_then_switches_model_for_a_long_one(monkeypatch):
    slept = []
    monkeypatch.setattr(free_ai.time, "sleep", slept.append)
    post = FakePost(free_ai.HTTPError(429, "Please retry in 426.6ms."), gemini_reply({"text": "Hi."}),
                    free_ai.HTTPError(429, "Please retry in 57s."), gemini_reply({"text": "Still here."}))
    g = free_ai.Gemini(Config(), "k", post=post)
    assert g("hello") == "Hi."
    assert slept and slept[0] < 1  # waited under a second and retried the same model
    assert g("again") == "Still here."
    assert post.requests[-1][0].endswith("gemini-flash-lite-latest:generateContent")


def test_retry_delay_parsing():
    assert free_ai.retry_delay("Please retry in 426.618514ms.") == pytest.approx(0.4266, abs=1e-3)
    assert free_ai.retry_delay("Please retry in 40.055756287s.") == pytest.approx(40.06, abs=0.01)
    assert free_ai.retry_delay("nothing here") is None


def test_ollama_tool_loop(monkeypatch):
    monkeypatch.setattr(computer, "close_app", lambda name: f"Closing {name}.")
    post = FakePost(
        {"message": {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "close_app", "arguments": {"name": "chrome"}}}]}},
        {"message": {"role": "assistant", "content": "Chrome is closed."}},
    )
    o = free_ai.Ollama(Config(), post=post)
    assert o("close chrome") == "Chrome is closed."
    url, body, _ = post.requests[1]
    assert url == "http://localhost:11434/api/chat" and body["model"] == "llama3.2" and body["stream"] is False
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][-1] == {"role": "tool", "tool_name": "close_app", "content": "Closing chrome."}


def test_ollama_remembers_the_conversation():
    post = FakePost({"message": {"role": "assistant", "content": "Hello."}},
                    {"message": {"role": "assistant", "content": "You said hi."}})
    o = free_ai.Ollama(Config(), post=post)
    o("hi")
    o("what did I say?")
    roles = [m["role"] for m in post.requests[1][1]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


class Brain(ai.Assistant):
    def __init__(self, label, answer, runs_out=False):
        super().__init__(Config())
        self.label, self.answer, self.runs_out, self.calls = label, answer, runs_out, 0

    def _turn(self, text):
        self.calls += 1
        if self.runs_out:
            self.pause(3600, "out of credit")
            return "out of credit"
        return self.answer


def test_failover_switches_when_a_brain_runs_out():
    claude = Brain("Claude", "from claude", runs_out=True)
    gemini = Brain("Gemini", "from gemini")
    brain = ai.Failover([claude, gemini])
    assert brain("hello") == "from gemini"
    assert brain("again") == "from gemini"
    assert claude.calls == 1  # not retried while paused
    assert brain.start_conversation() == "from gemini"


def test_failover_all_out():
    brain = ai.Failover([Brain("Claude", "x", runs_out=True)])
    assert brain("hello") == "out of credit"
    assert "unavailable" in brain("hello again")


def test_make_brain_uses_preference_and_available_keys(monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", "/nonexistent")
    monkeypatch.setattr(free_ai, "make_ollama", lambda config: None)
    assert ai.make_brain(Config()) is None

    save_setting("gemini_api_key", "g-key")
    assert ai.make_brain(Config()).names == "Gemini"

    pytest.importorskip("anthropic")
    save_setting("anthropic_api_key", "sk-ant")
    assert ai.make_brain(Config()).names == "Gemini, then Claude"  # free first by default
    save_setting("ai_provider", "claude")
    assert ai.make_brain(Config()).names == "Claude, then Gemini"


def test_make_ollama_checks_the_model_is_downloaded(monkeypatch):
    monkeypatch.setattr(free_ai, "ollama_exe", lambda: None)
    monkeypatch.setattr(free_ai, "get_json", lambda url, timeout=2: {"models": [{"name": "llama3.2:latest"}]})
    assert isinstance(free_ai.make_ollama(Config()), free_ai.Ollama)
    monkeypatch.setattr(free_ai, "get_json", lambda url, timeout=2: {"models": [{"name": "qwen2.5:3b"}]})
    assert free_ai.make_ollama(Config()) is None

    def offline(url, timeout=2):
        raise OSError("connection refused")

    monkeypatch.setattr(free_ai, "get_json", offline)
    assert free_ai.make_ollama(Config()) is None


def test_post_json_over_real_http():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if body.get("fail"):
                out, code = {"error": {"code": 429, "message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}}, 429
            else:
                out, code = {"echo": body, "key": self.headers.get("x-goog-api-key")}, 200
            data = json.dumps(out).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # bypass any proxy for localhost
    urllib.request.install_opener(opener)
    try:
        assert free_ai.post_json(url, {"a": 1}, {"x-goog-api-key": "k"}) == {"echo": {"a": 1}, "key": "k"}
        with pytest.raises(free_ai.HTTPError) as err:
            free_ai.post_json(url, {"fail": True})
        assert err.value.status == 429 and err.value.message == "Quota exceeded"
    finally:
        urllib.request.install_opener(None)
        server.shutdown()


def test_gemini_tools_without_parameters_omit_them():
    decls = {d["name"]: d for d in free_ai.Gemini(Config(), "k").tools[0]["functionDeclarations"]}
    assert "parameters" not in decls["read_screen"] and "parameters" not in decls["list_windows"]
    assert decls["click"]["parameters"]["required"] == ["target"]


def test_memory_is_shared_when_gemini_hands_over_to_ollama(monkeypatch):
    monkeypatch.setattr(computer, "switch_to_window", lambda name: None, raising=False)
    gemini_post = FakePost(gemini_reply({"text": "Chrome it is. What are we looking at?"}),
                           free_ai.HTTPError(429, "Please retry in 40s."),
                           free_ai.HTTPError(429, "Please retry in 40s."))
    ollama_post = FakePost({"message": {"role": "assistant", "content": "Still in Chrome, closing it now."}})
    gemini = free_ai.Gemini(Config(), "k", post=gemini_post)
    ollama = free_ai.Ollama(Config(), post=ollama_post)
    brain = ai.Failover([gemini, ollama])

    brain("let's work in chrome")
    assert brain("close that tab") == "Still in Chrome, closing it now."
    messages = ollama_post.requests[0][1]["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1]["content"] == "let's work in chrome"
    assert messages[2]["content"] == "Chrome it is. What are we looking at?"


def test_ollama_json_written_as_text_is_run_not_spoken(monkeypatch):
    closed = []
    monkeypatch.setattr(computer, "close_app", lambda name: closed.append(name) or f"Closed {name}.")
    post = FakePost(
        {"message": {"role": "assistant", "content":
            'I\'ll try again.\n\n{"name": "close_app", "parameters": {"name":"microsoft edge"}}'}},
        {"message": {"role": "assistant", "content": "Edge is closed now."}},
    )
    o = free_ai.Ollama(Config(), post=post)
    assert o("close edge") == "Edge is closed now."
    assert closed == ["microsoft edge"]


def test_clean_speech():
    assert ai.clean_speech('Sure. {"name": "list_windows", "parameters": {}} Done!') == "Sure. Done!"
    assert ai.clean_speech("**Closed** it.\n[Actions: close_app(x) -> Closed x.]") == "Closed it."
    assert ai.clean_speech("See https://ai.google.dev/docs for more") == "See the link for more"


def test_gemini_thinking_setting_falls_back_per_model():
    post = FakePost(free_ai.HTTPError(400, 'Invalid JSON payload received. Unknown name "thinkingLevel"'),
                    gemini_reply({"text": "Hi."}), gemini_reply({"text": "Again."}))
    g = free_ai.Gemini(Config(), "k", post=post)
    assert g("hello") == "Hi."
    assert post.requests[0][1]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    assert post.requests[1][1]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
    g("again")
    assert post.requests[2][1]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}  # remembered


def test_ollama_gets_compact_tools_room_and_keep_alive():
    post = FakePost({"message": {"role": "assistant", "content": "Hi."}})
    free_ai.Ollama(Config(), post=post)("hello")
    body = post.requests[0][1]
    assert len(body["tools"]) == len(free_ai.OLLAMA_TOOLS) < len(ai.TOOLS)
    assert body["options"]["num_ctx"] >= 8192 and body["keep_alive"]


def test_gemini_timeout_tries_the_other_model():
    post = FakePost(TimeoutError("The read operation timed out"), gemini_reply({"text": "Here."}))
    assert free_ai.Gemini(Config(), "k", post=post)("hello") == "Here."
    assert post.requests[1][0].endswith("gemini-flash-lite-latest:generateContent")


def test_instructions_are_identical_between_requests_so_they_can_be_reused(monkeypatch):
    from datetime import datetime as real_datetime

    post = FakePost({"message": {"role": "assistant", "content": "One."}},
                    {"message": {"role": "assistant", "content": "Two."}})
    o = free_ai.Ollama(Config(), post=post)
    o("first")
    monkeypatch.setattr(ai, "current_context", lambda: "Right now:\n- Window in front: Steam")
    o("second")
    first, second = post.requests[0][1]["messages"], post.requests[1][1]["messages"]
    assert first[0] == second[0]                       # same system prompt, byte for byte
    assert len(first[0]["content"]) < 900              # and short, for a laptop CPU
    assert second[1] == {"role": "user", "content": "first"}  # history is stored without the note
    assert second[-1]["content"].startswith("second\n\n[Right now: ") and "Steam" in second[-1]["content"]


class Flaky(ai.Assistant):
    def __init__(self, label, fail_times=0):
        super().__init__(Config())
        self.label, self.fail_times, self.calls, self.healthy = label, fail_times, 0, True

    def _turn(self, text):
        self.calls += 1
        if self.fail_times:
            self.fail_times -= 1
            self.pause(60, "limit")
            return "limit"
        return f"{self.label}: {text}"

    def ping(self):
        return self.healthy


def test_failover_stays_on_the_backup_until_the_background_check_says_so(monkeypatch):
    gemini, ollama = Flaky("Gemini", fail_times=1), Flaky("Ollama")
    brain = ai.Failover([gemini, ollama], background_checks=False)
    assert brain("one") == "Ollama: one"
    gemini.unavailable_until = 0          # Gemini's rest is over...
    assert brain("two") == "Ollama: two"  # ...but we don't go back and gamble on every question
    assert brain("three") == "Ollama: three"
    assert gemini.calls == 1

    gemini.healthy = False
    brain.recheck()                        # background check: still not answering
    assert brain("four") == "Ollama: four"
    gemini.healthy = True
    brain.recheck()                        # background check: it answers again
    assert brain("five") == "Gemini: five"
