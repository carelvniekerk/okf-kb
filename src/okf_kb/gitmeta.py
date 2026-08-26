"""Git archaeology for provenance backfill.

Recovers who and what produced a wiki article, and when, from git history.

Two traps make the naive approaches wrong, and both are exercised by this
repository's real history:

1. ``git log --follow`` scores renames by content similarity and will happily
   trace a wiki article back into ``raw/`` when a research brief was promoted
   near-verbatim. The producing commit then looks like the ``ingest:`` commit
   that created the *source*, not the ``compile:`` commit that created the
   article. Rename following must stop at the zone boundary.

2. ``git log`` without ``--follow`` misses in-zone renames, so the 2026-04-08
   "restructure wiki into subdirectories" commit reads as the creation of every
   article it moved.

The rule this module implements is *follow renames, but only within the zone*.
A rename whose source lies outside the zone is treated as the article's
creation: that commit is the moment the content entered the bundle.

Articles that were deleted and later re-created are resolved to the most recent
creation, since that is where the current content's lineage actually begins.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

#: Prefix stripped from ``Co-Authored-By`` trailers to yield a model name.
_TRAILER_PREFIX = "co-authored-by:"

#: Trailer values that identify a human rather than a model.
_NON_MODEL_AUTHORS = frozenset({"gemini"})


class GitError(RuntimeError):
    """Raised when a git invocation fails."""


@dataclass(frozen=True)
class Commit:
    """A commit's provenance-relevant metadata."""

    sha: str
    date: datetime
    subject: str
    #: Model name from the ``Co-Authored-By`` trailer, e.g. ``claude-opus-4-6``.
    #: ``None`` when the commit carries no such trailer.
    model: str | None

    @property
    def attested(self) -> bool:
        """Whether the producing model is recorded in the commit itself."""
        return self.model is not None

    @property
    def skill(self) -> str | None:
        """The skill inferred from the commit subject's ``<type>:`` prefix.

        Commit types map onto the skills that produce them (``compile:`` is
        written by ``/kb:compile``, and so on). Types with no corresponding skill,
        such as ``chore:`` or ``refactor:``, yield ``None``.
        """
        head, sep, _ = self.subject.partition(":")
        if not sep:
            return None
        candidate = head.strip().lower()
        return candidate if candidate in _SKILL_COMMIT_TYPES else None


#: Commit-message types that correspond to a producing skill.
_SKILL_COMMIT_TYPES = frozenset(
    {"compile", "ingest", "qa", "transcribe", "capture", "video"},
)


def _git(*args: str, cwd: Path | None = None) -> str:
    """Run a git command and return its stdout.

    Args:
        *args: Arguments following ``git``.
        cwd: Repository directory. Defaults to the current directory.

    Returns:
        Captured stdout, with trailing whitespace stripped.

    Raises:
        GitError: If git exits non-zero.

    """
    try:
        result = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        msg = f"git {' '.join(args)} failed: {exc.stderr.strip()}"
        raise GitError(msg) from exc
    return result.stdout.rstrip("\n")


def _git_optional(*args: str, cwd: Path | None = None) -> str | None:
    """Run a git command, returning ``None`` instead of raising on failure.

    Used for lookups that answer "what does history say about this?". Outside a
    repository, or for a path git has never seen, the honest answer is "nothing
    known" rather than an error — callers degrade by omitting the metadata.

    Args:
        *args: Arguments following ``git``.
        cwd: Repository directory.

    Returns:
        Captured stdout, or ``None`` if git failed.

    """
    try:
        return _git(*args, cwd=cwd)
    except GitError:
        return None


def normalise_model(trailer_value: str) -> str | None:
    """Convert a ``Co-Authored-By`` trailer value into an OKF actor id.

    Args:
        trailer_value: The raw value, e.g. ``Claude Opus 4.6 <noreply@...>``.

    Returns:
        A kebab-case actor id such as ``claude-opus-4-6``, or ``None`` if the
        value does not name a Claude model.

    Examples:
        >>> normalise_model("Claude Opus 4.6 <noreply@anthropic.com>")
        'claude-opus-4-6'
        >>> normalise_model("Claude Sonnet 5 <noreply@anthropic.com>")
        'claude-sonnet-5'
        >>> normalise_model("Claude Opus 4.7 (1M context) <noreply@anthropic.com>")
        'claude-opus-4-7'
        >>> normalise_model("Gemini <noreply@google.com>") is None
        True

    """
    name, _, _ = trailer_value.partition("<")
    # Parenthesised qualifiers such as "(1M context)" describe the context
    # window, not the model identity, so they are dropped.
    name, _, _ = name.partition("(")
    name = name.strip().lower()
    if not name or name in _NON_MODEL_AUTHORS:
        return None
    if not name.startswith("claude"):
        return None
    return name.replace(".", "-").replace(" ", "-")


def _parse_trailer(body: str) -> str | None:
    """Extract the first Claude model from a commit body's trailers."""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(_TRAILER_PREFIX):
            value = stripped[len(_TRAILER_PREFIX) :].strip()
            model = normalise_model(value)
            if model is not None:
                return model
    return None


def commit_info(sha: str, cwd: Path | None = None) -> Commit:
    """Look up a single commit's provenance metadata.

    Args:
        sha: Any git revision.
        cwd: Repository directory.

    Returns:
        The commit's metadata, including the attested model when present.

    Raises:
        GitError: If the revision cannot be resolved.

    """
    raw = _git("log", "-1", "--format=%h%x00%aI%x00%s%x00%b", sha, cwd=cwd)
    short, iso, subject, body = [*raw.split("\x00", 3), "", "", "", ""][:4]
    return Commit(
        sha=short,
        date=datetime.fromisoformat(iso),
        subject=subject,
        model=_parse_trailer(body),
    )


@dataclass(frozen=True)
class _Record:
    """One add/delete/rename entry from ``git log --name-status``."""

    sha: str
    status: str
    old_path: str | None
    new_path: str


def _parse_name_status(raw: str) -> list[_Record]:
    """Parse ``git log --format=%x01%h --name-status`` output, newest first."""
    records: list[_Record] = []
    sha = ""
    for line in raw.splitlines():
        if line.startswith("\x01"):
            sha = line[1:].strip()
            continue
        if not line.strip() or not sha:
            continue
        parts = line.split("\t")
        status = parts[0][0]
        if status == "R" and len(parts) >= 3:  # noqa: PLR2004
            records.append(_Record(sha, "R", parts[1], parts[2]))
        elif len(parts) >= 2:  # noqa: PLR2004
            records.append(_Record(sha, status, None, parts[1]))
    return records


def rename_map(
    zone: str = "wiki",
    cwd: Path | None = None,
) -> dict[str, tuple[str, str]]:
    """Build a ``{new_path: (old_path, sha)}`` map of renames inside ``zone``.

    Git only detects renames among the paths a log is limited to. Limiting to a
    single file therefore suppresses detection entirely (an in-zone move reads
    as a fresh add), while ``--follow`` over-reaches and will trace a wiki
    article back into ``raw/`` whenever a source was promoted near-verbatim.

    Limiting to the zone directory resolves both: renames within the zone are
    visible, and renames from outside it are excluded by construction.

    Args:
        zone: Directory to scan, e.g. ``wiki``.
        cwd: Repository directory.

    Returns:
        A mapping from each rename destination to its origin and the commit that
        performed the move.

    """
    raw = _git_optional(
        "log",
        "-M",
        "--diff-filter=R",
        "--format=%x01%h",
        "--name-status",
        "--",
        f"{zone}/",
        cwd=cwd,
    )
    if raw is None:
        return {}

    mapping: dict[str, tuple[str, str]] = {}
    for record in _parse_name_status(raw):
        if record.status == "R" and record.old_path:
            # Newest-first, so an earlier entry wins if a path was moved twice.
            mapping.setdefault(record.new_path, (record.old_path, record.sha))
    return mapping


def _adds(path: str, cwd: Path | None = None) -> list[_Record]:
    """Return add/delete records for an exact path, newest first."""
    raw = _git_optional(
        "log",
        "--diff-filter=AD",
        "--format=%x01%h",
        "--name-status",
        "--",
        path,
        cwd=cwd,
    )
    return _parse_name_status(raw) if raw is not None else []


def creation_commit(
    article: Path,
    zone: str = "wiki",
    cwd: Path | None = None,
) -> str | None:
    """Find the commit that produced an article's current content lineage.

    Walks in-zone renames backwards to the article's original path, then returns
    the most recent commit that added it. "Most recent" matters: an article that
    was deleted and later rebuilt resolves to the rebuild, since that is where
    the current content actually originates.

    Args:
        article: Repository-relative path to the article.
        zone: Directory the article must stay within, e.g. ``wiki``.
        cwd: Repository directory.

    Returns:
        The short sha of the producing commit, or ``None`` if the path has no
        history within the zone.

    """
    renames = rename_map(zone=zone, cwd=cwd)

    current = article.as_posix()
    seen: set[str] = {current}
    while current in renames:
        origin, _ = renames[current]
        if origin in seen:  # defensive: a rename cycle would otherwise spin
            break
        seen.add(origin)
        current = origin

    for record in _adds(current, cwd=cwd):
        if record.status == "A" and record.new_path == current:
            return record.sha
    return None


@dataclass(frozen=True)
class Provenance:
    """Everything recoverable about how a document was produced."""

    commit: Commit
    skill: str | None
    skill_version: str | None

    @property
    def skill_ref(self) -> str | None:
        """The ``name@sha`` reference for the producing skill, if known."""
        if self.skill is None:
            return None
        if self.skill_version is None:
            return self.skill
        return f"{self.skill}@{self.skill_version}"


#: Historical locations of a skill's definition, newest layout first. The repo
#: migrated from flat ``.claude/commands/<name>.md`` to directory-based
#: ``.claude/skills/<name>/SKILL.md`` on 2026-05-11, so backfilling a commit
#: from before that date must look in the old location.
_SKILL_PATHS = (".claude/skills/{name}", ".claude/commands/{name}.md")


def skill_version(skill: str, at_commit: str, cwd: Path | None = None) -> str | None:
    """Find the sha of the last change to a skill as of a given commit.

    Args:
        skill: Skill name, e.g. ``compile``.
        at_commit: The commit to look back from.
        cwd: Repository directory.

    Returns:
        Short sha of the most recent commit touching the skill at or before
        ``at_commit``, or ``None`` if the skill did not yet exist.

    """
    for template in _SKILL_PATHS:
        try:
            out = _git(
                "log",
                "-1",
                "--format=%h",
                at_commit,
                "--",
                template.format(name=skill),
                cwd=cwd,
            )
        except GitError:
            continue
        if out.strip():
            return out.strip()
    return None


def provenance(
    article: Path,
    zone: str = "wiki",
    cwd: Path | None = None,
) -> Provenance | None:
    """Recover full production provenance for an article.

    Args:
        article: Repository-relative path to the article.
        zone: Directory the article must stay within.
        cwd: Repository directory.

    Returns:
        The provenance record, or ``None`` if the article is untracked.

    """
    sha = creation_commit(article, zone=zone, cwd=cwd)
    if sha is None:
        return None
    commit = commit_info(sha, cwd=cwd)
    skill = commit.skill
    version = skill_version(skill, sha, cwd=cwd) if skill else None
    return Provenance(commit=commit, skill=skill, skill_version=version)


def last_modified(path: Path, cwd: Path | None = None) -> str | None:
    """Return the date of the last commit touching a path, as ``YYYY-MM-DD``.

    Args:
        path: Repository-relative path.
        cwd: Repository directory.

    Returns:
        The date string, or ``None`` if the path is untracked.

    """
    out = _git_optional(
        "log",
        "-1",
        "--format=%ad",
        "--date=short",
        "--",
        path.as_posix(),
        cwd=cwd,
    )
    return (out.strip() or None) if out is not None else None
