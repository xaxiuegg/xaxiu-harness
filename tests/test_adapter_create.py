"""Tests for ADAPTER-CREATE."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness.adapters.scaffold import scaffold_adapter


def test_scaffold_creates_expected_layout(tmp_path: Path) -> None:
    paths = scaffold_adapter("my-project", target_dir=tmp_path)
    pdir = paths["project_dir"]
    assert pdir.exists()
    assert (pdir / "adapters" / "my-project" / "harness-adapter.yaml").exists()
    assert (pdir / "coord" / "STATUS.csv").exists()
    assert (pdir / "spec" / ".gitkeep").exists()
    assert (pdir / "runs" / ".gitkeep").exists()


def test_scaffold_status_csv_has_only_header(tmp_path: Path) -> None:
    scaffold_adapter("p", target_dir=tmp_path)
    text = (tmp_path / "p" / "coord" / "STATUS.csv").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("ID,Category,Title,Status,")


def test_scaffold_refuses_existing_target(tmp_path: Path) -> None:
    (tmp_path / "existing").mkdir()
    with pytest.raises(FileExistsError):
        scaffold_adapter("existing", target_dir=tmp_path)




