"""W14-HARNESS-ASK 2026-05-26 / W14-ASK-ROUTED 2026-05-27: tests for the
daily-driver ask CLI (routed default + --task + --panel modes)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from harness.ask import (
    AskResult,
    DEFAULT_ENGINES,
    _slugify,
    run_panel,
    save_panel,
)
from harness.cli import cli
from harness.engines.base import EngineResponse
from harness.engines.pool_dispatch import (
    PoolAttempt,
    PoolDispatchResult,
)
from harness.engines.routing_recommend import Recommendation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_pool_result(text: str = "OK", success: bool = True,
                     cost: float = 0.01) -> PoolDispatchResult:
    """Build a successful PoolDispatchResult for mocking."""
    resp = EngineResponse(
        success=success,
        text=text if success else "",
        latency_ms=500,
        tokens_in=100,
        tokens_out=50,
        cost_usd=cost,
        error="" if success else "auth failed",
    )
    return PoolDispatchResult(
        success=success,
        response=resp,
        attempts=[PoolAttempt(
            alias="k1", env_var="KIMI_API_KEY",
            success=success,
            category="up" if success else "auth-failed",
            error="",
            latency_ms=500,
        )],
        winning_alias="k1" if success else "",
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_normal_question(self) -> None:
        assert _slugify("Should we deprecate X?") == "should-we-deprecate-x"

    def test_strips_punctuation(self) -> None:
        assert _slugify("Foo, bar! Baz?") == "foo-bar-baz"

    def test_caps_length(self) -> None:
        long = "a" * 100
        assert len(_slugify(long, max_len=20)) == 20

    def test_empty(self) -> None:
        assert _slugify("") == "unnamed"
        assert _slugify("!!!") == "unnamed"

    def test_normalizes_whitespace(self) -> None:
        assert _slugify("foo   bar  baz") == "foo-bar-baz"


# ---------------------------------------------------------------------------
# run_panel
# ---------------------------------------------------------------------------


class TestRunPanel:
    def test_dispatches_all_engines(self) -> None:
        with patch(
            "harness.engines.pool_dispatch.dispatch_with_pool",
            return_value=_mock_pool_result(text="response"),
        ) as mock_dispatch:
            results = run_panel(
                "test question",
                engines=("kimi-via-claude", "mimo-via-claude"),
            )
        assert len(results) == 2
        assert all(r.ok for r in results)
        assert all(r.text == "response" for r in results)
        assert mock_dispatch.call_count == 2

    def test_preserves_engine_order_despite_parallel(self) -> None:
        # Even though dispatch is parallel, the result list is
        # ordered to match the input engine tuple
        with patch(
            "harness.engines.pool_dispatch.dispatch_with_pool",
            return_value=_mock_pool_result(),
        ):
            results = run_panel(
                "q",
                engines=(
                    "deepseek-via-claude",
                    "kimi-via-claude",
                    "mimo-via-claude",
                ),
            )
        assert [r.engine for r in results] == [
            "deepseek-via-claude",
            "kimi-via-claude",
            "mimo-via-claude",
        ]

    def test_handles_failure(self) -> None:
        with patch(
            "harness.engines.pool_dispatch.dispatch_with_pool",
            return_value=_mock_pool_result(success=False),
        ):
            results = run_panel("q", engines=("kimi-via-claude",))
        assert results[0].ok is False
        assert "auth" in results[0].error.lower()

    def test_handles_exception(self) -> None:
        with patch(
            "harness.engines.pool_dispatch.dispatch_with_pool",
            side_effect=RuntimeError("boom"),
        ):
            results = run_panel("q", engines=("kimi-via-claude",))
        assert results[0].ok is False
        assert "RuntimeError: boom" in results[0].error


# ---------------------------------------------------------------------------
# save_panel
# ---------------------------------------------------------------------------


class TestSavePanel:
    def _make_result(
        self, engine: str = "mimo-via-claude",
        text: str = "response text",
    ) -> AskResult:
        return AskResult(
            engine=engine, ok=True, elapsed_s=12.3,
            tokens_in=100, tokens_out=50, cost_usd=0.01,
            text=text, error="",
            winning_alias="k1", attempt_count=1,
        )

    def test_writes_question_md(self, tmp_path: Path) -> None:
        save_panel("my question", [self._make_result()], tmp_path)
        content = (tmp_path / "question.md").read_text(encoding="utf-8")
        assert "my question" in content

    def test_writes_per_engine_files(self, tmp_path: Path) -> None:
        save_panel("q", [
            self._make_result("kimi-via-claude", "k-resp"),
            self._make_result("mimo-via-claude", "m-resp"),
        ], tmp_path)
        kimi = (tmp_path / "kimi-via-claude.md").read_text(encoding="utf-8")
        mimo = (tmp_path / "mimo-via-claude.md").read_text(encoding="utf-8")
        assert "k-resp" in kimi
        assert "m-resp" in mimo

    def test_writes_summary_json(self, tmp_path: Path) -> None:
        save_panel("q", [
            self._make_result("kimi-via-claude"),
            self._make_result("mimo-via-claude"),
        ], tmp_path)
        summary = json.loads(
            (tmp_path / "summary.json").read_text(encoding="utf-8"),
        )
        assert summary["question"] == "q"
        assert len(summary["results"]) == 2
        assert "total_cost_usd" in summary
        assert summary["total_cost_usd"] == pytest.approx(0.02)
        assert summary["max_latency_s"] == pytest.approx(12.3)

    def test_writes_packet_md(self, tmp_path: Path) -> None:
        save_panel("my question", [
            self._make_result("kimi-via-claude", "kimi says X"),
            self._make_result("mimo-via-claude", "mimo says Y"),
        ], tmp_path)
        packet = (tmp_path / "packet.md").read_text(encoding="utf-8")
        # Question + both responses concatenated
        assert "my question" in packet
        assert "kimi says X" in packet
        assert "mimo says Y" in packet
        # Section headers
        assert "kimi-via-claude" in packet
        assert "mimo-via-claude" in packet

    def test_handles_failed_result(self, tmp_path: Path) -> None:
        failed = AskResult(
            engine="kimi-via-claude", ok=False, elapsed_s=5.0,
            tokens_in=0, tokens_out=0, cost_usd=0.0,
            text="", error="timeout after 180s",
            winning_alias="", attempt_count=3,
        )
        save_panel("q", [failed], tmp_path)
        per_engine = (
            tmp_path / "kimi-via-claude.md"
        ).read_text(encoding="utf-8")
        assert "FAILED" in per_engine
        assert "timeout" in per_engine

    def test_creates_dir_if_missing(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "dir"
        save_panel("q", [self._make_result()], out)
        assert out.exists()
        assert (out / "question.md").exists()

    def test_default_mode_is_panel(self, tmp_path: Path) -> None:
        """Backward compat: callers that don't pass mode= get panel."""
        save_panel("q", [self._make_result()], tmp_path)
        summary = json.loads(
            (tmp_path / "summary.json").read_text(encoding="utf-8"),
        )
        assert summary["mode"] == "panel"
        # Panel writes packet.md
        assert (tmp_path / "packet.md").exists()

    def test_routed_mode_skips_packet_md(self, tmp_path: Path) -> None:
        """W14-ASK-ROUTED: single-engine routed mode = no packet.md.

        The lone per-engine file IS the synthesis-ready artifact; a
        packet.md wrapping one engine's output adds zero value.
        """
        save_panel(
            "q", [self._make_result("mimo-via-claude", "answer")],
            tmp_path, mode="routed",
        )
        assert (tmp_path / "question.md").exists()
        assert (tmp_path / "mimo-via-claude.md").exists()
        assert (tmp_path / "summary.json").exists()
        # KEY: no packet.md in routed mode
        assert not (tmp_path / "packet.md").exists()

    def test_summary_mode_field_routed(self, tmp_path: Path) -> None:
        save_panel(
            "q", [self._make_result()], tmp_path, mode="routed",
        )
        summary = json.loads(
            (tmp_path / "summary.json").read_text(encoding="utf-8"),
        )
        assert summary["mode"] == "routed"

    def test_summary_mode_field_panel(self, tmp_path: Path) -> None:
        save_panel(
            "q", [self._make_result()], tmp_path, mode="panel",
        )
        summary = json.loads(
            (tmp_path / "summary.json").read_text(encoding="utf-8"),
        )
        assert summary["mode"] == "panel"

    def test_extra_summary_merges(self, tmp_path: Path) -> None:
        """extra_summary keys are surfaced in summary.json (used by --audit)."""
        save_panel(
            "q", [self._make_result()], tmp_path,
            mode="audit",
            extra_summary={"verdict": "PASS", "auditor_engine": "deepseek-via-claude"},
        )
        summary = json.loads(
            (tmp_path / "summary.json").read_text(encoding="utf-8"),
        )
        assert summary["verdict"] == "PASS"
        assert summary["auditor_engine"] == "deepseek-via-claude"
        assert summary["mode"] == "audit"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestAskCli:
    def test_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["ask", "--help"])
        assert result.exit_code == 0
        assert "cross-engine panel" in result.output.lower()

    def test_requires_question_or_file(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["ask"])
        assert result.exit_code != 0
        assert "question" in (result.output + result.stderr_bytes.decode(
            "utf-8", errors="replace",
        )).lower() or "error" in result.output.lower()

    def test_dispatches_with_question_argument(
        self, tmp_path: Path,
    ) -> None:
        runner = CliRunner()
        with patch(
            "harness.engines.pool_dispatch.dispatch_with_pool",
            return_value=_mock_pool_result(text="answer"),
        ):
            result = runner.invoke(cli, [
                "ask", "test question",
                "--no-save",
                "--engines", "kimi-via-claude",
            ])
        assert result.exit_code == 0
        # Summary table includes the engine
        assert "kimi-via-claude" in result.output

    def test_dispatches_from_file(self, tmp_path: Path) -> None:
        q_file = tmp_path / "q.md"
        q_file.write_text("question from file", encoding="utf-8")
        runner = CliRunner()
        with patch(
            "harness.engines.pool_dispatch.dispatch_with_pool",
            return_value=_mock_pool_result(text="reply"),
        ):
            result = runner.invoke(cli, [
                "ask",
                "--file", str(q_file),
                "--no-save",
                "--engines", "mimo-via-claude",
            ])
        assert result.exit_code == 0
        assert "mimo-via-claude" in result.output

    def test_saves_to_output_dir(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with patch(
            "harness.engines.pool_dispatch.dispatch_with_pool",
            return_value=_mock_pool_result(text="saved-response"),
        ):
            result = runner.invoke(cli, [
                "ask", "test",
                "--engines", "kimi-via-claude",
                "--output", str(tmp_path / "panel"),
            ])
        assert result.exit_code == 0
        out = tmp_path / "panel"
        assert (out / "question.md").exists()
        assert (out / "summary.json").exists()
        assert (out / "packet.md").exists()
        assert (out / "kimi-via-claude.md").exists()

    def test_print_text_dumps_response(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with patch(
            "harness.engines.pool_dispatch.dispatch_with_pool",
            return_value=_mock_pool_result(text="VISIBLE-RESPONSE-TEXT"),
        ):
            result = runner.invoke(cli, [
                "ask", "test",
                "--no-save",
                "--print-text",
                "--engines", "kimi-via-claude",
            ])
        assert result.exit_code == 0
        assert "VISIBLE-RESPONSE-TEXT" in result.output

    def test_fail_exit_code_when_engine_fails(
        self, tmp_path: Path,
    ) -> None:
        runner = CliRunner()
        with patch(
            "harness.engines.pool_dispatch.dispatch_with_pool",
            return_value=_mock_pool_result(success=False),
        ):
            result = runner.invoke(cli, [
                "ask", "test",
                "--no-save",
                "--engines", "kimi-via-claude",
            ])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# W14-ASK-ROUTED 2026-05-27: routed default + --task + --panel + pin precedence
# ---------------------------------------------------------------------------


def _mock_recommendation(
    engine: str = "mimo-via-claude",
    rationale: str = "Test rationale.",
    alternates: tuple[str, ...] = ("deepseek-via-claude",),
) -> Recommendation:
    return Recommendation(
        engine=engine, alternates=alternates, rationale=rationale,
    )


class TestAskRoutedDefault:
    """Bare `harness ask "..."` (no flags) routes through the recommender
    and dispatches ONE engine."""

    def test_bare_ask_uses_routed_default(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
                return_value=_mock_recommendation("mimo-via-claude"),
            ) as mock_rec,
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                return_value=_mock_pool_result(text="routed-answer"),
            ) as mock_dispatch,
        ):
            result = runner.invoke(cli, [
                "ask", "test question", "--no-save",
            ])
        assert result.exit_code == 0
        # Recommender consulted exactly once for task="default"
        mock_rec.assert_called_once()
        args, kwargs = mock_rec.call_args
        assert (args and args[0] == "default") or kwargs.get("task_class") == "default"
        # Dispatch fired exactly once (single engine, not 3-panel)
        assert mock_dispatch.call_count == 1
        # Banner mentions routed mode
        assert "routed" in result.output.lower()
        # Per-engine row visible
        assert "mimo-via-claude" in result.output

    def test_task_flag_passes_through_to_recommender(
        self, tmp_path: Path,
    ) -> None:
        runner = CliRunner()
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
                return_value=_mock_recommendation("deepseek-via-claude"),
            ) as mock_rec,
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                return_value=_mock_pool_result(text="fast-answer"),
            ),
        ):
            result = runner.invoke(cli, [
                "ask", "test", "--no-save", "--task", "latency",
            ])
        assert result.exit_code == 0
        mock_rec.assert_called_once()
        args, kwargs = mock_rec.call_args
        assert (args and args[0] == "latency") or kwargs.get("task_class") == "latency"
        assert "deepseek-via-claude" in result.output

    def test_invalid_task_rejected_by_click(self, tmp_path: Path) -> None:
        """Click.Choice surfaces clean error on typo; recommender is
        not silently invoked with fallback."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "ask", "test", "--no-save", "--task", "fastest",
        ])
        # Click exit code for invalid value is 2
        assert result.exit_code == 2
        # Message names the bad value
        assert "fastest" in (result.output + (
            result.stderr_bytes.decode("utf-8", errors="replace")
            if hasattr(result, "stderr_bytes") else ""
        )).lower()

    def test_routed_mode_writes_no_packet_md(self, tmp_path: Path) -> None:
        """End-to-end: bare ask saves question.md + <engine>.md +
        summary.json but NOT packet.md."""
        runner = CliRunner()
        out = tmp_path / "panel"
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
                return_value=_mock_recommendation("mimo-via-claude"),
            ),
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                return_value=_mock_pool_result(text="answer"),
            ),
        ):
            result = runner.invoke(cli, [
                "ask", "test", "--output", str(out),
            ])
        assert result.exit_code == 0
        assert (out / "question.md").exists()
        assert (out / "mimo-via-claude.md").exists()
        assert (out / "summary.json").exists()
        assert not (out / "packet.md").exists()
        # summary.json carries mode="routed"
        summary = json.loads(
            (out / "summary.json").read_text(encoding="utf-8"),
        )
        assert summary["mode"] == "routed"


class TestAskPanelFlag:
    """`--panel` preserves the legacy 3-engine parallel fanout."""

    def test_panel_flag_uses_three_engines(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
            ) as mock_rec,
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                return_value=_mock_pool_result(text="response"),
            ) as mock_dispatch,
        ):
            result = runner.invoke(cli, [
                "ask", "test", "--no-save", "--panel",
            ])
        assert result.exit_code == 0
        # Recommender is NOT consulted for --panel mode
        mock_rec.assert_not_called()
        # All 3 Pattern B engines were dispatched
        assert mock_dispatch.call_count == 3
        engines_called = {
            call.args[0] for call in mock_dispatch.call_args_list
        }
        assert engines_called == set(DEFAULT_ENGINES)

    def test_panel_mode_writes_packet_md(self, tmp_path: Path) -> None:
        runner = CliRunner()
        out = tmp_path / "panel"
        with patch(
            "harness.engines.pool_dispatch.dispatch_with_pool",
            return_value=_mock_pool_result(text="resp"),
        ):
            result = runner.invoke(cli, [
                "ask", "test", "--output", str(out), "--panel",
            ])
        assert result.exit_code == 0
        # Panel mode writes packet.md
        assert (out / "packet.md").exists()
        summary = json.loads(
            (out / "summary.json").read_text(encoding="utf-8"),
        )
        assert summary["mode"] == "panel"


class TestAskEnginesPin:
    """`--engines X` pinning ALWAYS wins.  HANDOFF.md step 7 + scripted
    callers depend on this — must not regress."""

    def test_pin_overrides_task(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
            ) as mock_rec,
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                return_value=_mock_pool_result(text="pinned"),
            ) as mock_dispatch,
        ):
            result = runner.invoke(cli, [
                "ask", "test", "--no-save",
                "--task", "latency",  # would pick deepseek if recommender ran
                "--engines", "kimi-via-claude",  # pinned
            ])
        assert result.exit_code == 0
        # Pin short-circuits recommender entirely
        mock_rec.assert_not_called()
        # Only the pinned engine dispatched
        assert mock_dispatch.call_count == 1
        assert mock_dispatch.call_args_list[0].args[0] == "kimi-via-claude"

    def test_pin_overrides_panel(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with patch(
            "harness.engines.pool_dispatch.dispatch_with_pool",
            return_value=_mock_pool_result(text="pinned"),
        ) as mock_dispatch:
            result = runner.invoke(cli, [
                "ask", "test", "--no-save",
                "--panel",  # ignored
                "--engines", "kimi-via-claude",
            ])
        assert result.exit_code == 0
        # Only the pinned engine dispatched (panel ignored)
        assert mock_dispatch.call_count == 1
        assert mock_dispatch.call_args_list[0].args[0] == "kimi-via-claude"

    def test_handoff_step7_invocation_unchanged(
        self, tmp_path: Path,
    ) -> None:
        """HANDOFF.md step 7 verifies setup with:

            harness ask "Reply with the single word OK." \\
                --engines mimo-via-claude --no-save --max-budget-usd 0.05

        Must exit 0 and call dispatch exactly once with mimo-via-claude.
        Any future redesign must keep this surface working.
        """
        runner = CliRunner()
        with patch(
            "harness.engines.pool_dispatch.dispatch_with_pool",
            return_value=_mock_pool_result(text="OK"),
        ) as mock_dispatch:
            result = runner.invoke(cli, [
                "ask", "Reply with the single word OK.",
                "--engines", "mimo-via-claude",
                "--no-save",
                "--max-budget-usd", "0.05",
            ])
        assert result.exit_code == 0
        assert mock_dispatch.call_count == 1
        assert mock_dispatch.call_args_list[0].args[0] == "mimo-via-claude"
        assert "mimo-via-claude" in result.output


# ---------------------------------------------------------------------------
# W14-ASK-AUDIT 2026-05-27: audit prompt + parser + producer→auditor flow
# ---------------------------------------------------------------------------


class TestAuditPrompt:
    """Unit tests for the audit prompt template + verdict parser."""

    def test_build_audit_prompt_includes_question(self) -> None:
        from harness.audit_prompt import build_audit_prompt
        prompt = build_audit_prompt(
            question="Is MiMo Anthropic-only?",
            producer_engine="mimo-via-claude",
            producer_response="Yes, MiMo only speaks Anthropic protocol.",
        )
        assert "Is MiMo Anthropic-only?" in prompt
        assert "mimo-via-claude" in prompt
        assert "MiMo only speaks Anthropic protocol" in prompt
        # Rubric sections present
        assert "VERDICT:" in prompt
        assert "CORRECTIONS:" in prompt
        assert "MISSED CONSIDERATIONS:" in prompt
        assert "OVERALL:" in prompt

    def test_build_audit_prompt_strips_whitespace(self) -> None:
        from harness.audit_prompt import build_audit_prompt
        prompt = build_audit_prompt(
            question="  q  \n", producer_engine="X", producer_response="\n  a  \n",
        )
        # No stray leading/trailing whitespace inside the rendered fields
        assert "QUESTION:\nq\n" in prompt
        assert "(from X):\na" in prompt


class TestParseAuditVerdict:
    """Parser unit tests."""

    def test_full_pass_verdict(self) -> None:
        from harness.audit_prompt import parse_audit_verdict
        text = (
            "VERDICT: PASS\n"
            "ONE-LINE SUMMARY: Answer is correct and complete.\n"
            "CORRECTIONS: none\n"
            "MISSED CONSIDERATIONS: none\n"
            "OVERALL: The answer addresses the question fully and accurately.\n"
        )
        v = parse_audit_verdict(text)
        assert v["verdict"] == "PASS"
        assert "correct and complete" in v["summary"]
        assert v["corrections"].lower() == "none"
        assert v["missed"].lower() == "none"
        assert "fully and accurately" in v["overall"]

    def test_partial_verdict_with_corrections(self) -> None:
        from harness.audit_prompt import parse_audit_verdict
        text = (
            "VERDICT: PARTIAL\n"
            "ONE-LINE SUMMARY: Mostly right; missed one protocol path.\n"
            "CORRECTIONS:\n"
            "- MiMo has TWO surfaces, not one.\n"
            "- The /v1/chat/completions endpoint IS OpenAI-shape.\n"
            "MISSED CONSIDERATIONS: Token Plan UA gating.\n"
            "OVERALL: The producer conflated MiMo's two API surfaces.\n"
        )
        v = parse_audit_verdict(text)
        assert v["verdict"] == "PARTIAL"
        assert "TWO surfaces" in v["corrections"]
        assert "/v1/chat/completions" in v["corrections"]
        assert "Token Plan UA gating" in v["missed"]

    def test_fail_verdict(self) -> None:
        from harness.audit_prompt import parse_audit_verdict
        text = (
            "VERDICT: FAIL\n"
            "ONE-LINE SUMMARY: Off-topic.\n"
            "CORRECTIONS: The answer ignored the question.\n"
            "MISSED CONSIDERATIONS: All of them.\n"
            "OVERALL: Total miss.\n"
        )
        v = parse_audit_verdict(text)
        assert v["verdict"] == "FAIL"

    def test_missing_verdict_returns_unknown(self) -> None:
        from harness.audit_prompt import parse_audit_verdict
        text = "Sorry I don't have a verdict for this question."
        v = parse_audit_verdict(text)
        assert v["verdict"] == "UNKNOWN"
        assert v["raw"] == text

    def test_handles_one_line_summary_variants(self) -> None:
        """LLMs sometimes drop the hyphen ("ONE LINE SUMMARY")."""
        from harness.audit_prompt import parse_audit_verdict
        text = (
            "VERDICT: PASS\n"
            "ONE LINE SUMMARY: looks fine.\n"
            "CORRECTIONS: none\n"
            "MISSED CONSIDERATIONS: none\n"
            "OVERALL: ok.\n"
        )
        v = parse_audit_verdict(text)
        assert v["verdict"] == "PASS"
        assert "looks fine" in v["summary"]

    def test_case_insensitive_headers(self) -> None:
        from harness.audit_prompt import parse_audit_verdict
        text = (
            "verdict: pass\n"
            "one-line summary: yep\n"
            "corrections: none\n"
            "missed considerations: none\n"
            "overall: ok\n"
        )
        v = parse_audit_verdict(text)
        assert v["verdict"] == "PASS"
        assert v["summary"] == "yep"

    def test_empty_text_safe(self) -> None:
        from harness.audit_prompt import parse_audit_verdict
        v = parse_audit_verdict("")
        assert v["verdict"] == "UNKNOWN"
        assert v["raw"] == ""

    def test_none_text_safe(self) -> None:
        from harness.audit_prompt import parse_audit_verdict
        v = parse_audit_verdict(None)  # type: ignore[arg-type]
        assert v["verdict"] == "UNKNOWN"


class TestRunAudit:
    """Producer → auditor flow tests."""

    def test_producer_failure_skips_auditor(self) -> None:
        """If the producer fails, the audit step is skipped."""
        from harness.ask import run_audit
        with patch(
            "harness.engines.pool_dispatch.dispatch_with_pool",
            return_value=_mock_pool_result(success=False),
        ) as mock_dispatch:
            outcome = run_audit(
                "q", producer_engine="mimo-via-claude",
            )
        # Dispatch fired exactly once (just the producer)
        assert mock_dispatch.call_count == 1
        assert outcome.producer.ok is False
        assert outcome.auditor is None
        assert outcome.verdict is None
        assert outcome.auditor_engine == ""

    def test_auditor_uses_exclude_producer(self) -> None:
        """recommend('audit', exclude={producer_engine}) is called so
        the auditor is always a different engine label (D-i: engine-
        label dedup)."""
        from harness.ask import run_audit
        producer_resp = _mock_pool_result(text="producer answer")
        auditor_resp = _mock_pool_result(
            text=(
                "VERDICT: PASS\n"
                "ONE-LINE SUMMARY: ok\n"
                "CORRECTIONS: none\n"
                "MISSED CONSIDERATIONS: none\n"
                "OVERALL: fine\n"
            )
        )
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
                return_value=_mock_recommendation("deepseek-via-claude"),
            ) as mock_rec,
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                side_effect=[producer_resp, auditor_resp],
            ) as mock_dispatch,
        ):
            outcome = run_audit(
                "q", producer_engine="mimo-via-claude",
            )
        # Recommender called with audit class + exclude={producer}
        mock_rec.assert_called_once()
        call_args = mock_rec.call_args
        # 1st positional arg = "audit"
        assert call_args.args[0] == "audit"
        # exclude kwarg contains producer
        excl = call_args.kwargs.get("exclude") or set()
        assert "mimo-via-claude" in excl
        # 2 dispatches: producer + auditor
        assert mock_dispatch.call_count == 2
        # Auditor got the audit prompt (contains VERDICT label)
        auditor_call = mock_dispatch.call_args_list[1]
        auditor_engine = auditor_call.args[0]
        auditor_prompt = auditor_call.args[1]
        assert auditor_engine == "deepseek-via-claude"
        assert "VERDICT" in auditor_prompt
        assert "producer answer" in auditor_prompt
        # Outcome packs the verdict
        assert outcome.auditor is not None
        assert outcome.verdict is not None
        assert outcome.verdict["verdict"] == "PASS"

    def test_audit_engine_override_skips_recommender(self) -> None:
        from harness.ask import run_audit
        producer_resp = _mock_pool_result(text="answer")
        auditor_resp = _mock_pool_result(
            text="VERDICT: PASS\nONE-LINE SUMMARY: ok\nOVERALL: ok\n"
        )
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
            ) as mock_rec,
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                side_effect=[producer_resp, auditor_resp],
            ) as mock_dispatch,
        ):
            outcome = run_audit(
                "q", producer_engine="mimo-via-claude",
                audit_engine_override="kimi-via-claude",
            )
        # Recommender NOT consulted
        mock_rec.assert_not_called()
        # Auditor dispatched against the overridden engine
        auditor_engine = mock_dispatch.call_args_list[1].args[0]
        assert auditor_engine == "kimi-via-claude"
        assert outcome.auditor_engine == "kimi-via-claude"

    def test_auditor_dispatch_failure_yields_unknown_verdict(self) -> None:
        from harness.ask import run_audit
        producer_resp = _mock_pool_result(text="answer")
        auditor_resp = _mock_pool_result(success=False)
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
                return_value=_mock_recommendation("deepseek-via-claude"),
            ),
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                side_effect=[producer_resp, auditor_resp],
            ),
        ):
            outcome = run_audit("q", producer_engine="mimo-via-claude")
        # Auditor dispatch was attempted but failed; verdict surfaces UNKNOWN
        assert outcome.producer.ok is True
        assert outcome.auditor is not None
        assert outcome.auditor.ok is False
        assert outcome.verdict is not None
        assert outcome.verdict["verdict"] == "UNKNOWN"


class TestAuditCli:
    """End-to-end --audit flag through the CLI."""

    def test_audit_flag_runs_producer_then_auditor(
        self, tmp_path: Path,
    ) -> None:
        runner = CliRunner()
        producer_resp = _mock_pool_result(text="The answer is yes.")
        auditor_resp = _mock_pool_result(
            text=(
                "VERDICT: PASS\n"
                "ONE-LINE SUMMARY: correct.\n"
                "CORRECTIONS: none\n"
                "MISSED CONSIDERATIONS: none\n"
                "OVERALL: ok.\n"
            )
        )
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
                side_effect=[
                    # Routed default pick (producer)
                    _mock_recommendation("mimo-via-claude"),
                    # Audit pick (auditor)
                    _mock_recommendation("deepseek-via-claude"),
                ],
            ),
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                side_effect=[producer_resp, auditor_resp],
            ) as mock_dispatch,
        ):
            result = runner.invoke(cli, [
                "ask", "test question",
                "--audit",
                "--output", str(tmp_path / "out"),
            ])
        assert result.exit_code == 0
        assert mock_dispatch.call_count == 2
        # Banner mentions audit + producer
        assert "audit" in result.output.lower()
        assert "VERDICT:" in result.output or "PASS" in result.output
        # Output dir contains expected files
        out = tmp_path / "out"
        assert (out / "question.md").exists()
        assert (out / "producer-mimo-via-claude.md").exists()
        assert (out / "audit-deepseek-via-claude.md").exists()
        assert (out / "packet.md").exists()
        # Summary carries audit metadata
        summary = json.loads(
            (out / "summary.json").read_text(encoding="utf-8"),
        )
        assert summary["mode"] == "audit"
        assert summary["producer_engine"] == "mimo-via-claude"
        assert summary["auditor_engine"] == "deepseek-via-claude"
        assert summary["verdict"]["verdict"] == "PASS"

    def test_audit_engine_flag_implies_audit(
        self, tmp_path: Path,
    ) -> None:
        """--audit-engine X without --audit should still trigger audit
        mode (UX convenience)."""
        runner = CliRunner()
        producer_resp = _mock_pool_result(text="answer")
        auditor_resp = _mock_pool_result(
            text="VERDICT: PASS\nONE-LINE SUMMARY: ok\nOVERALL: ok\n"
        )
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
                return_value=_mock_recommendation("mimo-via-claude"),
            ),
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                side_effect=[producer_resp, auditor_resp],
            ) as mock_dispatch,
        ):
            result = runner.invoke(cli, [
                "ask", "test",
                "--audit-engine", "kimi-via-claude",
                "--no-save",
            ])
        assert result.exit_code == 0
        # Two dispatches (producer + auditor), auditor=kimi via override
        assert mock_dispatch.call_count == 2
        assert mock_dispatch.call_args_list[1].args[0] == "kimi-via-claude"

    def test_audit_plus_panel_rejected(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, [
            "ask", "test", "--audit", "--panel", "--no-save",
        ])
        assert result.exit_code == 2
        assert "audit" in result.output.lower()
        assert "panel" in result.output.lower()

    def test_audit_plus_multi_engine_rejected(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, [
            "ask", "test", "--audit",
            "--engines", "mimo-via-claude,kimi-via-claude",
            "--no-save",
        ])
        assert result.exit_code == 2
        assert "audit" in result.output.lower()
        assert "producer" in result.output.lower()

    def test_audit_with_single_engine_pin_ok(self, tmp_path: Path) -> None:
        """--audit + --engines <single> is fine — the pinned engine
        becomes the producer."""
        runner = CliRunner()
        producer_resp = _mock_pool_result(text="answer")
        auditor_resp = _mock_pool_result(
            text="VERDICT: PASS\nONE-LINE SUMMARY: ok\nOVERALL: ok\n"
        )
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
                return_value=_mock_recommendation("deepseek-via-claude"),
            ) as mock_rec,
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                side_effect=[producer_resp, auditor_resp],
            ) as mock_dispatch,
        ):
            result = runner.invoke(cli, [
                "ask", "test", "--audit",
                "--engines", "kimi-via-claude",
                "--no-save",
            ])
        assert result.exit_code == 0
        # Producer = pinned kimi; recommender consulted only for the
        # auditor pick (NOT for the routed default)
        mock_rec.assert_called_once()
        assert mock_rec.call_args.args[0] == "audit"
        assert mock_dispatch.call_args_list[0].args[0] == "kimi-via-claude"
        assert mock_dispatch.call_args_list[1].args[0] == "deepseek-via-claude"

class TestAskResearch:
    """W14-ASK-RESEARCH 2026-05-28 (Phase 4.2): --research <file>
    prepends pre-fetched context to the question for synthesis."""

    def test_research_flag_prepends_context(self, tmp_path: Path) -> None:
        runner = CliRunner()
        research = tmp_path / "findings.md"
        research.write_text(
            "# Findings\n\nSource: example.com\n- fact 1\n- fact 2\n",
            encoding="utf-8",
        )
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
                return_value=_mock_recommendation("mimo-via-claude"),
            ),
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                return_value=_mock_pool_result(text="synthesis"),
            ) as mock_dispatch,
        ):
            result = runner.invoke(cli, [
                "ask", "is X true?",
                "--research", str(research),
                "--no-save",
            ])
        assert result.exit_code == 0
        # The dispatch prompt should contain BOTH the question AND
        # the research context, in the documented framing
        called_prompt = mock_dispatch.call_args_list[0].args[1]
        assert "RESEARCH CONTEXT" in called_prompt
        assert "fact 1" in called_prompt
        assert "QUESTION" in called_prompt
        assert "is X true" in called_prompt

    def test_research_saves_findings_to_output_dir(
        self, tmp_path: Path,
    ) -> None:
        runner = CliRunner()
        research = tmp_path / "findings.md"
        research.write_text("# Notes\n\nFinding A.\n", encoding="utf-8")
        out = tmp_path / "out"
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
                return_value=_mock_recommendation("mimo-via-claude"),
            ),
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                return_value=_mock_pool_result(text="synthesis"),
            ),
        ):
            result = runner.invoke(cli, [
                "ask", "what next?",
                "--research", str(research),
                "--output", str(out),
            ])
        assert result.exit_code == 0
        # A research.md copy is persisted alongside the engine response
        assert (out / "research.md").exists()
        copied = (out / "research.md").read_text(encoding="utf-8")
        assert "Finding A" in copied
        # summary.json records the findings metadata
        summary = json.loads(
            (out / "summary.json").read_text(encoding="utf-8"),
        )
        assert summary["research_findings_chars"] > 0
        assert "findings.md" in summary["research_findings_source"]

    def test_research_with_audit_layers_correctly(
        self, tmp_path: Path,
    ) -> None:
        """--research + --audit: producer uses research context;
        auditor sees the synthesized answer (NOT the raw research)."""
        runner = CliRunner()
        research = tmp_path / "research.md"
        research.write_text(
            "RFC 9999 says X is true.\n", encoding="utf-8",
        )
        producer_resp = _mock_pool_result(text="X is true per RFC 9999.")
        auditor_resp = _mock_pool_result(
            text="VERDICT: PASS\nONE-LINE SUMMARY: ok\nOVERALL: ok\n"
        )
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
                side_effect=[
                    _mock_recommendation("mimo-via-claude"),
                    _mock_recommendation("deepseek-via-claude"),
                ],
            ),
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                side_effect=[producer_resp, auditor_resp],
            ) as mock_dispatch,
        ):
            result = runner.invoke(cli, [
                "ask", "is X true?",
                "--research", str(research),
                "--audit",
                "--output", str(tmp_path / "audit-research"),
            ])
        assert result.exit_code == 0
        # Producer prompt contains research context
        producer_prompt = mock_dispatch.call_args_list[0].args[1]
        assert "RFC 9999" in producer_prompt
        # Auditor prompt contains the SYNTHESIS, not the raw research
        # (audit_prompt template wraps the producer's answer)
        auditor_prompt = mock_dispatch.call_args_list[1].args[1]
        assert "X is true per RFC 9999" in auditor_prompt
        assert "VERDICT" in auditor_prompt  # the audit-prompt rubric

    def test_research_missing_file_errors(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, [
            "ask", "q",
            "--research", "/nonexistent/file.md",
            "--no-save",
        ])
        # Click's path-exists check fires before our handler — exit 2
        assert result.exit_code == 2


class TestAuditQuorum:
    """W14-AUDITORS-QUORUM 2026-05-28: multi-auditor (--auditors N)
    quorum support."""

    def test_aggregate_all_pass(self) -> None:
        from harness.ask import _aggregate_verdicts
        agg = _aggregate_verdicts([
            {"verdict": "PASS", "summary": "fine", "corrections": "none",
             "missed": "none", "overall": ""},
            {"verdict": "PASS", "summary": "fine", "corrections": "none",
             "missed": "none", "overall": ""},
        ])
        assert agg["verdict"] == "PASS"
        assert "Quorum of 2 auditors" in agg["summary"]

    def test_aggregate_all_fail(self) -> None:
        from harness.ask import _aggregate_verdicts
        agg = _aggregate_verdicts([
            {"verdict": "FAIL", "summary": "x", "corrections": "",
             "missed": "", "overall": ""},
            {"verdict": "FAIL", "summary": "x", "corrections": "",
             "missed": "", "overall": ""},
        ])
        assert agg["verdict"] == "FAIL"

    def test_aggregate_mixed_pass_fail_returns_partial(self) -> None:
        from harness.ask import _aggregate_verdicts
        agg = _aggregate_verdicts([
            {"verdict": "PASS", "summary": "", "corrections": "",
             "missed": "", "overall": ""},
            {"verdict": "FAIL", "summary": "", "corrections": "",
             "missed": "", "overall": ""},
        ])
        # PASS=2, FAIL=0, avg=1 → PARTIAL
        assert agg["verdict"] == "PARTIAL"
        assert "split" in agg["summary"].lower()

    def test_aggregate_pass_partial_leans_pass(self) -> None:
        from harness.ask import _aggregate_verdicts
        agg = _aggregate_verdicts([
            {"verdict": "PASS", "summary": "", "corrections": "",
             "missed": "", "overall": ""},
            {"verdict": "PARTIAL", "summary": "", "corrections": "",
             "missed": "", "overall": ""},
        ])
        # PASS=2, PARTIAL=1, avg=1.5 → PASS (boundary)
        assert agg["verdict"] == "PASS"

    def test_aggregate_all_unknown(self) -> None:
        from harness.ask import _aggregate_verdicts
        agg = _aggregate_verdicts([
            {"verdict": "UNKNOWN", "summary": "", "corrections": "",
             "missed": "", "overall": ""},
            {"verdict": "UNKNOWN", "summary": "", "corrections": "",
             "missed": "", "overall": ""},
        ])
        assert agg["verdict"] == "UNKNOWN"

    def test_aggregate_includes_per_auditor_breakdown(self) -> None:
        from harness.ask import _aggregate_verdicts
        agg = _aggregate_verdicts([
            {"verdict": "PASS", "summary": "", "corrections": "",
             "missed": "", "overall": ""},
            {"verdict": "FAIL", "summary": "", "corrections": "x",
             "missed": "", "overall": ""},
        ])
        assert "auditor_breakdown" in agg
        assert len(agg["auditor_breakdown"]) == 2
        verdicts_seen = {b["verdict"] for b in agg["auditor_breakdown"]}
        assert verdicts_seen == {"PASS", "FAIL"}

    def test_pick_auditor_engines_returns_up_to_n(self) -> None:
        from harness.ask import _pick_auditor_engines
        # 2 alternates available when producer is one of the 3 Pattern B
        # engines: should return 2 entries when asked for N=2.
        specs = _pick_auditor_engines("mimo-via-claude", num_auditors=2)
        assert len(specs) == 2
        # Each entry is (engine, model_override)
        for eng, mo in specs:
            assert eng != "mimo-via-claude"

    def test_pick_auditor_engines_caps_at_available(self) -> None:
        """If we ask for 3 auditors but only 2 alternates exist, cap at 2."""
        from harness.ask import _pick_auditor_engines
        specs = _pick_auditor_engines("mimo-via-claude", num_auditors=3)
        # Currently 3 Pattern B engines → producer + 2 alternates → cap=2
        assert len(specs) <= 2

    def test_run_audit_num_auditors_2_dispatches_3_total(self) -> None:
        """1 producer + 2 auditors = 3 dispatches."""
        from harness.ask import run_audit
        producer_resp = _mock_pool_result(text="answer")
        a1 = _mock_pool_result(
            text="VERDICT: PASS\nONE-LINE SUMMARY: ok\nOVERALL: ok\n"
        )
        a2 = _mock_pool_result(
            text="VERDICT: PARTIAL\nONE-LINE SUMMARY: kinda\nOVERALL: ok\n"
        )
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
                side_effect=[
                    _mock_recommendation("deepseek-via-claude"),
                    _mock_recommendation("kimi-via-claude"),
                ],
            ),
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                side_effect=[producer_resp, a1, a2],
            ) as mock_dispatch,
        ):
            outcome = run_audit(
                "q", producer_engine="mimo-via-claude",
                num_auditors=2,
            )
        # 3 total dispatches
        assert mock_dispatch.call_count == 3
        # 2 auditors in outcome
        assert len(outcome.auditors) == 2
        assert len(outcome.verdicts) == 2
        # Aggregate verdict computed (PASS + PARTIAL → PASS, avg=1.5)
        assert outcome.verdict["verdict"] == "PASS"
        # auditor_engines list populated
        assert set(outcome.auditor_engines) == {
            "deepseek-via-claude", "kimi-via-claude",
        }

    def test_cli_auditors_2_writes_two_audit_files(
        self, tmp_path: Path,
    ) -> None:
        runner = CliRunner()
        producer_resp = _mock_pool_result(text="answer")
        a1 = _mock_pool_result(
            text="VERDICT: PASS\nONE-LINE SUMMARY: ok\nOVERALL: ok\n"
        )
        a2 = _mock_pool_result(
            text="VERDICT: PASS\nONE-LINE SUMMARY: ok\nOVERALL: ok\n"
        )
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
                side_effect=[
                    # Producer pick (routed default)
                    _mock_recommendation("mimo-via-claude"),
                    # Auditor pick 1
                    _mock_recommendation("deepseek-via-claude"),
                    # Auditor pick 2
                    _mock_recommendation("kimi-via-claude"),
                ],
            ),
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                side_effect=[producer_resp, a1, a2],
            ),
        ):
            result = runner.invoke(cli, [
                "ask", "test question",
                "--audit", "--auditors", "2",
                "--output", str(tmp_path / "quorum-out"),
            ])
        assert result.exit_code == 0
        out = tmp_path / "quorum-out"
        # Three response files: producer + 2 auditors with -1 / -2 suffix
        assert (out / "producer-mimo-via-claude.md").exists()
        assert (out / "audit-1-deepseek-via-claude.md").exists()
        assert (out / "audit-2-kimi-via-claude.md").exists()
        # Summary carries quorum metadata
        summary = json.loads(
            (out / "summary.json").read_text(encoding="utf-8"),
        )
        assert summary["num_auditors_actual"] == 2
        assert summary["verdict"]["verdict"] == "PASS"
        assert "verdicts" in summary  # per-auditor breakdown

    def test_cli_audit_engine_with_auditors_2_conflicts(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, [
            "ask", "test",
            "--audit-engine", "kimi-via-claude",
            "--auditors", "2",
            "--no-save",
        ])
        assert result.exit_code == 2
        combined = (result.output + (result.stderr or "")).lower()
        assert "audit-engine" in combined
        assert "auditors" in combined or "conflict" in combined


    def test_audit_producer_fail_returns_failed_exit(self) -> None:
        """When the producer fails, --audit exits 1 (failed result) and
        no auditor is run."""
        runner = CliRunner()
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
                return_value=_mock_recommendation("mimo-via-claude"),
            ),
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                return_value=_mock_pool_result(success=False),
            ) as mock_dispatch,
        ):
            result = runner.invoke(cli, [
                "ask", "test", "--audit", "--no-save",
            ])
        assert result.exit_code == 1
        # Only the producer was dispatched
        assert mock_dispatch.call_count == 1


# ---------------------------------------------------------------------------
# W14-ASK-RERUN 2026-05-28 (Phase 2.2): --rerun <dir> --escalate {audit|panel}
# ---------------------------------------------------------------------------


def _build_ask_dir(
    tmp_path: Path, question: str, mode: str = "routed",
    engines: list[str] | None = None, dirname: str | None = None,
) -> Path:
    """Build a fake ask-* dir containing question.md + summary.json,
    suitable as input to `harness ask --rerun <dir>`."""
    dirname = dirname or "ask-20260527-test-question"
    d = tmp_path / dirname
    d.mkdir()
    (d / "question.md").write_text(
        f"# Panel question\n\n{question}\n",
        encoding="utf-8",
    )
    eng = engines or ["mimo-via-claude"]
    (d / "summary.json").write_text(json.dumps({
        "question": question,
        "mode": mode,
        "results": [
            {"engine": e, "role": "" if mode != "audit" else
             ("producer" if i == 0 else "audit")}
            for i, e in enumerate(eng)
        ],
        "total_cost_usd": 0.01,
    }), encoding="utf-8")
    return d


class TestAskRerun:
    """`--rerun <dir>` loads question from a prior ask dir + optionally
    upgrades the mode via `--escalate {audit|panel}`."""

    def test_rerun_inherits_question_and_engine(
        self, tmp_path: Path,
    ) -> None:
        runner = CliRunner()
        parent = _build_ask_dir(
            tmp_path, "Why is X true?",
            mode="routed", engines=["mimo-via-claude"],
        )
        with patch(
            "harness.engines.pool_dispatch.dispatch_with_pool",
            return_value=_mock_pool_result(text="answer"),
        ) as mock_dispatch:
            result = runner.invoke(cli, [
                "ask", "--rerun", str(parent), "--no-save",
            ])
        assert result.exit_code == 0
        # Recommender NOT called — parent's engine was inherited
        # (mock_dispatch was called with the inherited engine)
        assert mock_dispatch.call_count == 1
        assert mock_dispatch.call_args_list[0].args[0] == "mimo-via-claude"
        # Question text was read from question.md
        assert "Why is X true?" in mock_dispatch.call_args_list[0].args[1]

    def test_rerun_with_escalate_audit_promotes_routed_to_audit(
        self, tmp_path: Path,
    ) -> None:
        runner = CliRunner()
        parent = _build_ask_dir(
            tmp_path, "Is Y the case?",
            mode="routed", engines=["mimo-via-claude"],
        )
        producer_resp = _mock_pool_result(text="answer")
        auditor_resp = _mock_pool_result(
            text="VERDICT: PASS\nONE-LINE SUMMARY: ok\nOVERALL: fine\n"
        )
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
                return_value=_mock_recommendation("deepseek-via-claude"),
            ) as mock_rec,
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                side_effect=[producer_resp, auditor_resp],
            ) as mock_dispatch,
        ):
            result = runner.invoke(cli, [
                "ask", "--rerun", str(parent),
                "--escalate", "audit",
                "--output", str(tmp_path / "rerun-out"),
            ])
        assert result.exit_code == 0
        # Two dispatches (producer + auditor); recommender consulted
        # for the auditor pick with exclude={producer}
        assert mock_dispatch.call_count == 2
        assert mock_dispatch.call_args_list[0].args[0] == "mimo-via-claude"
        assert mock_dispatch.call_args_list[1].args[0] == "deepseek-via-claude"
        # Recommender called with audit class
        mock_rec.assert_called_once()
        assert mock_rec.call_args.args[0] == "audit"
        # Output dir has parent_id surfacing the parent ask
        out = tmp_path / "rerun-out"
        summary = json.loads(
            (out / "summary.json").read_text(encoding="utf-8"),
        )
        assert summary["parent_id"] == parent.name
        assert summary["mode"] == "audit"
        assert summary["escalated_from"] == "routed"
        assert summary["escalated_to"] == "audit"

    def test_rerun_with_escalate_panel_promotes_to_3_engines(
        self, tmp_path: Path,
    ) -> None:
        runner = CliRunner()
        parent = _build_ask_dir(
            tmp_path, "Should we ship X?",
            mode="routed", engines=["mimo-via-claude"],
        )
        with patch(
            "harness.engines.pool_dispatch.dispatch_with_pool",
            return_value=_mock_pool_result(text="resp"),
        ) as mock_dispatch:
            result = runner.invoke(cli, [
                "ask", "--rerun", str(parent),
                "--escalate", "panel",
                "--output", str(tmp_path / "panel-rerun"),
            ])
        assert result.exit_code == 0
        # 3 dispatches across the default panel engines
        assert mock_dispatch.call_count == 3
        engines_called = {
            c.args[0] for c in mock_dispatch.call_args_list
        }
        assert engines_called == set(DEFAULT_ENGINES)
        # Parent traceability + escalation metadata in summary.json
        out = tmp_path / "panel-rerun"
        summary = json.loads(
            (out / "summary.json").read_text(encoding="utf-8"),
        )
        assert summary["parent_id"] == parent.name
        assert summary["mode"] == "panel"
        assert summary["escalated_to"] == "panel"

    def test_rerun_no_escalate_inherits_panel_mode(
        self, tmp_path: Path,
    ) -> None:
        """Parent was --panel; rerun without --escalate stays panel."""
        runner = CliRunner()
        parent = _build_ask_dir(
            tmp_path, "Original panel question",
            mode="panel",
            engines=list(DEFAULT_ENGINES),
        )
        with patch(
            "harness.engines.pool_dispatch.dispatch_with_pool",
            return_value=_mock_pool_result(text="resp"),
        ) as mock_dispatch:
            result = runner.invoke(cli, [
                "ask", "--rerun", str(parent), "--no-save",
            ])
        assert result.exit_code == 0
        assert mock_dispatch.call_count == 3

    def test_rerun_conflicts_with_positional_question(
        self, tmp_path: Path,
    ) -> None:
        runner = CliRunner()
        parent = _build_ask_dir(tmp_path, "Original q")
        result = runner.invoke(cli, [
            "ask", "New q", "--rerun", str(parent), "--no-save",
        ])
        assert result.exit_code == 2
        combined = (result.output + (result.stderr or "")).lower()
        assert "incompat" in combined or "conflict" in combined

    def test_rerun_missing_question_md_errors(
        self, tmp_path: Path,
    ) -> None:
        runner = CliRunner()
        broken = tmp_path / "ask-broken"
        broken.mkdir()  # no question.md
        result = runner.invoke(cli, [
            "ask", "--rerun", str(broken), "--no-save",
        ])
        assert result.exit_code == 2
        combined = result.output + (result.stderr or "")
        assert "question.md" in combined

    def test_escalate_without_rerun_warns_and_ignores(
        self, tmp_path: Path,
    ) -> None:
        runner = CliRunner()
        with (
            patch(
                "harness.engines.routing_recommend.recommend",
                return_value=_mock_recommendation("mimo-via-claude"),
            ),
            patch(
                "harness.engines.pool_dispatch.dispatch_with_pool",
                return_value=_mock_pool_result(text="answer"),
            ),
        ):
            result = runner.invoke(cli, [
                "ask", "test", "--escalate", "audit", "--no-save",
            ])
        # Warning surfaces but command still succeeds (single routed dispatch)
        assert result.exit_code == 0
        combined = (result.output + (result.stderr or "")).lower()
        assert "escalate" in combined and (
            "ignored" in combined or "no effect" in combined
        )
