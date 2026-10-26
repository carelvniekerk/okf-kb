"""Acceptance tests AC-5 and AC-6: `kb-export consolidate` follows the bundle's config.

A bundle that renames its zones must export without a path argument, and a
directory outside any bundle must fail with the configuration error rather than
a stray usage message about a missing `wiki` directory.
"""

# ruff: noqa: ANN202, S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

from typer.testing import CliRunner

from okf_kb import config, export

runner = CliRunner()


def test_ac_5_consolidate_reads_the_configured_wiki_zone(tmp_path, monkeypatch):
    (tmp_path / "okf.toml").write_text('[paths]\nwiki = "articles"\n', encoding="utf-8")
    articles = tmp_path / "articles"
    (articles / "concepts").mkdir(parents=True)
    (articles / "INDEX.md").write_text("# Index heading\n", encoding="utf-8")
    (articles / "concepts" / "a.md").write_text("# Article heading\n", encoding="utf-8")
    decoy = tmp_path / "wiki"
    decoy.mkdir()
    (decoy / "INDEX.md").write_text("# DECOY index\n", encoding="utf-8")
    (decoy / "z.md").write_text("# DECOY article\n", encoding="utf-8")
    out = tmp_path / "all.md"
    monkeypatch.chdir(articles / "concepts")

    result = runner.invoke(export.app, ["consolidate", "--output", str(out)])

    assert result.exit_code == 0, result.output
    text = out.read_text(encoding="utf-8")
    assert text.index("# Index heading") < text.index("# Article heading")
    assert "<!-- source: concepts/a.md -->" in text
    assert "DECOY" not in text


def test_ac_6_consolidate_outside_a_bundle_raises_the_config_error(
    tmp_path,
    monkeypatch,
):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(export.app, ["consolidate"])

    assert result.exit_code != 0
    assert isinstance(result.exception, config.ConfigError)
