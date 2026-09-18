"""Tests for the shared markdown link scanner.

These cases moved here with the code: they pin down the parsing rules that
``kb-health`` and ``kb-stats`` both depend on and that their three separate
regexes used to repeat. The one distinction worth protecting is that
``targets`` keeps non-markdown targets and ``internal_targets`` drops them,
because the broken-link check needs the first and link density the second.
"""

# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

from okf_kb import links


def test_http_targets_are_skipped():
    text = "[a](https://example.com/a.md) [b](http://example.com) [c](./c.md)"
    assert links.targets(text) == ["./c.md"]


def test_non_markdown_targets_are_kept_by_targets_only():
    text = "![img](../raw/images/a/fig.png) [pdf](./paper.pdf) [md](./b.md)"
    assert links.targets(text) == ["../raw/images/a/fig.png", "./paper.pdf", "./b.md"]
    assert links.internal_targets(text) == ["./b.md"]


def test_duplicates_are_kept_in_document_order():
    text = "[b](./b.md) [a](./a.md) [b again](./b.md)"
    assert links.internal_targets(text) == ["./b.md", "./a.md", "./b.md"]


def test_whitespace_terminates_the_target():
    # A title after the target is not part of it.
    assert links.targets('[x](./a.md "A title")') == []
    assert links.targets("[x](./a.md)") == ["./a.md"]


def test_resolve_decodes_percent_encoding(tmp_path):
    source = tmp_path / "wiki" / "a.md"
    resolved = links.resolve("./with%20space.md", source)
    assert resolved == (tmp_path / "wiki" / "with space.md").resolve()


def test_resolve_is_relative_to_the_source_directory(tmp_path):
    source = tmp_path / "wiki" / "sub" / "a.md"
    assert links.resolve("../b.md", source) == (tmp_path / "wiki" / "b.md").resolve()


def test_outgoing_resolves_and_keeps_the_raw_target(tmp_path):
    wiki = tmp_path / "wiki"
    (wiki / "sub").mkdir(parents=True)
    source = wiki / "sub" / "a.md"
    source.write_text(
        "[b](../b.md) [img](./fig.png) [ext](https://x.org/c.md)\n",
        encoding="utf-8",
    )

    found = links.outgoing(source)

    assert len(found) == 1
    assert found[0].raw == "../b.md"
    assert found[0].target == (wiki / "b.md").resolve()
