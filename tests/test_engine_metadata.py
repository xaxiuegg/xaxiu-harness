"""W14-ENGINE-METADATA 2026-05-28: tests for the engine metadata
registry + CLI surfaces (describe / compatibility-matrix)."""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from harness.cli import cli
from harness.engines.metadata import (
    EngineMetadata,
    compatibility_matrix,
    describe,
    list_engine_metadata,
)


# ---------------------------------------------------------------------------
# Registry lookups
# ---------------------------------------------------------------------------


class TestDescribe:
    def test_known_engine_returns_metadata(self) -> None:
        md = describe("mimo-via-claude")
        assert isinstance(md, EngineMetadata)
        assert md.name == "mimo-via-claude"
        assert md.vendor == "xiaomi"

    def test_unknown_engine_raises_value_error(self) -> None:
        with pytest.raises(ValueError) as ctx:
            describe("totally-made-up-engine")
        msg = str(ctx.value)
        assert "totally-made-up-engine" in msg
        # Error message lists known engines so the operator can recover
        assert "mimo-via-claude" in msg

    def test_case_insensitive(self) -> None:
        assert describe("MIMO-VIA-CLAUDE").name == "mimo-via-claude"
        assert describe("DeepSeek-Via-Claude").name == "deepseek-via-claude"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            describe("")


class TestRegistry:
    def test_list_returns_all_known(self) -> None:
        names = set(list_engine_metadata())
        # Snapshot v0.5.2 set — any removal breaks discoverability
        assert {
            "mimo-via-claude",
            "deepseek-via-claude",
            "kimi-via-claude",
            "qwen-via-claude",
            "anthropic",
            "gemini",
        }.issubset(names)

    def test_list_returns_snapshot_not_internal_state(self) -> None:
        listing = list_engine_metadata()
        listing["fake"] = None  # type: ignore[assignment]
        assert "fake" not in list_engine_metadata()


# ---------------------------------------------------------------------------
# Closure of transcript hiccups — specific metadata that would have
# resolved the 2026-05-27 Desktop session's confusion in 1 call.
# ---------------------------------------------------------------------------


class TestTranscriptHiccupClosures:
    """Each test here corresponds to a specific friction point in the
    2026-05-27 transcript that this metadata makes 1-call discoverable."""

    def test_mimo_has_both_protocol_surfaces(self) -> None:
        """THE BIG ONE (transcript lines 945-1066): agent claimed
        'MiMo speaks Anthropic only' based on partial source.  Real
        MiMo has both /v1 (OpenAI) AND /anthropic surfaces."""
        md = describe("mimo-via-claude")
        assert "openai" in md.protocol_surfaces
        assert "anthropic" in md.protocol_surfaces
        # Notes field must surface this explicitly so the metadata
        # output makes the dual-surface fact unmissable
        assert "TWO" in md.notes or "both" in md.notes.lower()

    def test_mimo_ua_gating_documented(self) -> None:
        """Hiccup #10 (transcript lines 1170-1200): agent had to
        re-read concrete.py to learn Token Plan keys are UA-gated.
        The metadata surface must say so directly."""
        md = describe("mimo-via-claude")
        assert md.ua_gating
        # The gating note must mention BOTH the gated case (tp-) and
        # the bypass (sk-/mp- PAYG) so the operator knows what to do
        assert "tp-" in md.ua_gating or "Token Plan" in md.ua_gating
        assert "PAYG" in md.ua_gating or "sk-" in md.ua_gating

    def test_kimi_ua_gating_documented(self) -> None:
        """Kimi Code subscription has the same UA-gating pattern."""
        md = describe("kimi-via-claude")
        assert md.ua_gating
        assert "kimi" in md.ua_gating.lower() or "subscription" in md.ua_gating.lower()

    def test_each_engine_advertises_consumption_surfaces(self) -> None:
        """Hiccup #9 (transcript lines 1024-1140): the 4-option
        architecture comparison took 9 tool calls.  Every engine
        must enumerate its consumption surfaces so an agent can do
        the comparison in 1 call."""
        all_md = list_engine_metadata()
        for name, md in all_md.items():
            assert md.consumption_surfaces, (
                f"{name}: must enumerate consumption_surfaces"
            )
            expected_surfaces = {
                "http_direct", "proxy_upstream", "pattern_b", "swarm",
            }
            assert expected_surfaces.issubset(
                md.consumption_surfaces.keys()
            ), (
                f"{name}: missing surfaces "
                f"{expected_surfaces - set(md.consumption_surfaces.keys())}"
            )


# ---------------------------------------------------------------------------
# Compatibility matrix
# ---------------------------------------------------------------------------


class TestCompatibilityMatrix:
    def test_returns_one_row_per_engine(self) -> None:
        matrix = compatibility_matrix()
        names = {r["engine"] for r in matrix}
        assert names == set(list_engine_metadata())

    def test_each_row_has_required_columns(self) -> None:
        matrix = compatibility_matrix()
        required = {
            "engine", "vendor", "protocols", "ua_gated",
            "http_direct", "proxy_upstream", "pattern_b", "swarm",
        }
        for row in matrix:
            assert required.issubset(row.keys()), (
                f"missing columns in row {row['engine']}: "
                f"{required - set(row.keys())}"
            )

    def test_ua_gated_flag_set_for_mimo_and_kimi(self) -> None:
        matrix = {r["engine"]: r for r in compatibility_matrix()}
        assert matrix["mimo-via-claude"]["ua_gated"] is True
        assert matrix["kimi-via-claude"]["ua_gated"] is True
        # DeepSeek has no UA gating
        assert matrix["deepseek-via-claude"]["ua_gated"] is False

    def test_sorted_by_engine_name(self) -> None:
        matrix = compatibility_matrix()
        names = [r["engine"] for r in matrix]
        assert names == sorted(names), "matrix must be deterministically ordered"


# ---------------------------------------------------------------------------
# CLI: harness engines describe
# ---------------------------------------------------------------------------


class TestDescribeCli:
    def test_describe_known_engine(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, [
            "engines", "describe", "mimo-via-claude",
        ])
        assert result.exit_code == 0
        # Key fields visible in output
        assert "mimo-via-claude" in result.output
        assert "xiaomi" in result.output
        assert "openai" in result.output
        assert "anthropic" in result.output
        # UA gating note must appear so the operator sees the warning
        assert "UA" in result.output or "ua" in result.output.lower()

    def test_describe_json_format(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, [
            "engines", "describe", "deepseek-via-claude", "json",
        ])
        assert result.exit_code == 0
        # Output should be valid JSON
        parsed = json.loads(result.output)
        assert parsed["name"] == "deepseek-via-claude"
        assert parsed["vendor"] == "deepseek"
        # Lists serialize as JSON arrays
        assert isinstance(parsed["protocol_surfaces"], list)
        assert "openai" in parsed["protocol_surfaces"]

    def test_describe_unknown_engine_returns_error(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, [
            "engines", "describe", "fake-engine-name",
        ])
        assert result.exit_code == 2
        combined = result.output + (result.stderr or "")
        assert "fake-engine-name" in combined
        # Error must list valid names
        assert "mimo-via-claude" in combined

    def test_describe_missing_name_returns_error(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, ["engines", "describe"])
        assert result.exit_code == 2
        combined = result.output + (result.stderr or "")
        assert "engine" in combined.lower()

    def test_describe_mimo_surfaces_dual_protocol(self) -> None:
        """End-to-end: the CLI output must make MiMo's dual-protocol
        fact visible to a human reader — closing the canonical hiccup."""
        runner = CliRunner()
        result = runner.invoke(cli, [
            "engines", "describe", "mimo-via-claude",
        ])
        assert result.exit_code == 0
        # Both protocols listed in the same output
        assert "openai" in result.output.lower()
        assert "anthropic" in result.output.lower()
        # The "Notes" section must mention both surfaces (the closure)
        assert "TWO" in result.output or "both" in result.output.lower()


# ---------------------------------------------------------------------------
# CLI: harness engines compatibility-matrix
# ---------------------------------------------------------------------------


class TestCompatibilityMatrixCli:
    def test_text_output(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, [
            "engines", "compatibility-matrix",
        ])
        assert result.exit_code == 0
        # All known engines should be listed
        for name in list_engine_metadata():
            assert name in result.output
        # Surface columns present
        assert "http_direct" in result.output
        assert "proxy_upstream" in result.output
        assert "pattern_b" in result.output
        assert "swarm" in result.output
        # UA-gating badges shown for gated engines
        assert "UA-gated" in result.output

    def test_json_output(self) -> None:
        runner = CliRunner()
        result = runner.invoke(cli, [
            "engines", "compatibility-matrix", "--json",
        ])
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert isinstance(parsed, list)
        assert all("engine" in r for r in parsed)
        # Same engine set as the registry
        names = {r["engine"] for r in parsed}
        assert names == set(list_engine_metadata())
