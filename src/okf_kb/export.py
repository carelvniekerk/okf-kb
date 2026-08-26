"""Export wiki content to other formats: Marp slides, or the wiki as one file."""

from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(help="Export tools for the knowledge base.")


@app.command()
def marp(
    article: Annotated[
        Path,
        typer.Argument(exists=True, help="Wiki article to convert."),
    ],
    output: Annotated[Path | None, typer.Option(help="Output Marp file.")] = None,
    theme: Annotated[str, typer.Option(help="Marp theme.")] = "default",
) -> None:
    """Convert a wiki article into a Marp slide deck.

    Each H2 section becomes a slide.
    """
    if output is None:
        output = article.with_suffix(".marp.md")

    text = article.read_text(encoding="utf-8")
    lines = text.strip().split("\n")

    slides = []
    slides.append("---")
    slides.append("marp: true")
    slides.append(f"theme: {theme}")
    slides.append("paginate: true")
    slides.append("---")
    slides.append("")

    for line in lines:
        if line.startswith("## "):
            # New slide
            slides.append("---")
            slides.append("")
        slides.append(line)

    output.write_text("\n".join(slides) + "\n", encoding="utf-8")
    typer.echo(f"Created Marp deck: {output}")


@app.command()
def consolidate(
    wiki_dir: Annotated[Path, typer.Option(exists=True, help="Wiki directory.")] = Path(
        "wiki",
    ),
    output: Annotated[Path, typer.Option(help="Output file.")] = Path("wiki-export.md"),
) -> None:
    """Consolidate the entire wiki into a single markdown file.

    Useful for feeding the full wiki into an LLM context window or for printing.
    """
    index_path = wiki_dir / "INDEX.md"
    if not index_path.exists():
        typer.echo("[ERROR] wiki/INDEX.md not found.")
        raise typer.Exit(1)

    md_files = sorted(wiki_dir.rglob("*.md"))
    parts = []

    # INDEX first
    parts.append(index_path.read_text(encoding="utf-8"))
    parts.append("\n---\n")

    for md_file in md_files:
        if md_file == index_path:
            continue
        if md_file.name.startswith("_"):
            continue  # Skip health reports etc.

        rel = md_file.relative_to(wiki_dir)
        text = md_file.read_text(encoding="utf-8")
        parts.append(f"\n<!-- source: {rel} -->\n")
        parts.append(text)
        parts.append("\n---\n")

    output.write_text("\n".join(parts), encoding="utf-8")
    typer.echo(f"Consolidated {len(md_files)} articles into {output}")


if __name__ == "__main__":
    app()
