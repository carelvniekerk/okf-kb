"""Tests for the shared frontmatter parser.

This module replaced roughly a dozen hand-rolled regexes across four tools, so
the cases below deliberately cover the shapes those regexes got wrong: nested
mappings, block-style lists, quoted paths containing spaces, and identifiers
that YAML would otherwise coerce to numbers.
"""

# ruff: noqa: S101, D101, D102, D103, ANN001

from __future__ import annotations

import datetime as dt

import pytest

from okf_kb import frontmatter as fm

SIMPLE = """\
---
type: paper-summary
tags: [flash-attention, cuda]
date_added: 2026-04-04
---

# FlashAttention-2

Body text.
"""


def test_parse_returns_mapping_and_body() -> None:
    data, body = fm.parse(SIMPLE)
    assert data["type"] == "paper-summary"
    assert body.startswith("\n# FlashAttention-2")


def test_parse_preserves_key_order() -> None:
    data, _ = fm.parse(SIMPLE)
    assert list(data) == ["type", "tags", "date_added"]


def test_bare_dates_parse_as_date_objects() -> None:
    data, _ = fm.parse(SIMPLE)
    assert data["date_added"] == dt.date(2026, 4, 4)


def test_no_frontmatter_returns_empty_mapping() -> None:
    data, body = fm.parse("# Just a heading\n")
    assert data == {}
    assert body == "# Just a heading\n"


def test_horizontal_rule_is_not_frontmatter() -> None:
    """A leading `---` followed by prose must not be read as frontmatter."""
    text = "---\nnot: yaml: at: all\n"
    with pytest.raises(fm.FrontmatterError):
        fm.parse(text)


def test_unterminated_block_raises() -> None:
    with pytest.raises(fm.FrontmatterError, match="unterminated"):
        fm.parse("---\ntype: concept\n\nbody with no closing delimiter\n")


def test_non_mapping_frontmatter_raises() -> None:
    with pytest.raises(fm.FrontmatterError, match="must be a mapping"):
        fm.parse("---\n- just\n- a\n- list\n---\nbody\n")


def test_empty_frontmatter_block_is_empty_mapping() -> None:
    data, body = fm.parse("---\n---\nbody\n")
    assert data == {}
    assert body == "body\n"


NESTED = """\
---
type: paper-summary
generated:
  by: claude-opus-4-6
  at: 2026-04-07T14:22:31Z
  skill: compile@c8c310f
sources:
  - id: fa2-paper
    resource: raw/papers/2307.08691.md
    author: human:carel
  - id: fa2-notes
    resource: "raw/notes/FlashAttention-2 Faster Attention with Better Para 5ad4033d.md"
    author: human:carel
---
body
"""


def test_nested_mapping_parses() -> None:
    """The old regex parsers could not represent this shape at all."""
    data, _ = fm.parse(NESTED)
    assert data["generated"]["by"] == "claude-opus-4-6"
    assert data["generated"]["skill"] == "compile@c8c310f"


def test_list_of_mappings_parses() -> None:
    data, _ = fm.parse(NESTED)
    assert [s["id"] for s in data["sources"]] == ["fa2-paper", "fa2-notes"]


def test_quoted_path_with_spaces_survives() -> None:
    data, _ = fm.parse(NESTED)
    assert " " in data["sources"][1]["resource"]
    assert data["sources"][1]["resource"].endswith("5ad4033d.md")


class TestRoundTrip:
    """Serialising and re-parsing must not change the data."""

    def test_simple_document(self) -> None:
        data, body = fm.parse(SIMPLE)
        redata, rebody = fm.parse(fm.dumps(data, body))
        assert redata == data
        assert rebody == body

    def test_nested_document(self) -> None:
        data, body = fm.parse(NESTED)
        redata, rebody = fm.parse(fm.dumps(data, body))
        assert redata == data
        assert rebody == body

    def test_key_order_survives(self) -> None:
        data, body = fm.parse(NESTED)
        redata, _ = fm.parse(fm.dumps(data, body))
        assert list(redata) == list(data)


def test_tags_serialise_inline() -> None:
    """`tags` keeps the flow style the existing articles use."""
    out = fm.dumps({"tags": ["a", "b"]}, "body\n")
    assert "tags: [a, b]" in out


def test_sources_serialise_as_block() -> None:
    out = fm.dumps({"sources": [{"id": "x", "resource": "raw/x.md"}]}, "body\n")
    assert "sources:\n  - id: x" in out


def test_arxiv_id_stays_quoted_string() -> None:
    """Unquoted, `2104.09864` would round-trip as a float and lose its identity."""
    out = fm.dumps({"arxiv": "2104.09864"}, "body\n")
    assert 'arxiv: "2104.09864"' in out
    reparsed, _ = fm.parse(out)
    assert reparsed["arxiv"] == "2104.09864"


def test_unicode_is_not_escaped() -> None:
    out = fm.dumps({"title": "Tülu 3 — post-training"}, "body\n")
    assert "Tülu 3 — post-training" in out


def test_long_description_is_not_wrapped() -> None:
    """Wrapped lines would make frontmatter diffs unreadable."""
    description = "A single sentence that runs well past eighty characters " * 3
    out = fm.dumps({"description": description.strip()}, "body\n")
    description_lines = [ln for ln in out.splitlines() if ln.startswith("description:")]
    assert len(description_lines) == 1


def test_empty_frontmatter_emits_no_block() -> None:
    assert fm.dumps({}, "# Index\n") == "# Index\n"


class TestSourceResources:
    """`source_resources` must bridge the legacy and OKF shapes during migration."""

    def test_reads_okf_sources(self) -> None:
        data = {"sources": [{"resource": "raw/a.md"}, {"resource": "raw/b.md"}]}
        assert fm.source_resources(data) == ["raw/a.md", "raw/b.md"]

    def test_falls_back_to_legacy_source_files(self) -> None:
        data = {"source_files": ["raw/a.md", "raw/b.md"]}
        assert fm.source_resources(data) == ["raw/a.md", "raw/b.md"]

    def test_okf_sources_win_over_legacy(self) -> None:
        data = {"sources": [{"resource": "raw/new.md"}], "source_files": ["raw/old.md"]}
        assert fm.source_resources(data) == ["raw/new.md"]

    def test_integer_sources_does_not_crash(self) -> None:
        """Pre-migration articles carry `sources: 2`, an int, not a list."""
        assert fm.source_resources({"sources": 2, "source_files": ["raw/a.md"]}) == [
            "raw/a.md",
        ]

    def test_entry_without_resource_is_skipped(self) -> None:
        assert fm.source_resources({"sources": [{"id": "orphan"}]}) == []

    def test_missing_keys_yield_empty(self) -> None:
        assert fm.source_resources({}) == []


class TestAsDate:
    def test_bare_date(self) -> None:
        assert fm.as_date(dt.date(2026, 4, 4)) == dt.date(2026, 4, 4)

    def test_quoted_date_string(self) -> None:
        assert fm.as_date("2026-04-04") == dt.date(2026, 4, 4)

    def test_datetime_narrows_to_date(self) -> None:
        assert fm.as_date(dt.datetime(2026, 4, 4, 12, 30, tzinfo=dt.UTC)) == dt.date(
            2026,
            4,
            4,
        )

    def test_garbage_returns_none(self) -> None:
        assert fm.as_date("not a date") is None

    def test_none_returns_none(self) -> None:
        assert fm.as_date(None) is None


def test_load_and_save_round_trip(tmp_path) -> None:
    path = tmp_path / "article.md"
    path.write_text(NESTED, encoding="utf-8")

    doc = fm.load(path)
    assert doc.path == path
    assert doc.has_frontmatter

    doc.frontmatter["status"] = "stable"
    fm.save(doc)

    reloaded = fm.load(path)
    assert reloaded.frontmatter["status"] == "stable"
    assert reloaded.frontmatter["generated"]["by"] == "claude-opus-4-6"


def test_load_error_names_the_file(tmp_path) -> None:
    path = tmp_path / "broken.md"
    path.write_text("---\ntype: [unclosed\n---\nbody\n", encoding="utf-8")
    with pytest.raises(fm.FrontmatterError, match=r"broken\.md"):
        fm.load(path)


def test_save_without_path_raises() -> None:
    with pytest.raises(ValueError, match="no path"):
        fm.save(fm.Document(frontmatter={"type": "concept"}, body="x"))
