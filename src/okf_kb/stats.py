"""Wiki statistics: article count, word count, link density, connectivity."""

from __future__ import annotations

# Typer resolves these annotations at runtime to parse CLI arguments, so
# Path cannot move into a type-checking block.
from pathlib import Path  # noqa: TC003
from typing import Annotated

import typer

from okf_kb import config
from okf_kb.graph import Graph

app = typer.Typer(help="Print statistics about the knowledge base wiki.")


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
    graph = Graph.from_wiki(wiki_dir)
    nodes = [node for node in graph.nodes() if not node.is_index]

    articles: list[dict] = []
    total_words = 0
    for node in nodes:
        words = len(node.path.read_text(encoding="utf-8").split())
        total_words += words
        articles.append(
            {
                "path": str(node.rel),
                "words": words,
                "outgoing_links": len(node.out),
            },
        )
    total_links = sum(len(node.out) for node in nodes)

    # Most connected articles (by total links in + out)
    connectivity = {str(node.rel): len(node.out) + len(node.inbound) for node in nodes}
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
        "orphan_articles": [str(node.rel) for node in graph.orphans()],
        "broken_links": [
            f"{source.relative_to(graph.wiki)} -> {raw}"
            for source, raw in graph.broken()
        ],
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
