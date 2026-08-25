"""Tests for ``raw/`` reference-zone frontmatter normalisation.

``raw/`` is OKF's references zone (§6.3), so the bar is identity rather than
bundle conformance: enough metadata to cite a source, and nothing that
misrepresents it. The two things that can go wrong are losing a hand-written key
and altering the body, so both are pinned here.

Git-dependent derivations run against a throwaway repository built in
``tmp_path``, since author and creation date come from commit history.
"""

# ruff: noqa: ANN001, ANN201, D100, D101, D102, D103, INP001, PLR2004, RUF100, S101, SLF001, TC003

from __future__ import annotations

import datetime as dt
import subprocess
from pathlib import Path

import pytest

from okf_kb import frontmatter as fm
from okf_kb import okf

MEETING = "raw/meetings/2026-07-16-accenture-mythos-assessment-platform.md"
VIDEO = "raw/videos/the-state-pattern-OeirQdzYdnc.md"


def _document(text: str) -> fm.Document:
    frontmatter, body = fm.parse(text)
    return fm.Document(frontmatter=frontmatter, body=body)


MEETING_FILE = f"""---
tags: [meeting]
type: meeting-log
date_added: 2026-07-16
date_updated: 2026-07-16
meeting_date: 2026-07-16 13:00
attendees: [Brett Orwin, Thomas Schumacher]
sources: 1
source_files:
  - {MEETING}
source_type: meeting
compile: false
---

# Accenture Mythos Assessment Platform — 2026-07-16

## 👥 Attendees

- Brett Orwin
"""

VIDEO_FILE = f"""---
tags: [state-machine, python]
type: tutorial
date_added: 2026-04-28
sources: 1
source_files:
  - {VIDEO}
source_type: technical
video:
  url: https://www.youtube.com/watch?v=OeirQdzYdnc
  video_id: OeirQdzYdnc
  channel: ArjanCodes
  duration: 00:26:23
  uploaded: 2026-04-10
  transcription_method: youtube_captions
---

# The State Pattern in Python

Body text.
"""

ARXIV_FILE = """# arXiv: 2307.08691

Source: https://arxiv.org/abs/2307.08691

---

# FlashAttention-2: Faster Attention with Better Parallelism

Tri Dao
"""

PDF_FILE = """# 2411.15124


## Page 1

Tülu 3: Pushing Frontiers in Open Language Model Post-Training
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Build a throwaway git repository with one commit per ``raw/`` zone."""

    def git(*args: str) -> None:
        subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "Test")

    def commit(resource: str, text: str, message: str) -> None:
        target = tmp_path / resource
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", message)

    commit(MEETING, MEETING_FILE, "capture: meeting")
    commit(
        "raw/daily-briefs/2026-07-09.md",
        "# Daily Brief — 2026-07-09\n",
        "capture: brief\n\nCo-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>",
    )
    commit(
        "raw/research/brief.md",
        "# A Research Brief\n",
        "research: brief",
    )
    commit("raw/papers/2307.08691.md", ARXIV_FILE, "ingest: paper")
    commit("raw/notes/plain.md", "# A Plain Note\n", "ingest: note")
    return tmp_path


class TestRawType:
    @pytest.mark.parametrize(
        ("resource", "expected"),
        [
            ("raw/papers/2307.08691.md", "paper"),
            ("raw/notes/vllm-mac-installation.md", "note"),
            ("raw/clippings/some-article.md", "clipping"),
            ("raw/research/rag-vs-kb.md", "research-brief"),
            ("raw/transcriptions/Notes_260211.md", "transcription"),
            ("raw/daily-briefs/2026-07-09.md", "daily-brief"),
            ("raw/meetings/2026-08-04-kpi.md", "meeting-log"),
        ],
    )
    def test_type_is_derived_from_the_zone(self, resource, expected) -> None:
        assert okf.raw_type(resource) == expected

    def test_unknown_zone_has_no_derived_type(self) -> None:
        assert okf.raw_type("raw/loose-note.md") is None


class TestRawSourceType:
    @pytest.mark.parametrize(
        "resource",
        ["raw/meetings/2026-08-04-kpi.md", "raw/daily-briefs/2026-07-09.md"],
    )
    def test_chronological_zones_are_meetings(self, resource) -> None:
        assert okf.raw_source_type(resource) == "meeting"

    @pytest.mark.parametrize(
        "resource",
        ["raw/papers/2307.08691.md", "raw/notes/plain.md", "raw/loose.md"],
    )
    def test_everything_else_is_technical(self, resource) -> None:
        assert okf.raw_source_type(resource) == "technical"


class TestRawTitle:
    def test_arxiv_banner_is_skipped(self) -> None:
        """`kb-ingest arxiv` writes a banner above the paper's real title."""
        title = okf.raw_title(ARXIV_FILE)
        assert title == "FlashAttention-2: Faster Attention with Better Parallelism"

    def test_bare_id_heading_from_pdf_extraction_is_skipped(self) -> None:
        """PDF extraction leaves the id as the only H1, which names nothing."""
        assert okf.raw_title(PDF_FILE) is None

    def test_first_heading_wins_otherwise(self) -> None:
        assert okf.raw_title("# Real Title\n\n# Later Heading\n") == "Real Title"

    def test_no_heading_returns_none(self) -> None:
        assert okf.raw_title("Sie mochten Ihre Briefpost empfangen?\n") is None


class TestStripSelfReference:
    def test_self_referencing_pair_is_removed(self) -> None:
        data = {"sources": 1, "source_files": [MEETING], "type": "meeting-log"}
        assert okf.strip_self_reference(data, MEETING) is True
        assert "sources" not in data
        assert "source_files" not in data
        assert data["type"] == "meeting-log"

    def test_real_source_list_is_kept(self) -> None:
        data = {"sources": 2, "source_files": ["raw/papers/2307.08691.md", MEETING]}
        assert okf.strip_self_reference(data, MEETING) is False
        assert data["source_files"] == ["raw/papers/2307.08691.md", MEETING]

    def test_bare_count_without_a_file_list_is_kept(self) -> None:
        """On the research briefs `sources: 46` counts works consulted."""
        data = {"sources": 46}
        assert okf.strip_self_reference(data, "raw/notes/brief.md") is False
        assert data["sources"] == 46

    def test_absent_keys_are_a_no_op(self) -> None:
        data: fm.Frontmatter = {"type": "note"}
        assert okf.strip_self_reference(data, "raw/notes/plain.md") is False
        assert data == {"type": "note"}


class TestReorderRaw:
    def test_identity_keys_lead(self) -> None:
        data = {
            "tags": ["meeting"],
            "source_type": "meeting",
            "date_added": "2026-07-16",
            "type": "meeting-log",
            "title": "T",
        }
        assert list(okf.reorder_raw(data)) == [
            "type",
            "title",
            "date_added",
            "tags",
            "source_type",
        ]

    def test_unknown_keys_keep_their_relative_order(self) -> None:
        data = {"compile": False, "mood": "good", "type": "note"}
        assert list(okf.reorder_raw(data)) == ["type", "compile", "mood"]


class TestMigrateRawPreservation:
    def test_self_reference_is_dropped(self, repo: Path) -> None:
        result = okf.migrate_raw(_document(MEETING_FILE), MEETING, repo)
        assert "sources" not in result.frontmatter
        assert "source_files" not in result.frontmatter

    def test_compile_false_survives(self, repo: Path) -> None:
        """`compile: false` keeps a source out of the wiki, so losing it leaks."""
        result = okf.migrate_raw(_document(MEETING_FILE), MEETING, repo)
        assert result.frontmatter["compile"] is False

    def test_meeting_date_and_attendees_survive(self, repo: Path) -> None:
        result = okf.migrate_raw(_document(MEETING_FILE), MEETING, repo)
        assert result.frontmatter["meeting_date"] == "2026-07-16 13:00"
        assert result.frontmatter["attendees"] == ["Brett Orwin", "Thomas Schumacher"]

    def test_attendees_stay_on_one_line(self, repo: Path) -> None:
        result = okf.migrate_raw(_document(MEETING_FILE), MEETING, repo)
        assert "attendees: [Brett Orwin, Thomas Schumacher]" in result.to_text()

    def test_video_block_survives_intact(self, repo: Path) -> None:
        result = okf.migrate_raw(_document(VIDEO_FILE), VIDEO, repo)
        assert result.frontmatter["video"] == {
            "url": "https://www.youtube.com/watch?v=OeirQdzYdnc",
            "video_id": "OeirQdzYdnc",
            "channel": "ArjanCodes",
            "duration": "00:26:23",
            "uploaded": dt.date(2026, 4, 10),
            "transcription_method": "youtube_captions",
        }

    def test_existing_values_are_never_overwritten(self, repo: Path) -> None:
        declared = MEETING_FILE.replace(
            "type: meeting-log",
            "type: meeting-log\ntitle: Declared Title\ndescription: Declared.",
        )
        result = okf.migrate_raw(
            _document(declared),
            MEETING,
            repo,
            title="Ignored",
            description="Ignored",
        )
        assert result.frontmatter["type"] == "meeting-log"
        assert result.frontmatter["date_added"] == dt.date(2026, 7, 16)
        assert result.frontmatter["title"] == "Declared Title"
        assert result.frontmatter["description"] == "Declared."

    def test_body_is_byte_identical(self, repo: Path) -> None:
        document = _document(MEETING_FILE)
        result = okf.migrate_raw(document, MEETING, repo)
        assert result.body == document.body

    def test_body_is_byte_identical_when_frontmatter_is_added(
        self,
        repo: Path,
    ) -> None:
        document = _document(ARXIV_FILE)
        assert not document.has_frontmatter
        result = okf.migrate_raw(document, "raw/papers/2307.08691.md", repo)
        assert result.body == ARXIV_FILE
        assert result.to_text().endswith(ARXIV_FILE)


class TestMigrateRawDerivation:
    def test_type_and_source_type_come_from_the_zone(self, repo: Path) -> None:
        result = okf.migrate_raw(
            _document(ARXIV_FILE),
            "raw/papers/2307.08691.md",
            repo,
        )
        assert result.frontmatter["type"] == "paper"
        assert result.frontmatter["source_type"] == "technical"

    def test_title_skips_the_arxiv_banner(self, repo: Path) -> None:
        result = okf.migrate_raw(
            _document(ARXIV_FILE),
            "raw/papers/2307.08691.md",
            repo,
        )
        assert result.frontmatter["title"].startswith("FlashAttention-2:")

    def test_supplied_title_overrides_a_useless_heading(self, repo: Path) -> None:
        result = okf.migrate_raw(
            _document(PDF_FILE),
            "raw/papers/2411.15124.md",
            repo,
            title="Tülu 3",
        )
        assert result.frontmatter["title"] == "Tülu 3"

    def test_description_is_written_when_absent(self, repo: Path) -> None:
        result = okf.migrate_raw(
            _document(ARXIV_FILE),
            "raw/papers/2307.08691.md",
            repo,
            description="A one-sentence summary.",
        )
        assert result.frontmatter["description"] == "A one-sentence summary."

    @pytest.mark.parametrize(
        ("resource", "expected"),
        [
            (MEETING, "human:carel"),
            ("raw/notes/plain.md", "human:carel"),
            ("raw/loose-note.md", "human:carel"),
            ("raw/papers/2307.08691.md", "process:kb-ingest"),
            ("raw/clippings/article.md", "process:kb-ingest"),
        ],
    )
    def test_author_comes_from_the_zone_role(
        self,
        repo: Path,
        resource,
        expected,
    ) -> None:
        """Git author is useless: the owner commits everything regardless."""
        result = okf.migrate_raw(_document("# T\n"), resource, repo)
        assert result.frontmatter["author"] == expected

    def test_agent_zone_author_is_the_attested_model(self, repo: Path) -> None:
        result = okf.migrate_raw(
            _document("# Daily Brief — 2026-07-09\n"),
            "raw/daily-briefs/2026-07-09.md",
            repo,
        )
        assert result.frontmatter["author"] == "claude-sonnet-5"

    def test_agent_zone_author_falls_back_to_claude(self, repo: Path) -> None:
        """The research brief's commit carries no `Co-Authored-By` trailer."""
        result = okf.migrate_raw(
            _document("# A Research Brief\n"),
            "raw/research/brief.md",
            repo,
        )
        assert result.frontmatter["author"] == "claude"

    def test_date_added_comes_from_the_creating_commit(self, repo: Path) -> None:
        result = okf.migrate_raw(
            _document(ARXIV_FILE),
            "raw/papers/2307.08691.md",
            repo,
        )
        assert result.frontmatter["date_added"] == dt.date.today()  # noqa: DTZ011

    def test_untracked_file_gets_no_date(self, tmp_path: Path) -> None:
        result = okf.migrate_raw(
            _document(ARXIV_FILE),
            "raw/papers/never-committed.md",
            tmp_path,
        )
        assert "date_added" not in result.frontmatter

    def test_identity_keys_lead_the_block(self, repo: Path) -> None:
        result = okf.migrate_raw(
            _document(MEETING_FILE),
            MEETING,
            repo,
            description="Summary.",
        )
        leading = list(result.frontmatter)[:5]
        assert leading == ["type", "title", "description", "author", "date_added"]


class TestMigrateRawIdempotency:
    @pytest.mark.parametrize(
        ("text", "resource"),
        [
            (MEETING_FILE, MEETING),
            (VIDEO_FILE, VIDEO),
            (ARXIV_FILE, "raw/papers/2307.08691.md"),
        ],
    )
    def test_second_pass_changes_nothing(self, repo: Path, text, resource) -> None:
        once = okf.migrate_raw(
            _document(text),
            resource,
            repo,
            description="Summary.",
        )
        twice = okf.migrate_raw(
            _document(once.to_text()),
            resource,
            repo,
            description="A different summary.",
        )
        assert twice.to_text() == once.to_text()
