"""Acceptance test AC-15: /kb:adopt hands provenance backfill to the command.

The skill is prose, so the contract is its text: it must name the command, and
it must stop telling Claude to recover `generated` from commit trailers by hand.
"""

# ruff: noqa: ANN202, S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

from pathlib import Path

ADOPT = Path(__file__).parents[2] / "plugins" / "kb" / "skills" / "adopt" / "SKILL.md"


def test_ac_15_adopt_uses_the_migrate_write_command():
    text = ADOPT.read_text(encoding="utf-8")

    assert "kb-provenance migrate --write" in text
    assert "author trailer gives the producing model" not in text
