"""``kb-read``: print one wiki article from any bundle in scope.

This duplicates Claude Code's own ``Read`` tool on purpose. Permissions are
granted per binary, so ``Bash(kb-read *)`` lets an agent crawl a wiki outside
its project without a permission prompt on every hop. The price of that grant
is that ``kb-read`` must not become a general file reader: it resolves paths
only against the wikis in scope, follows symlinks before checking containment,
and refuses anything that is not a markdown file inside one of them.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Annotated

import typer

from okf_kb import config, frontmatter
from okf_kb.graph import canonicalise

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

app = typer.Typer(help="Print a wiki article from any knowledge base in scope.")

#: A markdown ATX heading: its hashes, then its text.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")

#: Opens or closes a fenced code block, inside which ``#`` is not a heading.
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


class ReadError(ValueError):
    """Raised when a path cannot be read from the wikis in scope."""


def resolve_readable(
    path: str,
    bundles: Sequence[config.Bundle],
) -> tuple[config.Bundle, Path]:
    """Find the one wiki file a path names among the bundles in scope.

    Args:
        path: An absolute, bundle-root-relative or wiki-relative path.
        bundles: The bundles in scope.

    Returns:
        The bundle and the resolved file.

    Raises:
        ReadError: If the path is not a markdown file inside any wiki in
            scope, or names one in more than one bundle.

    """
    matches: dict[Path, config.Bundle] = {}
    for bundle in bundles:
        wiki = bundle.config.wiki.resolve()
        resolved = canonicalise(path, wiki, bundle.config.root.resolve())
        if resolved is not None and resolved.is_file():
            matches.setdefault(resolved, bundle)

    if not matches:
        wikis = ", ".join(f"{b.name} ({b.config.wiki})" for b in bundles)
        msg = f"{path} is not a file inside any wiki in scope: {wikis}"
        raise ReadError(msg)
    if len(matches) > 1:
        names = ", ".join(b.name for b in matches.values())
        msg = f"{path} exists in more than one bundle ({names}); narrow with --kb"
        raise ReadError(msg)

    ((resolved, bundle),) = matches.items()
    if resolved.suffix != ".md":
        msg = f"{path} is not a markdown file; kb-read only prints wiki articles"
        raise ReadError(msg)
    return bundle, resolved


def section(text: str, heading: str) -> str:
    """Extract one section of a markdown document.

    Args:
        text: The document.
        heading: The heading line, such as ``## Sources``. Without leading
            hashes it matches a heading of that text at any level.

    Returns:
        The heading line and everything up to the next heading of the same or
        a higher level. Headings inside fenced code blocks are ignored.

    Raises:
        ReadError: If no heading matches; the message lists those present.

    """
    wanted = heading.strip()
    wanted_level = len(wanted) - len(wanted.lstrip("#"))
    wanted_text = wanted.lstrip("#").strip()

    lines = text.splitlines(keepends=True)
    present: list[str] = []
    start: int | None = None
    level = 0
    in_fence = False
    for number, line in enumerate(lines):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        match = None if in_fence else _HEADING_RE.match(line)
        if match is None:
            continue
        this_level, this_text = len(match.group(1)), match.group(2)
        if start is not None and this_level <= level:
            return "".join(lines[start:number])
        present.append(line.strip())
        if (
            start is None
            and this_text == wanted_text
            and wanted_level in {0, this_level}
        ):
            start, level = number, this_level

    if start is not None:
        return "".join(lines[start:])
    listing = "\n".join(f"  {h}" for h in present) or "  (none)"
    msg = f"no heading {heading!r}; headings present:\n{listing}"
    raise ReadError(msg)


def _strip(text: str) -> str:
    """Drop the frontmatter block, leaving a malformed one in place.

    Args:
        text: The document.

    Returns:
        The body.

    """
    try:
        _, body = frontmatter.parse(text)
    except frontmatter.FrontmatterError:
        return text
    return body.lstrip("\n")


def read_article(
    path: str,
    bundles: Sequence[config.Bundle],
    heading: str | None = None,
    strip_frontmatter: bool = False,  # noqa: FBT001, FBT002
) -> tuple[config.Bundle, str, str]:
    """Read one wiki article, or one section of it, from the bundles in scope.

    Args:
        path: An absolute, bundle-root-relative or wiki-relative path.
        bundles: The bundles in scope.
        heading: If set, return only this section; see :func:`section`.
        strip_frontmatter: Drop the YAML frontmatter block.

    Returns:
        The bundle, the article's wiki-relative POSIX path, and its text.

    Raises:
        ReadError: If the path is refused, or the section does not exist.

    """
    bundle, resolved = resolve_readable(path, bundles)
    text = resolved.read_text(encoding="utf-8")
    if strip_frontmatter:
        text = _strip(text)
    if heading is not None:
        text = section(text, heading)
    rel = resolved.relative_to(bundle.config.wiki.resolve()).as_posix()
    return bundle, rel, text


@app.command()
def main(
    path: Annotated[
        str,
        typer.Argument(help="Article path: absolute, bundle- or wiki-relative."),
    ],
    heading: Annotated[
        str | None,
        typer.Option(
            "--section",
            help='Print only this section, e.g. "## Sources".',
        ),
    ] = None,
    strip_frontmatter: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--strip-frontmatter/--keep-frontmatter",
            help="Drop the YAML frontmatter block.",
        ),
    ] = False,
    kb: Annotated[
        list[str] | None,
        typer.Option(
            "--kb",
            help="Knowledge base to read from: a name, a path, or 'all'. Repeatable.",
        ),
    ] = None,
) -> None:
    """Print a wiki article, headed by its bundle and wiki-relative path.

    Raises:
        Exit: With status 1 when no bundle resolves, or the path is refused.

    """
    try:
        bundle, rel, text = read_article(
            path,
            config.resolve_roots(kb),
            heading,
            strip_frontmatter,
        )
    except (config.ConfigError, ReadError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"==> {bundle.name}: {rel} <==")
    typer.echo(text.rstrip("\n"))


if __name__ == "__main__":
    app()
