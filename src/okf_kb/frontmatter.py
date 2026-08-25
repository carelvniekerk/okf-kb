"""Shared YAML frontmatter parsing and serialisation for the knowledge base.

This module is the single place where frontmatter is read and written.
Every other tool must go through it rather than hand-rolling regexes.

The previous regex-based parsers could not represent nested structures, which
blocks the OKF v0.2 ``sources`` provenance family (a list of mappings). They
also disagreed with one another on whitespace and quoting, so the same article
parsed differently depending on which tool read it.

Round-trip fidelity is deliberate but partial: key order, unicode, bare dates
and the inline ``tags`` flow style are preserved, but comments are not. YAML
comments are not representable in the parsed mapping, so anything that must
survive a rewrite belongs in a key, not a comment.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path

type Frontmatter = dict[str, Any]

DELIMITER = "---"

#: Keys serialised as an inline flow sequence (``[a, b, c]``) rather than a
#: block list. Matches the existing hand-written convention in ``wiki/`` and in
#: the meeting notes under ``raw/``, whose ``attendees`` lists are written
#: inline. Keeping them inline means rewriting frontmatter does not churn every
#: meeting note into a block list.
FLOW_SEQUENCE_KEYS: frozenset[str] = frozenset({"tags", "attendees"})

#: Keys whose scalar value must always be quoted, because YAML would otherwise
#: coerce them to a non-string type. ``arxiv: 2104.09864`` parses as a float and
#: silently loses its identity as an identifier.
FORCE_QUOTED_KEYS: frozenset[str] = frozenset({"arxiv", "okf_version", "kb_format"})


#: Structural files reserved by OKF (§8, §9). They carry no frontmatter and are
#: not concepts, so every article-level check must skip them.
RESERVED_FILENAMES: frozenset[str] = frozenset({"INDEX.md", "log.md"})


class FrontmatterError(ValueError):
    """Raised when a frontmatter block is present but cannot be parsed."""


def is_article(path: Path) -> bool:
    """Whether a wiki file counts as an article.

    The single exclusion rule shared by every tool, so they cannot drift into
    disagreeing about what the wiki contains — they previously did, which is why
    ``kb-stats`` reported 29 articles where ``kb-health`` saw 27.

    Args:
        path: Path to a file inside the wiki directory.

    Returns:
        ``True`` for markdown files other than the reserved structural files
        (``INDEX.md``, ``log.md``) and partials (names beginning with ``_``).

    """
    return (
        path.suffix == ".md"
        and path.name not in RESERVED_FILENAMES
        and not path.name.startswith("_")
    )


class _FlowList(list):
    """A list marked for inline flow-style serialisation."""


class _QuotedStr(str):
    """A string marked for forced double-quoted serialisation."""

    __slots__ = ()


class _Dumper(yaml.SafeDumper):
    """SafeDumper that preserves the knowledge base's formatting conventions."""

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:  # noqa: FBT001, FBT002, ARG002
        """Indent block sequences under their parent key.

        PyYAML defaults to writing list items flush with the parent key, which
        is legal YAML but does not match the existing hand-written articles.
        """
        return super().increase_indent(flow=flow, indentless=False)


_Dumper.add_representer(
    _FlowList,
    lambda dumper, data: dumper.represent_sequence(
        "tag:yaml.org,2002:seq",
        data,
        flow_style=True,
    ),
)
_Dumper.add_representer(
    _QuotedStr,
    lambda dumper, data: dumper.represent_scalar(
        "tag:yaml.org,2002:str",
        data,
        style='"',
    ),
)


@dataclass
class Document:
    """A markdown document split into its frontmatter and body."""

    frontmatter: Frontmatter = field(default_factory=dict)
    body: str = ""
    path: Path | None = None

    @property
    def has_frontmatter(self) -> bool:
        """Whether the document carried a frontmatter block."""
        return bool(self.frontmatter)

    def to_text(self) -> str:
        """Serialise back to full markdown text."""
        return dumps(self.frontmatter, self.body)


def _split(text: str) -> tuple[str | None, str]:
    """Split raw text into the frontmatter block and the body.

    Returns ``(None, text)`` when no leading frontmatter delimiter is present.
    """
    if not text.startswith(DELIMITER):
        return None, text

    lines = text.split("\n")
    # The opening delimiter must be a line of its own, not e.g. a `---` rule
    # immediately followed by content.
    if lines[0].strip() != DELIMITER:
        return None, text

    for index in range(1, len(lines)):
        if lines[index].strip() == DELIMITER:
            block = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1 :])
            return block, body

    # An opening delimiter with no closing delimiter is malformed, not absent.
    msg = "unterminated frontmatter block: no closing '---' found"
    raise FrontmatterError(msg)


def parse(text: str) -> tuple[Frontmatter, str]:
    """Parse markdown text into ``(frontmatter, body)``.

    Args:
        text: The full contents of a markdown file.

    Returns:
        A tuple of the parsed frontmatter mapping and the remaining body. When
        the document has no frontmatter block, the mapping is empty and the body
        is the input unchanged.

    Raises:
        FrontmatterError: If a frontmatter block is present but is not valid
            YAML, or does not parse to a mapping, or is unterminated.

    """
    block, body = _split(text)
    if block is None:
        return {}, body

    if not block.strip():
        return {}, body

    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        msg = f"invalid YAML in frontmatter: {exc}"
        raise FrontmatterError(msg) from exc

    if data is None:
        return {}, body
    if not isinstance(data, dict):
        msg = f"frontmatter must be a mapping, got {type(data).__name__}"
        raise FrontmatterError(msg)

    return data, body


def _prepare(value: Any, key: str | None = None) -> Any:  # noqa: ANN401
    """Recursively mark values for style-preserving serialisation."""
    if key in FORCE_QUOTED_KEYS and isinstance(value, str):
        return _QuotedStr(value)
    if isinstance(value, dict):
        return {k: _prepare(v, k) for k, v in value.items()}
    if isinstance(value, list):
        items = [_prepare(item) for item in value]
        return _FlowList(items) if key in FLOW_SEQUENCE_KEYS else items
    return value


def dumps(frontmatter: Frontmatter, body: str) -> str:
    """Serialise frontmatter and body back into markdown text.

    Args:
        frontmatter: The frontmatter mapping. An empty mapping emits no block.
        body: The document body, excluding any frontmatter.

    Returns:
        The full markdown text, with a trailing newline.

    """
    if not frontmatter:
        return body

    prepared = {key: _prepare(value, key) for key, value in frontmatter.items()}
    block = yaml.dump(
        prepared,
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10**6,
    ).rstrip("\n")

    return f"{DELIMITER}\n{block}\n{DELIMITER}\n{body}"


def load(path: Path) -> Document:
    """Read and parse a markdown file.

    Args:
        path: Path to the markdown file.

    Returns:
        The parsed document, with ``path`` populated.

    Raises:
        FrontmatterError: If the frontmatter block is malformed. The message is
            prefixed with the file path, since callers typically iterate over
            many files and need to know which one failed.

    """
    text = path.read_text(encoding="utf-8")
    try:
        frontmatter, body = parse(text)
    except FrontmatterError as exc:
        msg = f"{path}: {exc}"
        raise FrontmatterError(msg) from exc
    return Document(frontmatter=frontmatter, body=body, path=path)


def save(document: Document, path: Path | None = None) -> None:
    """Write a document back to disk.

    Args:
        document: The document to write.
        path: Target path. Defaults to the document's own ``path``.

    Raises:
        ValueError: If no path is available.

    """
    target = path or document.path
    if target is None:
        msg = "no path given and document has no path of its own"
        raise ValueError(msg)
    target.write_text(document.to_text(), encoding="utf-8")


def as_date(value: Any) -> _dt.date | None:  # noqa: ANN401
    """Coerce a frontmatter value to a date.

    YAML parses bare ``YYYY-MM-DD`` into ``datetime.date`` but quoted values
    stay strings, so callers cannot assume either.

    Args:
        value: The raw frontmatter value.

    Returns:
        The corresponding date, or ``None`` if the value is absent or not a
        recognisable date.

    """
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def source_resources(frontmatter: Frontmatter) -> list[str]:
    """Extract source paths, accepting both the OKF and legacy shapes.

    Reads OKF ``sources`` (a list of mappings with ``resource``) when present,
    and otherwise falls back to the legacy ``source_files`` string list. This
    lets tooling migrate ahead of the articles.

    Args:
        frontmatter: The parsed frontmatter mapping.

    Returns:
        Source paths in declaration order. Entries without a ``resource`` key
        are skipped.

    """
    sources = frontmatter.get("sources")
    if isinstance(sources, list):
        resources: list[str] = []
        for entry in sources:
            if isinstance(entry, dict) and entry.get("resource"):
                resources.append(str(entry["resource"]))
            elif isinstance(entry, str):
                resources.append(entry)
        return resources

    legacy = frontmatter.get("source_files")
    if isinstance(legacy, list):
        return [str(item) for item in legacy]
    return []
