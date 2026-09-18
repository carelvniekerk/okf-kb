"""The one markdown link scanner.

Wiki articles link to each other with relative ``[text](./path.md)`` links, and
those links are the actual graph of the wiki: the indexes only mirror the
directory layout. Three modules used to scan them with three copies of the same
regex, and the copies had already drifted apart on whether a non-``.md``
target counts. This module keeps both readings, under two names, so each caller
says which one it means.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import unquote

if TYPE_CHECKING:
    from pathlib import Path

#: Matches ``[label](target)``. The target may not contain ``#`` or whitespace,
#: so a link carrying an anchor or a title does not match at all. It also matches the
#: ``[alt](src)`` inside an image reference, which is what lets the broken-link
#: check validate image targets.
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)#\s]+)\)")

#: Prefix that marks a target as external rather than a path in the bundle.
_EXTERNAL_PREFIX = "http"


@dataclass(frozen=True)
class Link:
    """One internal link, as written and as resolved.

    Attributes:
        raw: The target exactly as written in the markdown, for messages.
        target: The absolute path the link points at.

    """

    raw: str
    target: Path


def resolve(link: str, source_file: Path) -> Path:
    """Resolve a relative markdown link to an absolute path.

    Args:
        link: The raw link target as written in the markdown.
        source_file: The file the link appears in.

    Returns:
        The absolute path the link points at. Percent-encoding is decoded first,
        since wiki links to files with spaces are written encoded.

    """
    return (source_file.parent / unquote(link)).resolve()


def targets(text: str) -> list[str]:
    """Extract every internal link target, whatever it points at.

    Args:
        text: Markdown text.

    Returns:
        Each non-``http`` target in document order, duplicates kept.

    """
    return [
        target
        for _, target in LINK_RE.findall(text)
        if not target.startswith(_EXTERNAL_PREFIX)
    ]


def internal_targets(text: str) -> list[str]:
    """Extract internal link targets that point at markdown files.

    Args:
        text: Markdown text.

    Returns:
        Each non-``http`` target ending in ``.md``, in document order,
        duplicates kept.

    """
    return [target for target in targets(text) if target.endswith(".md")]


def outgoing(md_file: Path) -> tuple[Link, ...]:
    """Read a markdown file and resolve its links to other markdown files.

    Args:
        md_file: The file to scan.

    Returns:
        One :class:`Link` per internal ``.md`` link, in document order,
        duplicates kept.

    """
    text = md_file.read_text(encoding="utf-8")
    return tuple(
        Link(raw=raw, target=resolve(raw, md_file)) for raw in internal_targets(text)
    )
