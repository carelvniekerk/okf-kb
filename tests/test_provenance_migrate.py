"""Tests for the guards around `kb-provenance migrate --write`.

The acceptance tests pin the happy paths. These pin the refusals: a directory
outside the bundle must fail with a message and write nothing, because git is
the only undo for a command that rewrites frontmatter in place.
"""

# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

from typer.testing import CliRunner

from okf_kb import provenance

runner = CliRunner()


def test_a_wiki_dir_outside_the_bundle_is_refused_and_nothing_is_written(
    tmp_path,
    monkeypatch,
):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "okf.toml").write_text("", encoding="utf-8")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    stray = outside / "a.md"
    stray.write_text("---\ntype: concept\ntitle: A\n---\n\n# A\n", encoding="utf-8")
    before = stray.read_bytes()
    monkeypatch.chdir(bundle)

    result = runner.invoke(
        provenance.app,
        ["migrate", "--write", "--wiki-dir", str(outside)],
    )

    assert result.exit_code != 0
    assert "outside the bundle" in result.output
    assert stray.read_bytes() == before
