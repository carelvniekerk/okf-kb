"""Wiki statistics: article count, word count, link density, connectivity."""

from __future__ import annotations

import re

# Typer resolves these annotations at runtime to parse CLI arguments, so
# Path cannot move into a type-checking block.
from pathlib import Path  # noqa: TC003
from typing import Annotated
from urllib.parse import unquote

import typer

from okf_kb import config
from okf_kb.frontmatter import is_article

app = typer.Typer(help="Print statistics about the knowledge base wiki.")

#: Matches ``[label](target)``. Anchors and whitespace terminate the target, so
#: this stays in step with ``health.py``'s link scanner.
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)#\s]+)\)")


def _resolve_link(link: str, source_file: Path) -> Path:
    """Resolve a relative markdown link to an absolute path.

    Args:
        link: The raw link target as written in the markdown.
        source_file: The file the link appears in.

    Returns:
        The absolute path the link points at. Percent-encoding is decoded first,
        since wiki links to files with spaces are written encoded.

    """
    return (source_file.parent / unquote(link)).resolve()


def _internal_md_links(text: str) -> list[str]:
    """Extract internal markdown link targets that point at ``.md`` files."""
    return [
        target
        for _, target in LINK_RE.findall(text)
        if not target.startswith("http") and target.endswith(".md")
    ]


def compute_stats(wiki_dir: Path) -> dict:
    """Compute comprehensive statistics about the wiki.

    ``INDEX.md``, ``log.md``, and underscore-prefixed partials are not articles,
    so they are excluded from the counts and averages. They are still scanned
    for links, because a link from ``INDEX.md`` is what keeps an article from
    being an orphan.

    Args:
        wiki_dir: Path to the wiki directory.

    Returns:
        A mapping of statistics: article and word counts, link totals and
        averages, orphan articles, broken links, the most connected articles,
        and the per-article breakdown.

    """
    wiki_root = wiki_dir.resolve()
    md_files = sorted(wiki_dir.rglob("*.md"))
    article_paths = {f.resolve() for f in md_files if is_article(f)}

    articles: list[dict] = []
    outgoing: dict[Path, int] = {}
    total_words = 0
    total_links = 0
    broken_links: list[str] = []
    incoming_counts: dict[Path, int] = dict.fromkeys(article_paths, 0)

    for md_file in md_files:
        text = md_file.read_text(encoding="utf-8")
        rel_path = str(md_file.relative_to(wiki_dir))
        absolute = md_file.resolve()
        targets = _internal_md_links(text)

        for target in targets:
            resolved = _resolve_link(target, md_file)
            if not resolved.exists():
                broken_links.append(f"{rel_path} -> {target}")
            if resolved in incoming_counts:
                incoming_counts[resolved] += 1

        if absolute not in article_paths:
            continue

        words = len(text.split())
        total_words += words
        total_links += len(targets)
        outgoing[absolute] = len(targets)
        articles.append(
            {
                "path": rel_path,
                "words": words,
                "outgoing_links": len(targets),
            },
        )

    orphans = sorted(
        str(path.relative_to(wiki_root))
        for path, count in incoming_counts.items()
        if count == 0
    )

    # Most connected articles (by total links in + out)
    connectivity = {
        str(path.relative_to(wiki_root)): out + incoming_counts.get(path, 0)
        for path, out in outgoing.items()
    }
    most_connected = sorted(
        connectivity.items(),
        key=lambda x: x[1],
        reverse=True,
    )[:10]

    return {
        "article_count": len(articles),
        "total_words": total_words,
        "total_internal_links": total_links,
        "avg_words_per_article": round(total_words / max(len(articles), 1)),
        "avg_links_per_article": round(total_links / max(len(articles), 1), 1),
        "orphan_articles": orphans,
        "broken_links": broken_links,
        "most_connected": most_connected,
        "articles": sorted(articles, key=lambda a: a["words"], reverse=True),
    }


@app.command()
def main(
    wiki_dir: Annotated[
        Path | None,
        typer.Option(exists=True, help="Wiki directory. Defaults to the bundle's."),
    ] = None,
    json_output: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--json-output/--no-json-output", help="Output as JSON."),
    ] = False,
) -> None:
    """Print statistics about the knowledge base wiki."""
    stats = compute_stats(config.resolve_dir(wiki_dir, "wiki"))

    if json_output:
        import json  # noqa: PLC0415

        typer.echo(json.dumps(stats, indent=2))
    else:
        from rich.console import Console  # noqa: PLC0415
        from rich.table import Table  # noqa: PLC0415

        console = Console()

        console.print("\n[bold]Wiki Statistics[/bold]")
        console.print(f"  Articles:        {stats['article_count']}")
        console.print(f"  Total words:     {stats['total_words']:,}")
        console.print(f"  Avg words/article: {stats['avg_words_per_article']:,}")
        console.print(f"  Internal links:  {stats['total_internal_links']}")
        console.print(f"  Avg links/article: {stats['avg_links_per_article']}")
        console.print(f"  Orphan articles: {len(stats['orphan_articles'])}")
        console.print(f"  Broken links:    {len(stats['broken_links'])}")

        if stats["orphan_articles"]:
            console.print("\n[yellow]Orphans:[/yellow]")
            for o in stats["orphan_articles"]:
                console.print(f"  - {o}")

        if stats["broken_links"]:
            console.print("\n[red]Broken links:[/red]")
            for b in stats["broken_links"]:
                console.print(f"  - {b}")

        if stats["most_connected"]:
            console.print("\n[bold]Most connected articles:[/bold]")
            table = Table(show_header=True)
            table.add_column("Article")
            table.add_column("Links", justify="right")
            for path, count in stats["most_connected"]:
                table.add_row(path, str(count))
            console.print(table)


if __name__ == "__main__":
    app()
