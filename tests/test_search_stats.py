"""Tests for the search, stats, and ingest tools.

These cover the bugs the hand-rolled regexes and path arithmetic hid: block
style YAML tag lists that the old `tags:` regex could not see, the two shapes
the `sources` key now takes, deprecation filtering, broken-link detection that
never touched the filesystem, article counts inflated by `INDEX.md` and
`log.md`, and image references rewritten with `Path.relative_to`.
"""

# Test-suite conventions: bare asserts, undocumented helpers, magic numbers.
# RUF100 is included because several of the codes below are not currently
# enabled in the global ruff config and would otherwise be flagged as unused.
# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from okf_kb import ingest, okf, provenance, search, stats

# --------------------------------------------------------------------------
# search.py — frontmatter parsing
# --------------------------------------------------------------------------

BLOCK_TAGS = """\
---
type: concept
tags:
  - flash-attention
  - cuda
  - tiling
date_added: 2026-04-04
sources: 2
---

# Block Tags

Body text about tiling.
"""

INLINE_TAGS = """\
---
type: paper-summary
tags: [rope, position-encoding]
date_added: 2026-04-05
sources: 1
---

# Inline Tags

Body text.
"""


def test_block_style_tags_are_parsed():
    """The old `_TAG_LINE_RE` only matched inline flow lists and missed these."""
    meta = search.parse_frontmatter(BLOCK_TAGS)
    assert meta["tags"] == ["flash-attention", "cuda", "tiling"]


def test_inline_style_tags_still_parsed():
    meta = search.parse_frontmatter(INLINE_TAGS)
    assert meta["tags"] == ["rope", "position-encoding"]


def _write_article(wiki: Path, name: str, frontmatter: str, term: str) -> None:
    """Write an article whose body carries one term unique to it.

    BM25 gives a non-positive score to a term occurring in most of the corpus,
    and `search` stops at the first non-positive score, so test corpora need
    several documents with distinctive vocabulary.
    """
    wiki.mkdir(parents=True, exist_ok=True)
    (wiki / name).write_text(
        f"---\n{frontmatter}\n---\n\n# {name}\n\nDiscussion of {term}.\n",
        encoding="utf-8",
    )


#: Query hitting one distinctive term per article in the small test corpora.
CORPUS_QUERY = "alpha beta gamma"

#: Block-style tag list — the shape the old `tags:` regex could not see.
BLOCK_CUDA_TAGS = "type: concept\ntags:\n  - flash-attention\n  - cuda"


def test_block_style_tags_are_filterable(tmp_path):
    wiki = tmp_path / "wiki"
    _write_article(wiki, "block-a.md", BLOCK_CUDA_TAGS, "alpha")
    _write_article(wiki, "block-b.md", BLOCK_CUDA_TAGS, "beta")
    _write_article(wiki, "block-c.md", BLOCK_CUDA_TAGS, "gamma")
    _write_article(wiki, "other-a.md", "type: concept\ntags: [rope]", "delta")
    _write_article(wiki, "other-b.md", "type: concept\ntags: [rope]", "epsilon")

    results = search.search(CORPUS_QUERY, wiki, top_k=10, filter_tag="cuda")
    assert {Path(r["path"]).name for r in results} == {
        "block-a.md",
        "block-b.md",
        "block-c.md",
    }


def test_missing_frontmatter_yields_empty_metadata():
    meta = search.parse_frontmatter("# No frontmatter\n\nJust a body.\n")
    assert meta == {
        "tags": [],
        "type": None,
        "date_added": None,
        "sources": 0,
        "status": "stable",
    }


def test_malformed_frontmatter_does_not_raise():
    meta = search.parse_frontmatter("---\ntags: [unterminated\n---\n\nBody.\n")
    assert meta["tags"] == []


def test_strip_frontmatter_removes_only_the_block():
    body = search.strip_frontmatter(INLINE_TAGS)
    assert body.lstrip().startswith("# Inline Tags")
    assert "date_added" not in body


# --------------------------------------------------------------------------
# search.py — source counting across the legacy and OKF shapes
# --------------------------------------------------------------------------


def test_source_count_legacy_int():
    assert search.source_count({"sources": 3}) == 3


def test_source_count_okf_list():
    frontmatter = {
        "sources": [
            {"resource": "raw/papers/2307.08691.md"},
            {"resource": "raw/notes/flash.md"},
        ],
    }
    assert search.source_count(frontmatter) == 2


def test_source_count_absent_is_zero():
    assert search.source_count({}) == 0


def test_source_count_unrecognised_type_is_zero():
    assert search.source_count({"sources": "many"}) == 0


def test_parse_frontmatter_exposes_okf_source_count():
    text = """\
---
type: concept
sources:
  - resource: raw/a.md
  - resource: raw/b.md
  - resource: raw/c.md
---

Body.
"""
    assert search.parse_frontmatter(text)["sources"] == 3


# --------------------------------------------------------------------------
# search.py — deprecation filtering
# --------------------------------------------------------------------------


def _write_status_wiki(wiki: Path) -> None:
    _write_article(wiki, "stable.md", "type: concept", "alpha")
    _write_article(wiki, "old.md", "type: concept\nstatus: deprecated", "beta")
    _write_article(wiki, "explicit.md", "type: concept\nstatus: stable", "gamma")
    # Filler keeps the corpus large enough for BM25 to score the query terms
    # above zero once the deprecated article is filtered out.
    _write_article(wiki, "filler-a.md", "type: concept", "delta")
    _write_article(wiki, "filler-b.md", "type: concept", "epsilon")
    _write_article(wiki, "filler-c.md", "type: concept", "zeta")


def test_deprecated_articles_excluded_by_default(tmp_path):
    wiki = tmp_path / "wiki"
    _write_status_wiki(wiki)

    names = {Path(r["path"]).name for r in search.search(CORPUS_QUERY, wiki, top_k=10)}
    assert names == {"stable.md", "explicit.md"}


def test_deprecated_articles_returned_when_requested(tmp_path):
    wiki = tmp_path / "wiki"
    _write_status_wiki(wiki)

    names = {
        Path(r["path"]).name
        for r in search.search(CORPUS_QUERY, wiki, top_k=10, include_deprecated=True)
    }
    assert names == {"stable.md", "explicit.md", "old.md"}


def test_absent_status_defaults_to_stable(tmp_path):
    wiki = tmp_path / "wiki"
    _write_status_wiki(wiki)

    statuses = {
        Path(r["path"]).name: r["status"]
        for r in search.search(CORPUS_QUERY, wiki, top_k=10)
    }
    assert statuses["stable.md"] == "stable"


def test_index_and_log_are_not_articles(tmp_path):
    assert not search.is_article(tmp_path / "INDEX.md")
    assert not search.is_article(tmp_path / "log.md")
    assert not search.is_article(tmp_path / "_partial.md")
    assert search.is_article(tmp_path / "article.md")


# --------------------------------------------------------------------------
# stats.py
# --------------------------------------------------------------------------


def _build_wiki(tmp_path: Path) -> Path:
    """Build a wiki with a link out to raw/, plus INDEX.md and log.md."""
    raw = tmp_path / "raw" / "papers"
    raw.mkdir(parents=True)
    (raw / "2307.08691.md").write_text("# Paper\n", encoding="utf-8")

    wiki = tmp_path / "wiki"
    (wiki / "alignment").mkdir(parents=True)
    (wiki / "alignment" / "rlhf.md").write_text(
        "# RLHF\n\n"
        "See [attention](../attention.md).\n\n"
        "## Sources\n\n"
        "- [Paper](../../raw/papers/2307.08691.md)\n",
        encoding="utf-8",
    )
    (wiki / "attention.md").write_text(
        "# Attention\n\nSee [RLHF](./alignment/rlhf.md).\n",
        encoding="utf-8",
    )
    (wiki / "INDEX.md").write_text(
        "# Index\n\n- [Attention](./attention.md)\n- [RLHF](./alignment/rlhf.md)\n",
        encoding="utf-8",
    )
    (wiki / "log.md").write_text("# Log\n\nSome words here.\n", encoding="utf-8")
    (wiki / "_partial.md").write_text("# Partial\n", encoding="utf-8")
    return wiki


def test_links_outside_the_wiki_are_not_broken(tmp_path):
    """The old check tested set membership in wiki files, so every raw/ link
    was reported broken even though the file existed on disk.
    """  # noqa: D205
    wiki = _build_wiki(tmp_path)
    result = stats.compute_stats(wiki)
    assert result["broken_links"] == []


def test_genuinely_missing_link_is_reported(tmp_path):
    wiki = _build_wiki(tmp_path)
    (wiki / "attention.md").write_text(
        "# Attention\n\nSee [gone](./does-not-exist.md).\n",
        encoding="utf-8",
    )
    result = stats.compute_stats(wiki)
    assert len(result["broken_links"]) == 1
    assert "does-not-exist.md" in result["broken_links"][0]


def test_percent_encoded_links_resolve(tmp_path):
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "My Note.md").write_text("# My Note\n", encoding="utf-8")
    (wiki / "a.md").write_text(
        "# A\n\nSee [note](./My%20Note.md).\n",
        encoding="utf-8",
    )
    assert stats.compute_stats(wiki)["broken_links"] == []


def test_index_log_and_partials_excluded_from_article_count(tmp_path):
    wiki = _build_wiki(tmp_path)
    result = stats.compute_stats(wiki)

    paths = {article["path"] for article in result["articles"]}
    assert paths == {"attention.md", "alignment/rlhf.md"}
    assert result["article_count"] == 2


def test_excluded_files_do_not_inflate_averages(tmp_path):
    wiki = _build_wiki(tmp_path)
    result = stats.compute_stats(wiki)

    log_words = len((wiki / "log.md").read_text(encoding="utf-8").split())
    article_words = sum(
        len((wiki / p).read_text(encoding="utf-8").split())
        for p in ("attention.md", "alignment/rlhf.md")
    )
    assert result["total_words"] == article_words
    assert log_words not in (0, result["total_words"])
    assert result["avg_words_per_article"] == round(article_words / 2)


def test_index_links_prevent_orphan_reports(tmp_path):
    wiki = _build_wiki(tmp_path)
    assert stats.compute_stats(wiki)["orphan_articles"] == []


def test_unlinked_article_is_an_orphan(tmp_path):
    wiki = _build_wiki(tmp_path)
    (wiki / "lonely.md").write_text("# Lonely\n", encoding="utf-8")
    assert stats.compute_stats(wiki)["orphan_articles"] == ["lonely.md"]


def test_excluded_files_are_never_orphans(tmp_path):
    wiki = _build_wiki(tmp_path)
    orphans = stats.compute_stats(wiki)["orphan_articles"]
    assert "log.md" not in orphans
    assert "INDEX.md" not in orphans
    assert "_partial.md" not in orphans


# --------------------------------------------------------------------------
# ingest.py
# --------------------------------------------------------------------------


def test_download_images_rewrites_across_directories(tmp_path):
    """`Path.relative_to` raised for the layout the /ingest skill prescribes."""
    clippings = tmp_path / "raw" / "clippings"
    clippings.mkdir(parents=True)
    md_file = clippings / "some-article.md"
    md_file.write_text(
        "# Clip\n\n![diagram](https://example.com/diagram.png)\n",
        encoding="utf-8",
    )

    # Pre-create the image so no network request is attempted.
    image_dir = tmp_path / "raw" / "images" / "some-article"
    image_dir.mkdir(parents=True)
    (image_dir / "diagram.png").write_bytes(b"\x89PNG")

    ingest.download_images(markdown_file=md_file, image_dir=image_dir)

    assert "![diagram](../images/some-article/diagram.png)" in md_file.read_text(
        encoding="utf-8",
    )


def test_download_images_handles_same_directory(tmp_path):
    md_file = tmp_path / "note.md"
    md_file.write_text("![x](https://example.com/x.png)\n", encoding="utf-8")

    image_dir = tmp_path / "assets"
    image_dir.mkdir()
    (image_dir / "x.png").write_bytes(b"\x89PNG")

    ingest.download_images(markdown_file=md_file, image_dir=image_dir)

    assert "![x](assets/x.png)" in md_file.read_text(encoding="utf-8")


# -- ingest follows the bundle's configured raw directory --------------------
#
# These were module constants derived from a hardcoded Path("raw"), so the
# commands only worked from the bundle root and never honoured a renamed raw
# zone. They are resolved per call now, which is what these pin.


def test_ingest_subdirectories_follow_the_configured_raw_zone(tmp_path, monkeypatch):
    (tmp_path / "okf.toml").write_text('[paths]\nraw = "sources"\n', encoding="utf-8")
    (tmp_path / "sources").mkdir()
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(ingest.app, ["list-untranscribed"])

    assert result.exit_code == 0
    assert "sources/handwritten" in result.output.replace("\\", "/")


def test_ingest_resolves_the_raw_zone_from_a_nested_directory(tmp_path, monkeypatch):
    """Discovery walks up, so a command need not be run from the bundle root."""
    (tmp_path / "okf.toml").write_text("", encoding="utf-8")
    nested = tmp_path / "raw" / "notes"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    result = CliRunner().invoke(ingest.app, ["list-untranscribed"])

    assert result.exit_code == 0
    assert str(tmp_path / "raw" / "handwritten") in result.output


# -- the raw zone's name is configurable -------------------------------------
#
# A bundle adopted from an existing folder often calls its zones something else.
# Matching a hardcoded "raw/" made `kb-provenance migrate` find nothing there and
# report every article as already declaring its sources — a false clean, on the
# exact command whose job is to find what is missing.


def test_source_links_are_parsed_from_a_renamed_raw_zone(tmp_path):
    article = tmp_path / "articles" / "a.md"
    article.parent.mkdir(parents=True)
    article.write_text(
        "# A\n\n## Sources\n\n- [Talk](../notes/talk.md)\n",
        encoding="utf-8",
    )
    assert provenance._parse_source_links(article.read_text(), article, "notes")
    assert provenance._parse_source_links(article.read_text(), article, "raw") == []


def test_source_zone_honours_a_renamed_raw_zone():
    assert okf.source_zone("notes/papers/x.md", "notes") == "papers"
    assert okf.source_zone("notes/papers/x.md") == ""
    assert okf.source_zone("raw/papers/x.md") == "papers"
