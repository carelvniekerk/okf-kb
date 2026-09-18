"""Full-text BM25 search over one or more wikis, with tag and type filters.

Several bundles can be in scope at once. They are searched as one corpus with
one BM25 index rather than one index each merged afterwards, so document
frequencies are computed jointly and a score from one bundle is comparable
with a score from another.
"""

from __future__ import annotations

import re
from enum import StrEnum

# Typer resolves these annotations at runtime to parse CLI arguments, so
# Path cannot move into a type-checking block.
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Annotated, Any

import typer

from okf_kb import config, frontmatter
from okf_kb.frontmatter import is_article
from okf_kb.index_gen import split_emoji

if TYPE_CHECKING:
    from collections.abc import Sequence

app = typer.Typer(help="Search the knowledge base wiki.")


class Field(StrEnum):
    """Which part of each article BM25 indexes."""

    BODY = "body"
    TITLE = "title"


#: Frontmatter ``status`` value that marks an article as superseded.
DEPRECATED_STATUS = "deprecated"

#: Status assumed when an article declares none.
DEFAULT_STATUS = "stable"


def source_count(fm: dict[str, Any]) -> int:
    """Count the sources an article declares.

    The ``sources`` key carries a plain integer in the legacy shape and a list
    of source mappings in the OKF shape, so callers cannot assume either.

    Args:
        fm: The parsed frontmatter mapping.

    Returns:
        The number of declared sources, or ``0`` when the key is absent or of an
        unrecognised type.

    """
    sources = fm.get("sources")
    if isinstance(sources, bool):
        return 0
    if isinstance(sources, int):
        return sources
    if isinstance(sources, (list, tuple)):
        return len(sources)
    return 0


def _split(text: str) -> tuple[dict[str, Any], str]:
    """Split markdown into frontmatter and body, tolerating malformed blocks."""
    try:
        return frontmatter.parse(text)
    except frontmatter.FrontmatterError:
        return {}, text


def parse_frontmatter(text: str) -> dict:
    """Extract the search-relevant frontmatter fields from a markdown document.

    Args:
        text: The full contents of a markdown file.

    Returns:
        A mapping with ``tags`` (list of strings), ``type``, ``date_added``,
        ``sources`` (a count, see :func:`source_count`), and ``status``. A
        document with no parsable frontmatter yields empty/``None`` values and a
        source count of ``0``.

    """
    fm, _ = _split(text)

    raw_tags = fm.get("tags")
    if isinstance(raw_tags, str):
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    elif isinstance(raw_tags, (list, tuple)):
        tags = [str(t).strip() for t in raw_tags]
    else:
        tags = []

    article_type = fm.get("type")
    date_added = fm.get("date_added")
    status = fm.get("status") or DEFAULT_STATUS

    return {
        "tags": tags,
        "type": str(article_type) if article_type is not None else None,
        "date_added": str(date_added) if date_added is not None else None,
        "sources": source_count(fm),
        "status": str(status),
    }


def strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter from markdown text before indexing.

    Args:
        text: The full contents of a markdown file.

    Returns:
        The body with any leading frontmatter block removed.

    """
    _, body = _split(text)
    return body


def _display_fields(text: str, md_file: Path) -> tuple[str, str | None]:
    """Read the title and description an agent needs to judge a hit.

    Args:
        text: The full contents of the article.
        md_file: The article's path, whose stem stands in for a missing title.

    Returns:
        The title with any leading emoji removed, and the description or
        ``None``.

    """
    fm, _ = _split(text)
    title = fm.get("title")
    raw_title = title if isinstance(title, str) and title.strip() else md_file.stem
    description = fm.get("description")
    return (
        split_emoji(raw_title)[1],
        description.strip() if isinstance(description, str) else None,
    )


def load_documents(
    bundles: Sequence[config.Bundle],
) -> list[tuple[Path, str, str, dict]]:
    """Load every article of every bundle in scope, parsing frontmatter.

    Args:
        bundles: The bundles to read.

    Returns:
        One ``(path, bundle name, raw text, metadata)`` tuple per article, in
        bundle order and then path order. The metadata is
        :func:`parse_frontmatter`'s, plus ``rel`` (the wiki-relative POSIX
        path), ``title`` and ``description``.

    """
    docs = []
    for bundle in bundles:
        wiki = bundle.config.wiki
        for md_file in sorted(wiki.rglob("*.md")):
            if not is_article(md_file):
                continue
            text = md_file.read_text(encoding="utf-8")
            meta = parse_frontmatter(text)
            meta["rel"] = md_file.relative_to(wiki).as_posix()
            meta["title"], meta["description"] = _display_fields(text, md_file)
            docs.append((md_file, bundle.name, text, meta))
    return docs


def tokenise(text: str) -> list[str]:
    """Simple whitespace + punctuation tokeniser."""  # noqa: D401
    return re.findall(r"\w+", text.lower())


def search(  # noqa: PLR0913, PLR0917
    query: str,
    bundles: Sequence[config.Bundle],
    top_k: int = 5,
    filter_tag: str | None = None,
    filter_type: str | None = None,
    include_deprecated: bool = False,  # noqa: FBT001, FBT002
    fields: Field = Field.BODY,
) -> list[dict]:
    """Search the wikis in scope and return ranked results with snippets.

    Args:
        query: Search query string.
        bundles: The bundles to search, ranked together as one corpus.
        top_k: Maximum number of results to return.
        filter_tag: If set, only return articles that include this tag.
        filter_type: If set, only return articles of this type.
        include_deprecated: If ``True``, keep articles whose frontmatter marks
            them ``status: deprecated``. Articles with no ``status`` are treated
            as stable and are always returned.
        fields: Index the article body, or only its title as a cheap first
            probe. The snippet always comes from the body.

    Returns:
        List of result dicts with path, bundle, rel, title, description,
        score, snippet, tags, type, date_added, sources, and status.

    """
    from rank_bm25 import BM25Okapi  # noqa: PLC0415

    all_docs = load_documents(bundles)
    if not all_docs:
        return []

    # Apply tag/type/status filters
    docs = []
    for path, bundle, text, meta in all_docs:
        if filter_tag and filter_tag not in meta["tags"]:
            continue
        if filter_type and meta["type"] != filter_type:
            continue
        if not include_deprecated and meta["status"] == DEPRECATED_STATUS:
            continue
        docs.append((path, bundle, text, meta))

    if not docs:
        return []

    # Build BM25 index on frontmatter-stripped text, or on titles alone
    corpus = [
        tokenise(meta["title"] if fields == Field.TITLE else strip_frontmatter(text))
        for _, _, text, meta in docs
    ]
    bm25 = BM25Okapi(corpus)

    query_tokens = tokenise(query)
    scores = bm25.get_scores(query_tokens)

    ranked = sorted(
        zip(scores, docs, strict=True),
        key=lambda x: x[0],
        reverse=True,
    )

    results = []
    for score, (path, bundle, text, meta) in ranked[:top_k]:
        if score <= 0:
            break
        snippet = _extract_snippet(strip_frontmatter(text), query_tokens)
        results.append(
            {
                "path": str(path),
                "bundle": bundle,
                "rel": meta["rel"],
                "title": meta["title"],
                "description": meta["description"],
                "score": round(score, 3),
                "snippet": snippet,
                "tags": meta["tags"],
                "type": meta["type"],
                "date_added": meta["date_added"],
                "sources": meta["sources"],
                "status": meta["status"],
            },
        )

    return results


def _extract_snippet(
    text: str,
    query_tokens: list[str],
    context_chars: int = 200,
) -> str:
    """Extract the most relevant snippet from the text."""
    text_lower = text.lower()
    best_pos = 0
    best_count = 0

    window = context_chars * 2
    for i in range(0, len(text_lower), context_chars // 2):
        chunk = text_lower[i : i + window]
        count = sum(1 for token in query_tokens if token in chunk)
        if count > best_count:
            best_count = count
            best_pos = i

    start = max(0, best_pos - 50)
    end = min(len(text), best_pos + context_chars)
    snippet = text[start:end].strip()

    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."

    return snippet


@app.command()
def main(  # noqa: PLR0913, PLR0917
    query: str,
    wiki_dir: Annotated[
        Path | None,
        typer.Option(exists=True, help="Wiki directory. Defaults to the bundle's."),
    ] = None,
    top_k: Annotated[int, typer.Option(help="Number of results to return.")] = 5,
    tag: Annotated[
        str | None,
        typer.Option(help="Filter results to articles with this tag."),
    ] = None,
    article_type: Annotated[
        str | None,
        typer.Option(
            "--type",
            help="Filter results to articles of this type (paper-summary, concept, etc.).",  # noqa: E501
        ),
    ] = None,
    include_deprecated: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--include-deprecated/--no-include-deprecated",
            help="Include articles marked `status: deprecated`.",
        ),
    ] = False,
    json_output: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--json-output/--no-json-output",
            help="Output as JSON (for LLM tool use).",
        ),
    ] = False,
    kb: Annotated[
        list[str] | None,
        typer.Option(
            "--kb",
            help="Knowledge base to search: a name, a path, or 'all'. Repeatable. "
            "Defaults to the enclosing bundle, the project's .okf-kb.toml, or "
            "the user config's default.",
        ),
    ] = None,
    fields: Annotated[
        Field,
        typer.Option(help="Index article bodies, or titles only as a cheap probe."),
    ] = Field.BODY,
) -> None:
    """Search the knowledge base wiki with optional tag/type filtering.

    Raises:
        BadParameter: If ``--wiki-dir`` and ``--kb`` are both given.
        Exit: With status 1 when no knowledge base can be resolved.

    """
    if wiki_dir is not None and kb:
        msg = "--wiki-dir and --kb are mutually exclusive"
        raise typer.BadParameter(msg)
    try:
        bundles = (
            (config.bundle_for_wiki(wiki_dir),)
            if wiki_dir is not None
            else config.resolve_roots(kb)
        )
    except config.ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc

    results = search(
        query,
        bundles,
        top_k,
        filter_tag=tag,
        filter_type=article_type,
        include_deprecated=include_deprecated,
        fields=fields,
    )

    if json_output:
        import json  # noqa: PLC0415

        typer.echo(json.dumps(results, indent=2))
    else:
        _print_results(
            results,
            multi_bundle=len(bundles) > 1,
            tag=tag,
            article_type=article_type,
        )


def _print_results(
    results: list[dict],
    *,
    multi_bundle: bool,
    tag: str | None,
    article_type: str | None,
) -> None:
    """Render search results as rich panels.

    Args:
        results: What :func:`search` returned.
        multi_bundle: Whether to prefix each path with its bundle's name.
        tag: The tag filter, echoed when nothing matched.
        article_type: The type filter, echoed when nothing matched.

    """
    from rich.console import Console  # noqa: PLC0415
    from rich.markup import escape  # noqa: PLC0415
    from rich.panel import Panel  # noqa: PLC0415
    from rich.text import Text  # noqa: PLC0415

    console = Console()

    if not results:
        msg = "No results found."
        if tag:
            msg += f" (tag filter: {tag})"
        if article_type:
            msg += f" (type filter: {article_type})"
        console.print(f"[yellow]{msg}[/yellow]")
        return

    for result in results:
        meta_parts = []
        if result["type"]:
            meta_parts.append(f"[cyan]{result['type']}[/cyan]")
        if result["date_added"]:
            meta_parts.append(f"[dim]{result['date_added']}[/dim]")
        if result["status"] == DEPRECATED_STATUS:
            meta_parts.append("[red]deprecated[/red]")
        if result["tags"]:
            tags_str = " ".join(f"[green]#{t}[/green]" for t in result["tags"])
            meta_parts.append(tags_str)

        meta_line = Text.from_markup("  ".join(meta_parts)) if meta_parts else Text("")

        label = result["path"]
        if multi_bundle:
            label = f"[{result['bundle']}] {label}"
        console.print(
            Panel(
                f"[dim]{result['snippet']}[/dim]\n{meta_line}",
                title=f"[bold]{escape(label)}[/bold]",
                subtitle=f"score: {result['score']}",
            ),
        )


if __name__ == "__main__":
    app()
