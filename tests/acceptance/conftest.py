"""Shared fixtures for the acceptance tests of docs/design/okf-kb-architecture-fixes.md.

Each test builds a throwaway bundle in a real git repository, because the
provenance migration derives `generated` and `last_modified` from history.
"""

# ruff: noqa: ANN202, S101, D100, D101, D102, D103, D107, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100, S603, S607

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]

OPUS = "Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"

needs_git = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="git is not installed",
)


class GitBundle:
    """A knowledge base inside a git repository, with its own zone names."""

    def __init__(self, root: Path, wiki: str = "wiki", raw: str = "raw") -> None:
        self.root = root
        self.wiki = wiki
        self.raw = raw
        self._clock = 0
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "commit.gpgsign", "false")
        paths = ""
        if (wiki, raw) != ("wiki", "raw"):
            paths = f'[paths]\nwiki = "{wiki}"\nraw = "{raw}"\n'
        self.write("okf.toml", paths)

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def commit(self, subject: str, trailer: str | None = None) -> str:
        """Stage everything, commit with a fixed advancing date, return the sha."""
        self._clock += 1
        stamp = f"2026-04-{self._clock:02d}T12:00:00+00:00"
        message = subject if trailer is None else f"{subject}\n\n{trailer}"
        env = {**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
        self.git("add", "-A")
        subprocess.run(
            ["git", "commit", "-q", "-m", message],
            cwd=self.root,
            env=env,
            check=True,
            capture_output=True,
        )
        return self.git("rev-parse", "HEAD")


def legacy_article(sources: list[str], title: str = "Paged attention") -> str:
    """Return an article in the pre-OKF shape: `source_files`, no `sources`."""
    listed = "".join(f"  - {s}\n" for s in sources)
    return (
        f"---\ntype: concept\ntitle: {title}\nsource_files:\n{listed}---\n\n"
        f"# {title}\n\nBody text.\n"
    )


def source_file(title: str) -> str:
    return f"# {title}\n\nSource content.\n"


@pytest.fixture
def bundle(tmp_path, monkeypatch) -> GitBundle:
    monkeypatch.chdir(tmp_path)
    return GitBundle(tmp_path)
