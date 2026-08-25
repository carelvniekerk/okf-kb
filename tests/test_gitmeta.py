"""Tests for git-based provenance recovery.

`TestRecoveredHistory` pins the three cases where the obvious git invocation
gives the wrong answer: an in-zone rename read as a fresh creation, a rebuilt
article resolved to its long-deleted original, and `--follow` tracing a wiki
article back into the source that was promoted into it.

They run against a repository the fixture builds commit by commit. That costs a
little setup over asserting on shas from some real history, and buys tests that
travel with the package rather than describing one checkout, and that state the
scenario they guard in the fixture instead of in a comment.
"""

# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from okf_kb import gitmeta

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Arbitrary fixed timestamp for commits built by hand in tests.
STAMP = datetime(2026, 4, 7, 14, 22, 31, tzinfo=UTC)

#: Trailers attributing a commit to a model, as the commit convention writes them.
OPUS = "Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
SONNET = "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"

needs_git = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git is not installed",
)


def _git(repo: Path, *args: str) -> str:
    """Run git in the fixture repo and return its stdout."""
    result = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _write(repo: Path, rel: str, text: str) -> None:
    """Write a file inside the repo, creating parent directories."""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(repo: Path, subject: str, trailer: str | None = None) -> str:
    """Stage everything and commit, returning the new short sha."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"{subject}\n\n{trailer}" if trailer else subject)
    return _git(repo, "rev-parse", "--short", "HEAD")


@pytest.fixture(scope="module")
def history() -> Iterator[dict[str, Path | str]]:
    """Build a bundle whose history contains every case worth pinning.

    Keyed by a name per commit so an assertion can say which commit it expects
    rather than repeating a literal sha.
    """
    root = Path(tempfile.mkdtemp(prefix="okf-kb-history-"))
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "commit.gpgsign", "false")

    shas: dict[str, Path | str] = {"root": root}

    _write(root, "wiki/INDEX.md", "# Index\n")
    shas["init"] = _commit(root, "init: empty bundle")

    # The skill is defined at the pre-2026-05-11 path, so skill_version has to
    # fall back to it. Nothing committed before this can resolve a version.
    _write(root, ".claude/commands/compile.md", "# compile\n")
    shas["skill_added"] = _commit(root, "chore: add the compile skill")

    _write(root, "raw/research/brief.md", "# Brief\n\nFindings about tiling.\n")
    shas["ingest"] = _commit(root, "ingest: add the brief", SONNET)

    _write(root, "wiki/attention.md", "# Attention\n\nThe original attention one.\n")
    shas["create"] = _commit(root, "compile: write attention", OPUS)

    # An in-zone restructure. Without rename following it would masquerade as
    # the article's creation.
    (root / "wiki" / "efficiency").mkdir()
    _git(root, "mv", "wiki/attention.md", "wiki/efficiency/attention.md")
    shas["restructure"] = _commit(root, "refactor: file articles by topic")

    # A near-verbatim promotion out of raw/. The source stays put, so --follow
    # scores the wiki article as a rename of it and reports the ingest commit.
    shutil.copy(root / "raw/research/brief.md", root / "wiki/research-brief.md")
    shas["promote"] = _commit(root, "compile: promote the brief", OPUS)

    # Written, retired and rebuilt at one path, never renamed — so the rename
    # walk cannot reach an earlier path and the delete is what has to be
    # honoured. Keeping this separate from the renamed article is deliberate:
    # a file that was both moved and rebuilt resolves to its pre-move creation,
    # which would make this case pass for the wrong reason.
    _write(root, "wiki/efficiency/tiling.md", "# Tiling\n\nThe first draft.\n")
    shas["first_draft"] = _commit(root, "compile: write tiling", OPUS)

    (root / "wiki/efficiency/tiling.md").unlink()
    shas["retire"] = _commit(root, "compile: retire tiling")

    _write(root, "wiki/efficiency/tiling.md", "# Tiling\n\nRebuilt from scratch.\n")
    shas["rebuild"] = _commit(root, "compile: rebuild tiling", OPUS)

    _write(root, "wiki/INDEX.md", "# Index\n\nUpdated.\n")
    shas["reindex"] = _commit(root, "compile: refresh the index", OPUS)

    yield shas
    shutil.rmtree(root, ignore_errors=True)


class TestNormaliseModel:
    """Trailer values become OKF actor ids."""

    @pytest.mark.parametrize(
        ("trailer", "expected"),
        [
            ("Claude Opus 4.6 <noreply@anthropic.com>", "claude-opus-4-6"),
            ("Claude Sonnet 4.6 <noreply@anthropic.com>", "claude-sonnet-4-6"),
            ("Claude Sonnet 5 <noreply@anthropic.com>", "claude-sonnet-5"),
            ("Claude <noreply@anthropic.com>", "claude"),
        ],
    )
    def test_known_models(self, trailer: str, expected: str) -> None:
        assert gitmeta.normalise_model(trailer) == expected

    @pytest.mark.parametrize(
        "trailer",
        [
            "Claude Opus 4.7 (1M context) <noreply@anthropic.com>",
            "Claude Opus 4.7 (1M context)",
        ],
    )
    def test_context_qualifier_is_dropped(self, trailer: str) -> None:
        """`(1M context)` describes the context window, not the model."""
        assert gitmeta.normalise_model(trailer) == "claude-opus-4-7"

    def test_non_claude_author_is_rejected(self) -> None:
        assert gitmeta.normalise_model("Gemini <noreply@google.com>") is None

    def test_human_coauthor_is_rejected(self) -> None:
        assert gitmeta.normalise_model("Jane Doe <jane@example.com>") is None

    def test_empty_is_rejected(self) -> None:
        assert gitmeta.normalise_model("") is None


class TestSkillInference:
    """The commit subject's type prefix names the producing skill."""

    @pytest.mark.parametrize(
        ("subject", "expected"),
        [
            ("compile: integrate four research briefs", "compile"),
            ("ingest: promote briefs to raw/research/", "ingest"),
            ("qa: answer question about RoPE", "qa"),
            ("refactor: split agreement data model out", None),
            ("chore: remove outdated articles", None),
            ("tools: add slash commands", None),
            ('Revert "vault backup: 2026-04-23"', None),
            ("no colon here", None),
        ],
    )
    def test_subject_maps_to_skill(self, subject: str, expected: str | None) -> None:
        commit = gitmeta.Commit(sha="abc1234", date=STAMP, subject=subject, model=None)
        assert commit.skill == expected


class TestAttested:
    def test_attested_when_model_present(self) -> None:
        commit = gitmeta.Commit("abc", STAMP, "compile: x", "claude-opus-4-6")
        assert commit.attested

    def test_not_attested_when_model_absent(self) -> None:
        commit = gitmeta.Commit("abc", STAMP, "compile: x", None)
        assert not commit.attested


class TestProvenanceSkillRef:
    def test_name_and_version(self) -> None:
        commit = gitmeta.Commit("abc", STAMP, "compile: x", "claude-sonnet-5")
        prov = gitmeta.Provenance(
            commit=commit,
            skill="compile",
            skill_version="53756f8",
        )
        assert prov.skill_ref == "compile@53756f8"

    def test_name_only_when_version_unknown(self) -> None:
        commit = gitmeta.Commit("abc", STAMP, "compile: x", "claude-sonnet-5")
        prov = gitmeta.Provenance(commit=commit, skill="compile", skill_version=None)
        assert prov.skill_ref == "compile"

    def test_none_when_no_skill(self) -> None:
        commit = gitmeta.Commit("abc", STAMP, "refactor: x", None)
        prov = gitmeta.Provenance(commit=commit, skill=None, skill_version=None)
        assert prov.skill_ref is None


@needs_git
class TestRecoveredHistory:
    """Regression pins for the three cases naive git invocations get wrong."""

    def test_in_zone_rename_is_followed(self, history) -> None:
        """A restructure must not masquerade as the article's creation.

        `attention.md` was written by `create` and only moved by `restructure`.
        """
        sha = gitmeta.creation_commit(
            Path("wiki/efficiency/attention.md"),
            zone="wiki",
            cwd=history["root"],
        )
        assert sha == history["create"]
        assert sha != history["restructure"]

    def test_delete_and_recreate_resolves_to_latest_creation(self, history) -> None:
        """`tiling.md` was written, retired, then rebuilt from scratch.

        The current content's lineage starts at the rebuild, not the original.
        """
        sha = gitmeta.creation_commit(
            Path("wiki/efficiency/tiling.md"),
            zone="wiki",
            cwd=history["root"],
        )
        assert sha == history["rebuild"]
        assert sha != history["first_draft"]

    def test_promotion_out_of_raw_is_not_followed(self, history) -> None:
        """The brief was promoted out of `raw/` near-verbatim.

        `git log --follow` scores that as a rename and reports the `ingest:`
        commit that created the *source*. The article's own creation is the
        later `compile:` commit that promoted it.
        """
        sha = gitmeta.creation_commit(
            Path("wiki/research-brief.md"),
            zone="wiki",
            cwd=history["root"],
        )
        assert sha == history["promote"]
        assert sha != history["ingest"]

    def test_untracked_path_returns_none(self, history) -> None:
        sha = gitmeta.creation_commit(
            Path("wiki/does-not-exist.md"),
            cwd=history["root"],
        )
        assert sha is None

    def test_provenance_recovers_attested_model(self, history) -> None:
        prov = gitmeta.provenance(
            Path("wiki/efficiency/tiling.md"),
            cwd=history["root"],
        )
        assert prov is not None
        assert prov.commit.model == "claude-opus-4-6"
        assert prov.commit.attested
        assert prov.skill == "compile"

    def test_skill_version_resolves_via_legacy_command_path(self, history) -> None:
        """Before 2026-05-11 the skill lived at `.claude/commands/<name>.md`."""
        version = gitmeta.skill_version(
            "compile",
            str(history["rebuild"]),
            cwd=history["root"],
        )
        assert version == history["skill_added"]

    def test_skill_version_is_none_before_skill_existed(self, history) -> None:
        """Nothing defined `compile` at the initial commit."""
        version = gitmeta.skill_version(
            "compile",
            str(history["init"]),
            cwd=history["root"],
        )
        assert version is None

    def test_last_modified_returns_iso_date(self, history) -> None:
        date = gitmeta.last_modified(Path("wiki/INDEX.md"), cwd=history["root"])
        assert date is not None
        assert len(date) == len("YYYY-MM-DD")
        assert date.count("-") == 2


@needs_git
def test_commit_info_parses_trailer(history) -> None:
    commit = gitmeta.commit_info(str(history["rebuild"]), cwd=history["root"])
    assert commit.model == "claude-opus-4-6"
    assert commit.subject.startswith("compile:")


@needs_git
def test_commit_without_a_trailer_has_no_model(history) -> None:
    commit = gitmeta.commit_info(str(history["restructure"]), cwd=history["root"])
    assert commit.model is None
    assert not commit.attested


@needs_git
def test_bad_revision_raises(history) -> None:
    with pytest.raises(gitmeta.GitError):
        gitmeta.commit_info("definitely-not-a-real-revision", cwd=history["root"])
