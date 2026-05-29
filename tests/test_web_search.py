"""Tests for the Pattern A /v1 web-search dispatch (W14-WEB-SEARCH-TIER1).

All MOCKED (no live HTTP).  Pins the verified MiMo shape (server-side,
inline annotations, console-toggle error hint) and the Kimi $web_search
client round-trip (echo args back -> grounded answer; thinking disabled).
"""
from harness.engines import web_search as ws


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "headers": headers, "json": json})
        return self._responses.pop(0)


def _patch_client(monkeypatch, responses, capture=None):
    client = _FakeClient(responses)
    if capture is not None:
        capture.append(client)
    monkeypatch.setattr(ws.httpx, "Client", lambda *a, **k: client)
    return client


# --- citation folding ---------------------------------------------------

def test_fold_citations_appends_sources():
    out = ws._fold_citations(
        "answer",
        [{"url": "http://a", "title": "A"}, {"url": "http://b", "site_name": "B"}],
    )
    assert out.startswith("answer")
    assert "Sources:" in out and "http://a" in out and "http://b" in out


def test_fold_citations_empty_or_urlless_is_noop():
    assert ws._fold_citations("answer", []) == "answer"
    assert ws._fold_citations("answer", [{"title": "no url"}]) == "answer"


# --- MiMo (server-side, inline annotations, no round-trip) --------------

def test_mimo_web_search_success_folds_annotations(monkeypatch):
    payload = {
        "choices": [{"message": {
            "content": "The answer.",
            "annotations": [{"url": "https://src/1", "title": "Src1"}],
        }}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 34},
    }
    cap = []
    _patch_client(monkeypatch, [_FakeResp(200, payload)], cap)
    r = ws.mimo_web_search("q", api_key="tp-test")
    assert r.success
    assert "The answer." in r.text and "https://src/1" in r.text
    assert r.tokens_in == 12 and r.tokens_out == 34
    # the web_search tool was declared in the request
    sent = cap[0].calls[0]["json"]
    assert sent["tools"][0]["type"] == "web_search"
    assert sent["tools"][0]["force_search"] is True


def test_mimo_web_search_console_toggle_hint(monkeypatch):
    err = {"error": {
        "code": "400", "message": "Param Incorrect",
        "param": ("web search tool found in the request body, but "
                  "webSearchEnabled is false"),
    }}
    _patch_client(monkeypatch, [_FakeResp(400, err)])
    r = ws.mimo_web_search("q", api_key="tp-test")
    assert not r.success
    # actionable: points at the console plugin page to enable it
    assert "console/plugin" in r.error


# --- Kimi ($web_search builtin_function, client round-trip) -------------

def test_kimi_web_search_round_trip(monkeypatch):
    turn1 = {"choices": [{"finish_reason": "tool_calls", "message": {
        "content": "",
        "tool_calls": [{"id": "ws:0", "type": "function", "function": {
            "name": "$web_search", "arguments": "{\"query\":\"x\"}"}}],
    }}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}
    turn2 = {"choices": [{"finish_reason": "stop", "message": {
        "content": "Grounded answer."}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 8}}
    cap = []
    _patch_client(monkeypatch, [_FakeResp(200, turn1), _FakeResp(200, turn2)], cap)
    r = ws.kimi_web_search("q", api_key="sk-test")
    assert r.success and r.text == "Grounded answer."
    # exactly two HTTP calls (the round-trip)
    assert len(cap[0].calls) == 2
    # turn 1 declares $web_search + disables thinking
    assert cap[0].calls[0]["json"]["thinking"] == {"type": "disabled"}
    assert cap[0].calls[0]["json"]["tools"][0]["function"]["name"] == "$web_search"
    # turn 2 echoes the tool_call args back as a role=tool message
    msgs = cap[0].calls[1]["json"]["messages"]
    assert any(m.get("role") == "tool" and m.get("name") == "$web_search"
               for m in msgs)
    # token usage accumulated across both turns
    assert r.tokens_in == 55 and r.tokens_out == 10


def test_kimi_web_search_direct_answer_no_tool(monkeypatch):
    direct = {"choices": [{"finish_reason": "stop", "message": {
        "content": "No search needed."}}], "usage": {}}
    cap = []
    _patch_client(monkeypatch, [_FakeResp(200, direct)], cap)
    r = ws.kimi_web_search("q", api_key="sk-test")
    assert r.success and r.text == "No search needed."
    assert len(cap[0].calls) == 1  # no round-trip


def test_kimi_web_search_error_surfaces(monkeypatch):
    _patch_client(monkeypatch, [_FakeResp(401, {"error": {"message": "bad key"}})])
    r = ws.kimi_web_search("q", api_key="sk-bad")
    assert not r.success and "bad key" in r.error


def test_kimi_web_search_targets_open_platform_by_default(monkeypatch):
    cap = []
    _patch_client(monkeypatch, [_FakeResp(200, {"choices": [{
        "finish_reason": "stop", "message": {"content": "ok"}}], "usage": {}})], cap)
    ws.kimi_web_search("q", api_key="sk-test")
    assert cap[0].calls[0]["url"] == ws.KIMI_OPEN_PLATFORM_ENDPOINT
