"""Tests for ``kb-read``.

The permission grant ``Bash(kb-read *)`` is only safe if ``kb-read`` cannot be
used to read anything but wiki articles, so most of this file tries to escape:
``../`` traversal, absolute paths elsewhere, a symlink inside the wiki that
points out of it, and a non-markdown file inside it.
"""

# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from okf_kb import config, read

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

ARTICLE = """\
---
type: concept
title: Alpha
---

# Alpha

Intro.

## Details

Some detail.

```bash
# not a heading
```

### Deeper

Still details.

## Sources

- [Paper](../raw/paper.md)
"""


def _kb(root: Path, **files: str) -> config.Bundle:
    wiki = root / "wiki"
    wiki.mkdir(parents=True)
    (root / config.CONFIG_FILENAME).write_text("", encoding="utf-8")
    for name, text in files.items():
        (wiki / name).write_text(text, encoding="utf-8")
    return config.Bundle(root.name, config.load_from(root), "flag")


@pytest.fixture
def kb(tmp_path) -> config.Bundle:
    return _kb(tmp_path / "work", **{"a.md": ARTICLE, "notes.txt": "plain\n"})


# -- path resolution -------------------------------------------------------------


def test_wiki_and_root_relative_paths_resolve(kb):
    wiki = kb.config.wiki.resolve()
    assert read.resolve_readable("a.md", [kb]) == (kb, wiki / "a.md")
    assert read.resolve_readable("wiki/a.md", [kb]) == (kb, wiki / "a.md")
    assert read.resolve_readable(str(wiki / "a.md"), [kb]) == (kb, wiki / "a.md")


def test_parent_traversal_is_refused(kb, tmp_path):
    (tmp_path / "secret.md").write_text("secret\n", encoding="utf-8")
    with pytest.raises(read.ReadError, match="not a file inside any wiki"):
        read.resolve_readable("../../secret.md", [kb])


def test_absolute_path_outside_the_wiki_is_refused(kb):
    raw = kb.config.root / "raw.md"
    raw.write_text("raw\n", encoding="utf-8")
    with pytest.raises(read.ReadError):
        read.resolve_readable(str(raw), [kb])
    with pytest.raises(read.ReadError):
        read.resolve_readable("raw.md", [kb])


def test_symlink_out_of_the_wiki_is_refused(kb, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("outside\n", encoding="utf-8")
    (kb.config.wiki / "link.md").symlink_to(outside)
    with pytest.raises(read.ReadError):
        read.resolve_readable("link.md", [kb])


def test_non_markdown_inside_the_wiki_is_refused(kb):
    with pytest.raises(read.ReadError, match="not a markdown file"):
        read.resolve_readable("notes.txt", [kb])


def test_a_path_in_two_bundles_is_ambiguous(kb, tmp_path):
    other = _kb(tmp_path / "other", **{"a.md": "# Other\n"})
    with pytest.raises(read.ReadError, match=r"more than one bundle \(work, other\)"):
        read.resolve_readable("a.md", [kb, other])
    assert read.resolve_readable("a.md", [other])[0] is other


# -- sections --------------------------------------------------------------------


def test_section_runs_to_the_next_heading_of_equal_level():
    text = read.section(ARTICLE, "## Details")
    assert text.startswith("## Details\n")
    assert "### Deeper" in text
    assert "# not a heading" in text
    assert "## Sources" not in text


def test_section_without_hashes_matches_any_level():
    assert read.section(ARTICLE, "Deeper").startswith("### Deeper\n")


def test_last_section_runs_to_the_end():
    assert read.section(ARTICLE, "## Sources").rstrip().endswith("(../raw/paper.md)")


def test_missing_section_lists_the_headings():
    with pytest.raises(read.ReadError) as info:
        read.section(ARTICLE, "## Nope")
    assert "## Details" in str(info.value)
    assert "not a heading" not in str(info.value)


# -- CLI -------------------------------------------------------------------------


@pytest.fixture
def standing_outside(tmp_path, monkeypatch, kb) -> config.Bundle:
    project = tmp_path / "project"
    project.mkdir()
    (project / config.PROJECT_FILENAME).write_text(
        f'[paths]\nwork = "{kb.config.root}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv(config.ENV_ROOT, raising=False)
    monkeypatch.chdir(project)
    return kb


@pytest.mark.usefixtures("standing_outside")
def test_cli_prints_a_header_then_the_article():
    result = runner.invoke(read.app, ["a.md"])
    assert result.exit_code == 0, result.output
    first, *rest = result.output.splitlines()
    assert first == "==> work: a.md <=="
    assert rest[0] == "---"


@pytest.mark.usefixtures("standing_outside")
def test_cli_strip_frontmatter_and_section():
    result = runner.invoke(
        read.app,
        ["a.md", "--strip-frontmatter", "--section", "## Sources"],
    )
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[1:] == [
        "## Sources",
        "",
        "- [Paper](../raw/paper.md)",
    ]


@pytest.mark.usefixtures("standing_outside")
def test_cli_refusal_exits_non_zero():
    result = runner.invoke(read.app, ["../../../etc/hosts"])
    assert result.exit_code == 1
    assert "not a file inside any wiki" in result.output
