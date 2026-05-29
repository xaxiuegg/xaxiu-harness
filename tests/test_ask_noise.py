"""W14-ASK-NOISE 2026-05-29 (reviewer gap #3): per-engine noise detector.

The cross-vendor compare must flag a response that succeeded transport-wise
but is semantically garbage (empty body, or provider tool-call scaffolding
leaked into the text) so it doesn't silently corrupt the comparison.  The
detector is deliberately conservative — only unambiguous machinery tokens
count, never a legitimate prose answer.
"""
from harness.ask import AskResult, _assess_noise


def test_clean_prose_is_not_flagged():
    assert _assess_noise("The capital of France is Paris.") == ""


def test_prose_about_functions_is_not_flagged():
    # The word "function" / "tool" in ordinary prose must NOT trip the
    # tool-call detector — that's the whole point of using specific tokens.
    assert _assess_noise(
        "To define a function in Python use `def`; tools like black format it."
    ) == ""
    assert _assess_noise(
        "The function call convention passes arguments on the stack."
    ) == ""


def test_empty_body_flagged_as_empty():
    assert _assess_noise("") == "empty"
    assert _assess_noise("   \n\t  ") == "empty"


def test_tool_call_markup_flagged_as_tool_noise():
    assert _assess_noise('<tool_call>{"name": "search"}</tool_call>') == "tool-noise"
    assert _assess_noise('prefix {"tool_calls": [{"id": "1"}]} suffix') == "tool-noise"
    assert _assess_noise(
        "ok <|tool_calls_section_begin|> ... <|tool_call_begin|>"
    ) == "tool-noise"
    assert _assess_noise("I will $web_search for that") == "tool-noise"
    assert _assess_noise("<function_calls><invoke name=\"x\">") == "tool-noise"


def test_askresult_noise_defaults_to_empty():
    r = AskResult(
        engine="x", ok=True, elapsed_s=0.0, tokens_in=0, tokens_out=0,
        cost_usd=0.0, text="hi", error="", winning_alias="x", attempt_count=1,
    )
    assert r.noise == ""
