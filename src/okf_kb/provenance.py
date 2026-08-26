"""Source provenance tracking for the knowledge base.

Maps raw source files to wiki articles and vice versa, detects affected
articles when sources are deleted, and provides heuristic source classification.

Frontmatter is read through :mod:`okf_kb.frontmatter`, so declared
sources are picked up from both the legacy ``source_files`` list and the OKF
``sources`` list-of-mappings shape.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote

import typer
from rich.console import Console
from rich.table import Table

from okf_kb import config, frontmatter
from okf_kb.frontmatter import is_article

app = typer.Typer(help="Source provenance tracking for the knowledge base.")


def _raw_zone_name(explicit_wiki: Path | None = None) -> str:
    """Return the bundle's raw-zone directory name.

    Args:
        explicit_wiki: The ``--wiki-dir`` the caller passed, if any. When set,
            the command was pointed somewhere explicitly and may not be inside a
            bundle at all, so fall back to the conventional name.

    Returns:
        The configured raw directory's name, or ``"raw"`` outside a bundle.

    """
    if explicit_wiki is not None:
        return "raw"
    try:
        return config.load().raw.name
    except config.ConfigError:
        return "raw"


def _source_link_re(raw_name: str) -> re.Pattern[str]:
    """Build the pattern matching ## Sources links into the raw zone.

    The zone's directory name is configurable, so this cannot be a module
    constant: a bundle that calls its sources ``notes/`` would match nothing
    against a hardcoded ``raw/`` and read as having declared everything.

    Args:
        raw_name: Directory name of the raw zone, relative to the bundle root.

    Returns:
        A compiled pattern whose second group is the link target.

    """
    escaped = re.escape(raw_name)
    return re.compile(rf"\[([^\]]+)\]\(((?:\.\.\/)*{escaped}\/[^)]+)\)")


def _declared_sources(text: str) -> list[str]:
    """Extract the declared source paths from YAML frontmatter.

    Args:
        text: Full markdown text with frontmatter.

    Returns:
        List of raw/ paths declared in ``sources`` or ``source_files``, or an
        empty list when there are none or the frontmatter is malformed.

    """
    try:
        data, _ = frontmatter.parse(text)
    except frontmatter.FrontmatterError:
        return []
    return [item.strip() for item in frontmatter.source_resources(data)]


def _parse_source_links(
    text: str,
    article_path: Path,
    raw_name: str = "raw",
) -> list[str]:
    """Extract raw-zone source paths from the ## Sources section links.

    Falls back to this when source provenance is not declared in frontmatter.

    Args:
        text: Full markdown text.
        article_path: Path to the article file (for resolving relative links).
        raw_name: Directory name of the raw zone.

    Returns:
        Paths found in Sources section links, root-relative where possible.

    """
    pattern = _source_link_re(raw_name)
    sources: list[str] = []
    in_sources = False
    for line in text.splitlines():
        if line.startswith("## Sources"):
            in_sources = True
            continue
        if in_sources and line.startswith("## "):
            break
        if not in_sources:
            continue
        for match in pattern.finditer(line):
            raw_link = match.group(2)
            # Resolve relative path to get a normalized raw/ path
            resolved = (article_path.parent / unquote(raw_link)).resolve()
            try:
                rel = resolved.relative_to(Path.cwd())
                sources.append(str(rel))
            except ValueError:
                sources.append(str(resolved))
    return sources


def build_provenance_map(
    wiki_dir: Path,
    raw_name: str = "raw",
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Build bidirectional mapping between raw sources and wiki articles.

    Args:
        wiki_dir: Path to the wiki directory.
        raw_name: Directory name of the raw zone, for parsing body links.

    Returns:
        Tuple of (raw_to_wiki, wiki_to_raw) dicts.

    """
    raw_to_wiki: dict[str, list[str]] = {}
    wiki_to_raw: dict[str, list[str]] = {}
    for md_file in sorted(wiki_dir.rglob("*.md")):
        if not is_article(md_file):
            continue

        text = md_file.read_text(encoding="utf-8")
        article_path = str(md_file)

        # Try frontmatter first, fall back to Sources section links
        source_paths = _declared_sources(text)
        if not source_paths:
            source_paths = _parse_source_links(text, md_file, raw_name)

        if source_paths:
            wiki_to_raw[article_path] = source_paths
            for raw_path in source_paths:
                raw_to_wiki.setdefault(raw_path, []).append(article_path)

    return raw_to_wiki, wiki_to_raw


# -- Classification heuristics --

_MEETING_KEYWORDS = [
    "meeting",
    "standup",
    "stand-up",
    "sync",
    "minutes",
    "agenda",
    "action item",
    "attendees",
    "participants",
    "discussed",
    "next steps",
    "follow-up",
    "follow up",
]

_DISCUSSION_KEYWORDS = [
    "discussion",
    "debate",
    "consensus",
    "proposal",
    "pros and cons",
    "trade-off",
    "tradeoff",
    "alternative",
    "option a",
    "option b",
    "decided",
    "decision",
    "agreed",
    "disagreed",
    "argument",
]

_EXPERIMENT_KEYWORDS = [
    "experiment",
    "benchmark",
    "ablation",
    "results",
    "baseline",
    "accuracy",
    "precision",
    "recall",
    "f1",
    "perplexity",
    "throughput",
    "latency",
    "evaluation",
    "eval",
    "metric",
    "table",
    "comparison",
    "run",
    "trial",
    "hyperparameter",
    "epoch",
    "loss",
    "training loss",
    "validation",
]


def classify_source(text: str) -> tuple[str, float]:
    """Classify a source document by type using keyword heuristics.

    Args:
        text: Full text content of the source document.

    Returns:
        Tuple of (classification, confidence) where classification is one of
        'technical', 'discussion', 'experiment', 'meeting' and confidence
        is a float between 0 and 1.

    """
    text_lower = text.lower()
    word_count = max(len(text_lower.split()), 1)

    scores: dict[str, float] = {}

    for label, keywords in [
        ("meeting", _MEETING_KEYWORDS),
        ("discussion", _DISCUSSION_KEYWORDS),
        ("experiment", _EXPERIMENT_KEYWORDS),
    ]:
        hits = sum(text_lower.count(kw) for kw in keywords)
        # Normalize by document length to avoid bias toward long documents
        scores[label] = hits / (word_count**0.5)

    # Technical is the default — it wins if no other category scores high
    scores["technical"] = 0.1

    best_label = max(scores, key=scores.get)  # ty:ignore[no-matching-overload]
    best_score = scores[best_label]
    total = sum(scores.values())

    confidence = best_score / total if total > 0 else 0.0

    return best_label, round(min(confidence, 1.0), 2)


# -- CLI Commands --


@app.command("map")
def map_cmd(
    wiki_dir: Annotated[
        Path | None,
        typer.Option("--wiki-dir", help="Wiki directory. Defaults to the bundle's."),
    ] = None,
    json_output: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--json/--no-json", help="Output as JSON."),
    ] = False,
) -> None:
    """Show the bidirectional mapping between raw sources and wiki articles."""
    raw_name = _raw_zone_name(wiki_dir)
    wiki_dir = config.resolve_dir(wiki_dir, "wiki")
    raw_to_wiki, wiki_to_raw = build_provenance_map(wiki_dir, raw_name)

    if json_output:
        typer.echo(
            json.dumps(
                {"raw_to_wiki": raw_to_wiki, "wiki_to_raw": wiki_to_raw},
                indent=2,
            ),
        )
        return

    console = Console()

    if not raw_to_wiki:
        console.print("[yellow]No source mappings found.[/yellow]")
        return

    table = Table(title="Raw Source -> Wiki Articles")
    table.add_column("Raw Source", style="cyan")
    table.add_column("Wiki Articles", style="green")

    for raw_path in sorted(raw_to_wiki):
        articles = "\n".join(raw_to_wiki[raw_path])
        table.add_row(raw_path, articles)

    console.print(table)

    # Also show wiki articles with their source counts
    console.print()
    table2 = Table(title="Wiki Article -> Raw Sources")
    table2.add_column("Wiki Article", style="green")
    table2.add_column("Sources", style="cyan")
    table2.add_column("Count", style="yellow", justify="right")

    for wiki_path in sorted(wiki_to_raw):
        sources = "\n".join(wiki_to_raw[wiki_path])
        table2.add_row(wiki_path, sources, str(len(wiki_to_raw[wiki_path])))

    console.print(table2)


@app.command()
def affected(
    deleted: Annotated[
        list[str],
        typer.Argument(help="Deleted raw source file paths."),
    ],
    wiki_dir: Annotated[
        Path | None,
        typer.Option("--wiki-dir", help="Wiki directory. Defaults to the bundle's."),
    ] = None,
    json_output: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--json/--no-json", help="Output as JSON."),
    ] = False,
) -> None:
    """Report wiki articles affected by deleted raw sources."""
    raw_name = _raw_zone_name(wiki_dir)
    wiki_dir = config.resolve_dir(wiki_dir, "wiki")
    raw_to_wiki, wiki_to_raw = build_provenance_map(wiki_dir, raw_name)

    affected_articles: dict[str, dict] = {}

    for deleted_path in deleted:
        # Normalize path for matching
        normalized = str(Path(deleted_path))
        wiki_articles = raw_to_wiki.get(normalized, [])

        for article_path in wiki_articles:
            all_sources = wiki_to_raw.get(article_path, [])
            remaining = [s for s in all_sources if str(Path(s)) != normalized]

            if article_path not in affected_articles:
                affected_articles[article_path] = {
                    "deleted_sources": [],
                    "remaining_sources": remaining,
                    "remaining_count": len(remaining),
                    "is_orphan": len(remaining) == 0,
                }
            affected_articles[article_path]["deleted_sources"].append(normalized)

    if json_output:
        typer.echo(json.dumps(affected_articles, indent=2))
        return

    console = Console()

    if not affected_articles:
        console.print("[green]No wiki articles affected by these deletions.[/green]")
        return

    table = Table(title="Affected Wiki Articles")
    table.add_column("Article", style="green")
    table.add_column("Deleted Sources", style="red")
    table.add_column("Remaining", style="yellow", justify="right")
    table.add_column("Orphan?", style="bold red", justify="center")

    for article_path in sorted(affected_articles):
        info = affected_articles[article_path]
        table.add_row(
            article_path,
            "\n".join(info["deleted_sources"]),
            str(info["remaining_count"]),
            "YES" if info["is_orphan"] else "no",
        )

    console.print(table)


@app.command()
def classify(
    file: Annotated[Path, typer.Argument(help="Raw source file to classify.")],
    json_output: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--json/--no-json", help="Output as JSON."),
    ] = False,
) -> None:
    """Classify a raw source file by type."""
    if not file.exists():
        typer.echo(f"Error: {file} does not exist.", err=True)
        raise typer.Exit(1)

    text = file.read_text(encoding="utf-8")
    label, confidence = classify_source(text)

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "file": str(file),
                    "classification": label,
                    "confidence": confidence,
                },
            ),
        )
    else:
        console = Console()
        emoji = {
            "technical": "📘",
            "discussion": "💬",
            "experiment": "🧪",
            "meeting": "📋",
        }
        console.print(
            f"{emoji.get(label, '📄')} [bold]{label}[/bold] "
            f"(confidence: {confidence:.0%}) — {file}",
        )


@app.command()
def migrate(
    wiki_dir: Annotated[
        Path | None,
        typer.Option("--wiki-dir", help="Wiki directory. Defaults to the bundle's."),
    ] = None,
) -> None:
    """Report articles that declare no provenance in their frontmatter.

    Every article should carry an OKF ``sources`` array. Where one is missing
    but the body has a ``## Sources`` section, the links are parsed and printed
    as a starting point.

    Does not modify files. Full migration of an article to the OKF schema is
    :func:`okf_kb.okf.migrate`; this command only surfaces the gap.
    """
    cfg_wiki = config.resolve_dir(wiki_dir, "wiki")
    raw_name = _raw_zone_name(wiki_dir)
    wiki_dir = cfg_wiki
    console = Console()
    found_any = False
    undeclared: list[Path] = []

    for md_file in sorted(wiki_dir.rglob("*.md")):
        if not is_article(md_file):
            continue

        text = md_file.read_text(encoding="utf-8")
        existing = _declared_sources(text)

        if existing:
            continue  # Provenance already declared

        source_paths = _parse_source_links(text, md_file, raw_name)
        if not source_paths:
            undeclared.append(md_file)
            continue

        found_any = True
        rel = md_file.relative_to(Path.cwd()) if md_file.is_absolute() else md_file
        console.print(f"\n[bold cyan]{rel}[/bold cyan]")
        console.print("  Sources found in the body but absent from frontmatter:")
        for sp in source_paths:
            console.print(f"    - {sp}")

    if not found_any:
        console.print(
            "[green]No article has body sources missing from frontmatter.[/green]",
        )
    if undeclared:
        # Distinct from the line above: these declare nothing *and* have no
        # `## Sources` section to recover from, so migration cannot help them.
        # Reporting them as clean is how an adopted bundle looks finished when
        # none of its provenance has been written yet.
        console.print(
            f"\n[yellow]{len(undeclared)} article(s) declare no sources and have "
            f"no `## Sources` section to recover from:[/yellow]",
        )
        for md_file in undeclared:
            console.print(f"    - {md_file.name}")


if __name__ == "__main__":
    app()
