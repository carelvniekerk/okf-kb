"""Tests for OKF v0.2 schema construction.

Covers id/title/author derivation and the full article migration. The cases
using real repository paths are pinned against fixtures written to ``tmp_path``
rather than the live wiki, so they do not drift as articles change.
"""

# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from okf_kb import frontmatter as fm
from okf_kb import okf


class TestSourceId:
    def test_arxiv_stem(self) -> None:
        assert okf.source_id("raw/papers/2307.08691.md") == "2307-08691"

    def test_meeting_stem_is_already_kebab(self) -> None:
        resource = "raw/meetings/2026-08-04-ccep-kpi-discussion.md"
        assert okf.source_id(resource) == "2026-08-04-ccep-kpi-discussion"

    def test_notion_hex_suffix_is_stripped(self) -> None:
        """Notion exports append a 32-char hex id that carries no meaning."""
        resource = (
            "raw/notes/Rethinking Pre-training 24705d5fdedf801aa3c4c76b8c244172.md"
        )
        assert "24705d5f" not in okf.source_id(resource)

    def test_spaces_become_hyphens(self) -> None:
        assert okf.source_id("raw/notes/My Great Note.md") == "my-great-note"

    def test_long_id_is_trimmed_at_word_boundary(self) -> None:
        resource = (
            "raw/notes/FlashAttention-2 Faster Attention with Better Parallelism.md"
        )
        result = okf.source_id(resource)
        assert len(result) <= okf._MAX_ID_LENGTH
        assert not result.endswith("-")
        # Trimmed on a boundary, so the last segment is a whole word.
        assert result.split("-")[-1] in {"faster", "attention", "with", "better", "2"}

    def test_collisions_get_a_numeric_suffix(self) -> None:
        taken: set[str] = set()
        first = okf.source_id("raw/a/note.md", taken)
        second = okf.source_id("raw/b/note.md", taken)
        assert first == "note"
        assert second == "note-2"

    def test_taken_set_is_updated(self) -> None:
        taken: set[str] = set()
        okf.source_id("raw/a/note.md", taken)
        assert "note" in taken

    def test_degenerate_name_falls_back(self) -> None:
        assert okf.source_id("raw/notes/---.md") == "source"


class TestSourceZone:
    @pytest.mark.parametrize(
        ("resource", "expected"),
        [
            ("raw/papers/2307.08691.md", "papers"),
            ("raw/meetings/a.md", "meetings"),
            ("raw/research/brief.md", "research"),
            ("raw/loose.md", ""),
        ],
    )
    def test_zone(self, resource: str, expected: str) -> None:
        assert okf.source_zone(resource, "raw") == expected


class TestSourceAuthor:
    @pytest.mark.parametrize(
        "resource",
        [
            "raw/notes/x.md",
            "raw/meetings/x.md",
            "raw/papers/x.md",
            "raw/clippings/x.md",
            "raw/loose.md",
            "raw/research/x.md",
        ],
    )
    def test_no_author_is_inferred_from_the_directory(
        self,
        tmp_path,
        resource: str,
    ) -> None:
        """Git names the committer, not the writer, so no trailer means no author."""
        assert okf.source_author(resource, tmp_path, "raw") is None


class TestSourceTitle:
    def test_prefers_frontmatter_title(self, tmp_path) -> None:
        (tmp_path / "raw").mkdir()
        (tmp_path / "raw" / "n.md").write_text(
            "---\ntitle: Declared Title\n---\n\n# Heading Title\n",
            encoding="utf-8",
        )
        assert okf.source_title("raw/n.md", tmp_path) == "Declared Title"

    def test_falls_back_to_first_heading(self, tmp_path) -> None:
        (tmp_path / "raw").mkdir()
        (tmp_path / "raw" / "n.md").write_text("# Heading Title\n", encoding="utf-8")
        assert okf.source_title("raw/n.md", tmp_path) == "Heading Title"

    def test_skips_the_arxiv_banner_heading(self, tmp_path) -> None:
        """`kb-ingest arxiv` writes `# arXiv: <id>` above the real title."""
        (tmp_path / "raw").mkdir()
        (tmp_path / "raw" / "p.md").write_text(
            "# arXiv: 2307.08691\n\nmeta\n\n# FlashAttention-2: Faster Attention\n",
            encoding="utf-8",
        )
        assert (
            okf.source_title("raw/p.md", tmp_path)
            == "FlashAttention-2: Faster Attention"
        )

    def test_falls_back_to_filename_when_missing(self, tmp_path) -> None:
        assert okf.source_title("raw/notes/Some Note.md", tmp_path) == "Some Note"

    def test_malformed_source_does_not_raise(self, tmp_path) -> None:
        (tmp_path / "raw").mkdir()
        (tmp_path / "raw" / "b.md").write_text(
            "---\ntitle: [oops\n---\nbody\n",
            encoding="utf-8",
        )
        assert okf.source_title("raw/b.md", tmp_path) == "b"


class TestReorder:
    def test_okf_keys_come_first(self) -> None:
        data = {"date_added": 1, "sources": 2, "type": 3, "tags": 4}
        assert list(okf.reorder(data)) == ["type", "tags", "sources", "date_added"]

    def test_unknown_keys_are_preserved_at_the_end(self) -> None:
        data = {"custom": 1, "type": 2}
        result = okf.reorder(data)
        assert list(result) == ["type", "custom"]
        assert result["custom"] == 1

    def test_no_keys_are_lost(self) -> None:
        data = {"z": 1, "type": 2, "tags": 3, "aaa": 4, "arxiv": "5"}
        assert set(okf.reorder(data)) == set(data)


class TestMigrate:
    """End-to-end reshape of a legacy article, using a throwaway repo."""

    @staticmethod
    def _article(tmp_path) -> tuple[fm.Document, Path]:
        (tmp_path / "raw" / "notes").mkdir(parents=True)
        (tmp_path / "raw" / "notes" / "alpha.md").write_text(
            "# Alpha Note\n",
            encoding="utf-8",
        )
        (tmp_path / "wiki").mkdir()
        article = tmp_path / "wiki" / "a.md"
        article.write_text(
            "---\n"
            "tags: [x, y]\n"
            "type: concept\n"
            "date_added: 2026-04-04\n"
            "sources: 1\n"
            "source_files:\n"
            "  - raw/notes/alpha.md\n"
            "source_type: technical\n"
            "---\n\n"
            "# A\n",
            encoding="utf-8",
        )
        return fm.load(article), Path("wiki/a.md")

    def test_source_files_is_removed(self, tmp_path) -> None:
        doc, rel = self._article(tmp_path)
        out = okf.migrate(doc, rel, tmp_path, wiki_name="wiki", raw_name="raw")
        assert "source_files" not in out.frontmatter

    def test_sources_becomes_a_list_of_mappings(self, tmp_path) -> None:
        doc, rel = self._article(tmp_path)
        out = okf.migrate(doc, rel, tmp_path, wiki_name="wiki", raw_name="raw")
        sources = out.frontmatter["sources"]
        assert isinstance(sources, list)
        assert sources[0]["id"] == "alpha"
        assert sources[0]["resource"] == "raw/notes/alpha.md"
        assert sources[0]["title"] == "Alpha Note"
        assert "author" not in sources[0]

    def test_integer_count_is_gone(self, tmp_path) -> None:
        """The redundant `sources: <int>` must not survive migration."""
        doc, rel = self._article(tmp_path)
        out = okf.migrate(doc, rel, tmp_path, wiki_name="wiki", raw_name="raw")
        assert not isinstance(out.frontmatter["sources"], int)

    def test_status_defaults_to_stable(self, tmp_path) -> None:
        doc, rel = self._article(tmp_path)
        assert (
            okf.migrate(
                doc,
                rel,
                tmp_path,
                wiki_name="wiki",
                raw_name="raw",
            ).frontmatter["status"]
            == "stable"
        )

    def test_verified_is_never_written(self, tmp_path) -> None:
        """Absent `verified` is the honest unverified tier under OKF §5.2."""
        doc, rel = self._article(tmp_path)
        assert (
            "verified"
            not in okf.migrate(
                doc,
                rel,
                tmp_path,
                wiki_name="wiki",
                raw_name="raw",
            ).frontmatter
        )

    def test_local_extensions_survive(self, tmp_path) -> None:
        doc, rel = self._article(tmp_path)
        out = okf.migrate(doc, rel, tmp_path, wiki_name="wiki", raw_name="raw")
        assert out.frontmatter["source_type"] == "technical"
        assert out.frontmatter["date_added"] == dt.date(2026, 4, 4)

    def test_body_is_untouched(self, tmp_path) -> None:
        doc, rel = self._article(tmp_path)
        assert (
            okf.migrate(doc, rel, tmp_path, wiki_name="wiki", raw_name="raw").body
            == doc.body
        )

    def test_key_order_is_canonical(self, tmp_path) -> None:
        doc, rel = self._article(tmp_path)
        keys = list(
            okf.migrate(
                doc,
                rel,
                tmp_path,
                wiki_name="wiki",
                raw_name="raw",
            ).frontmatter,
        )
        assert keys.index("type") < keys.index("sources")
        assert keys.index("sources") < keys.index("source_type")

    def test_is_idempotent(self, tmp_path) -> None:
        """Re-running must not double-migrate or churn the data."""
        doc, rel = self._article(tmp_path)
        once = okf.migrate(doc, rel, tmp_path, wiki_name="wiki", raw_name="raw")
        twice = okf.migrate(once, rel, tmp_path, wiki_name="wiki", raw_name="raw")
        assert once.frontmatter == twice.frontmatter

    def test_existing_source_mappings_are_kept(self, tmp_path) -> None:
        """A curated `sources` list holds ids and authors that paths cannot rebuild."""
        doc, rel = self._article(tmp_path)
        curated = [
            {
                "id": "my-own-id",
                "resource": "raw/notes/alpha.md",
                "title": "Hand-written title",
                "author": "human:someone",
            },
        ]
        doc.frontmatter.pop("source_files")
        doc.frontmatter["sources"] = curated
        out = okf.migrate(doc, rel, tmp_path, wiki_name="wiki", raw_name="raw")
        assert out.frontmatter["sources"] == curated

    def test_existing_status_is_not_overwritten(self, tmp_path) -> None:
        doc, rel = self._article(tmp_path)
        doc.frontmatter["status"] = "draft"
        assert (
            okf.migrate(
                doc,
                rel,
                tmp_path,
                wiki_name="wiki",
                raw_name="raw",
            ).frontmatter["status"]
            == "draft"
        )

    def test_result_round_trips_through_the_parser(self, tmp_path) -> None:
        doc, rel = self._article(tmp_path)
        out = okf.migrate(doc, rel, tmp_path, wiki_name="wiki", raw_name="raw")
        reparsed, _ = fm.parse(fm.dumps(out.frontmatter, out.body))
        assert reparsed["sources"][0]["id"] == "alpha"
        assert reparsed["status"] == "stable"
