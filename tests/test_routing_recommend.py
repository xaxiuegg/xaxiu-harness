"""W14-CROSS-ENGINE-AUDIT 2026-05-26: tests for the routing recommender."""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.engines.routing_recommend import (
    VALID_TASK_CLASSES,
    Recommendation,
    recommend,
)


class TestRecommendCore:
    def test_valid_task_classes(self) -> None:
        assert VALID_TASK_CLASSES == frozenset({
            "default", "latency", "verbose", "cost", "high-volume",
            "multimodal", "audit",
        })

    def test_default_class(self) -> None:
        rec = recommend("default")
        assert rec.engine == "mimo-via-claude"
        assert "deepseek-via-claude" in rec.alternates
        assert "kimi-via-claude" in rec.alternates
        assert rec.model_override is None

    def test_latency_class(self) -> None:
        # W14-MIMO-PRODUCTION-VALIDATION 2026-05-26 recalibration:
        # MiMo was 36.8s on realistic prompts (vs smoke's 9.3s on
        # trivial).  DeepSeek-flash won latency on every category.
        rec = recommend("latency")
        assert rec.engine == "deepseek-via-claude"
        assert "mimo-via-claude" in rec.alternates

    def test_verbose_class(self) -> None:
        rec = recommend("verbose")
        assert rec.engine == "kimi-via-claude"  # most tokens out
        assert "deepseek-via-claude" in rec.alternates

    def test_cost_class(self) -> None:
        rec = recommend("cost")
        # W14-MIMO-PRICE-CUT 2026-05-26: MiMo flipped to cheapest after
        # the permanent price cut (-57%/-71%/-98%).
        assert rec.engine == "mimo-via-claude"
        assert "kimi-via-claude" in rec.alternates

    def test_high_volume_class(self) -> None:
        # New class for batch workloads — MiMo Token Plan dominates
        rec = recommend("high-volume")
        assert rec.engine == "mimo-via-claude"

    def test_multimodal_class(self) -> None:
        rec = recommend("multimodal")
        # MiMo or Kimi to avoid DeepSeek's WARNING log on .png mentions
        assert rec.engine in ("mimo-via-claude", "kimi-via-claude")

    def test_audit_class_uses_v4_pro_override(self) -> None:
        rec = recommend("audit")
        # When deepseek is the primary audit engine, override to v4-pro
        if rec.engine == "deepseek-via-claude":
            assert rec.model_override == "deepseek-v4-pro"
        assert "rationale" in str(rec) or rec.rationale

    def test_unknown_class_falls_through_to_default(self) -> None:
        rec = recommend("nonsense-class")
        assert rec.engine == "mimo-via-claude"  # default

    def test_empty_class_falls_through(self) -> None:
        rec = recommend("")
        assert rec.engine == "mimo-via-claude"

    def test_recommendation_has_rationale(self) -> None:
        for tc in VALID_TASK_CLASSES:
            rec = recommend(tc)
            assert rec.rationale
            assert len(rec.rationale) > 20  # non-trivial explanation

    def test_exclude_filters_primary(self) -> None:
        """For audit: caller passes the first-pass engine via exclude=."""
        rec = recommend("audit", exclude={"deepseek-via-claude"})
        assert rec.engine != "deepseek-via-claude"
        # Should pick from alternates
        assert rec.engine in ("kimi-via-claude", "mimo-via-claude")

    def test_exclude_all_raises(self) -> None:
        # If every candidate is excluded, the helper raises rather than
        # returning an arbitrary fallback
        with pytest.raises(ValueError):
            recommend(
                "default",
                exclude={
                    "kimi-via-claude",
                    "mimo-via-claude",
                    "deepseek-via-claude",
                },
            )

    def test_audit_model_override_dropped_when_deepseek_excluded(
        self,
    ) -> None:
        # If DeepSeek is excluded from audit, the v4-pro override
        # shouldn't apply (the alternate isn't DeepSeek)
        rec = recommend("audit", exclude={"deepseek-via-claude"})
        assert rec.model_override is None


class TestRecommendCli:
    def test_help_mentions_recommend(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["engines", "--help"])
        assert result.exit_code == 0
        assert "recommend" in result.output.lower()

    def test_recommend_default_prints_engine_name(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["engines", "recommend", "default"])
        assert result.exit_code == 0
        # The engine name is on stdout, alone on first non-empty line
        lines = [
            line for line in result.output.strip().split("\n") if line
        ]
        # First line should be the engine name (or only line if no
        # stderr captured into output)
        assert any(
            "mimo-via-claude" in line for line in lines
        ), result.output

    def test_recommend_latency(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["engines", "recommend", "latency"])
        assert result.exit_code == 0
        assert "mimo-via-claude" in result.output

    def test_recommend_verbose(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["engines", "recommend", "verbose"])
        assert result.exit_code == 0
        assert "kimi-via-claude" in result.output

    def test_recommend_missing_class_exits_nonzero(self) -> None:
        runner = CliRunner()
        # Just "recommend" with no class
        result = runner.invoke(cli, ["engines", "recommend"])
        assert result.exit_code != 0
