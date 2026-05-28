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
