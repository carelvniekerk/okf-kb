"""Ingestion helpers.

Download images, extract PDF text, convert HTML to markdown,
fetch arXiv papers, and find new handwritten notes for transcription.
"""

import os
import re
from pathlib import Path
from typing import Annotated

import typer

from okf_kb import config, extras

app = typer.Typer(help="Ingestion tools for the knowledge base.")


def main() -> None:
    """Run the CLI, reporting a missing extra instead of raising a traceback.

    Typer lets unknown exceptions escape as tracebacks, which buries the
    install command under a stack the user has no use for.
    """
    try:
        app()
    except extras.MissingExtraError as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(1) from exc


@app.command()
def download_images(
    markdown_file: Annotated[
        Path,
        typer.Argument(
            exists=True,
            help="Markdown file with external image references.",
        ),
    ],
    image_dir: Annotated[
        Path | None,
        typer.Option(
            help="Directory to save downloaded images. "
            "Defaults to raw/images/<markdown-stem>/.",
        ),
    ] = None,
) -> None:
    """Download all external images referenced in a markdown file to local storage.

    Images are saved to raw/images/<markdown-stem>/ by default (one subdirectory per
    source document). Rewrites image references to paths relative to the markdown file.
    """
    with extras.required("ingest"):
        import requests  # noqa: PLC0415

    resolved = markdown_file.resolve()
    if image_dir is None:
        image_dir = config.resolve_dir(None, "raw") / "images" / resolved.stem
    image_dir.mkdir(parents=True, exist_ok=True)

    text = resolved.read_text(encoding="utf-8")

    # Find all image references: ![alt](url)
    pattern = r"(!\[[^\]]*\])\((https?://[^)]+)\)"
    matches = re.findall(pattern, text)

    if not matches:
        typer.echo("No external images found.")
        return

    for alt_part, url in matches:
        # Derive a filename from the URL
        url_path = url.split("?")[0]  # Strip query params
        filename = Path(url_path).name
        if not filename or len(filename) > 100:  # noqa: PLR2004
            import hashlib  # noqa: PLC0415

            filename = hashlib.md5(url.encode()).hexdigest()[:12] + ".png"  # noqa: S324

        local_path = image_dir / filename

        if not local_path.exists():
            typer.echo(f"Downloading: {url} -> {local_path}")
            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                local_path.write_bytes(resp.content)
            except requests.RequestException as e:
                typer.echo(f"  [ERROR] Failed to download: {e}")
                continue
        else:
            typer.echo(f"Already exists: {local_path}")

        # Rewrite the reference as a path relative to the markdown file's
        # location. `Path.relative_to` cannot express "go up a level", so it
        # raises for the normal case of raw/clippings/x.md referencing
        # raw/images/x/ — os.path.relpath emits the `../` prefix instead.
        rel_image_path = os.path.relpath(local_path.resolve(), resolved.parent)
        text = text.replace(f"{alt_part}({url})", f"{alt_part}({rel_image_path})")

    resolved.write_text(text, encoding="utf-8")
    typer.echo(f"Updated image references in {markdown_file}")


@app.command()
def extract_pdf(
    pdf_file: Annotated[
        Path,
        typer.Argument(exists=True, help="PDF file to extract text from."),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            help="Output markdown file (default: same name with .md extension).",
        ),
    ] = None,
) -> None:
    """Extract text from a PDF and save as markdown."""
    with extras.required("ingest"):
        import fitz  # pymupdf  # noqa: PLC0415

    if output is None:
        output = pdf_file.with_suffix(".md")

    doc = fitz.open(pdf_file)
    lines = [f"# {pdf_file.stem}\n"]

    for page_num, page in enumerate(doc, 1):  # ty:ignore[invalid-argument-type]
        text = page.get_text()
        if text.strip():
            lines.append(f"\n## Page {page_num}\n")
            lines.append(text.strip())

    output.write_text("\n".join(lines), encoding="utf-8")
    typer.echo(f"Extracted {len(doc)} pages to {output}")


@app.command()
def html_to_md(
    html_file: Annotated[
        Path,
        typer.Argument(exists=True, help="HTML file to convert."),
    ],
    output: Annotated[Path | None, typer.Option(help="Output markdown file.")] = None,
) -> None:
    """Convert an HTML file to clean markdown."""
    with extras.required("ingest"):
        from markdownify import markdownify  # noqa: PLC0415

    if output is None:
        output = html_file.with_suffix(".md")

    html = html_file.read_text(encoding="utf-8")
    md = markdownify(html, heading_style="ATX", strip=["script", "style"])

    # Clean up excessive blank lines
    md = re.sub(r"\n{3,}", "\n\n", md)

    output.write_text(md.strip() + "\n", encoding="utf-8")
    typer.echo(f"Converted {html_file} to {output}")


@app.command()
def arxiv(  # noqa: C901, PLR0912, PLR0915
    arxiv_id: Annotated[
        str,
        typer.Argument(help="arXiv paper ID or URL (e.g. 2402.12345)."),
    ],
    papers_dir: Annotated[
        Path | None,
        typer.Option(help="Directory to save papers. Defaults to <raw>/papers."),
    ] = None,
    image_dir: Annotated[
        Path | None,
        typer.Option(help="Directory to save figures. Defaults to <raw>/images."),
    ] = None,
) -> None:
    """Fetch an arXiv paper by ID and convert to markdown.

    Tries ar5iv HTML first (cleaner output with equations), falls back to PDF extract.

    Examples:
        kb-ingest arxiv 2402.12345

        kb-ingest arxiv https://arxiv.org/abs/2402.12345

    """
    with extras.required("ingest"):
        import requests  # noqa: PLC0415

    raw = config.resolve_dir(None, "raw")
    papers_dir = papers_dir or raw / "papers"
    image_dir = image_dir or raw / "images"

    # Normalize: accept full URLs or bare IDs
    arxiv_id = arxiv_id.strip()
    for prefix in ["https://arxiv.org/abs/", "http://arxiv.org/abs/", "arxiv:"]:
        arxiv_id = arxiv_id.removeprefix(prefix)
    arxiv_id = arxiv_id.strip("/")

    papers_dir.mkdir(parents=True, exist_ok=True)
    # Images go in a subdirectory named after the paper ID
    paper_image_dir = image_dir / arxiv_id.replace("/", "-")
    paper_image_dir.mkdir(parents=True, exist_ok=True)

    md_output = papers_dir / f"{arxiv_id.replace('/', '-')}.md"
    pdf_output = papers_dir / f"{arxiv_id.replace('/', '-')}.pdf"

    if md_output.exists():
        typer.echo(f"Already ingested: {md_output}")
        return

    # Strategy 1: Try ar5iv HTML (much cleaner for equations and structure)
    ar5iv_url = f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}"
    typer.echo(f"Trying ar5iv HTML: {ar5iv_url}")

    try:
        resp = requests.get(ar5iv_url, timeout=60)
        if resp.status_code == 200 and len(resp.text) > 1000:  # noqa: PLR2004
            with extras.required("ingest"):
                from bs4 import BeautifulSoup  # noqa: PLC0415
                from markdownify import markdownify  # noqa: PLC0415

            soup = BeautifulSoup(resp.text, "html.parser")

            # Extract only the article body to avoid JS/nav/footer noise
            article = soup.find("article") or soup.find("main") or soup.body
            if article is None:
                raise ValueError("Could not locate article body in ar5iv HTML")  # noqa: EM101, TRY003

            # Resolve relative image src to absolute ar5iv URLs and download them
            ar5iv_base = "https://ar5iv.labs.arxiv.org"
            for img in article.find_all("img"):
                src = str(img.get("src", ""))
                if src.startswith("/"):
                    abs_url = ar5iv_base + src
                    url_path = src.split("?", maxsplit=1)[0]
                    filename = Path(url_path).name
                    if not filename or len(filename) > 100:  # noqa: PLR2004
                        import hashlib  # noqa: PLC0415

                        filename = (
                            hashlib.md5(abs_url.encode()).hexdigest()[:12] + ".png"  # noqa: S324
                        )
                    local_path = paper_image_dir / filename
                    if not local_path.exists():
                        typer.echo(f"Downloading figure: {abs_url}")
                        try:
                            img_resp = requests.get(abs_url, timeout=30)
                            img_resp.raise_for_status()
                            local_path.write_bytes(img_resp.content)
                        except requests.RequestException as e:
                            typer.echo(f"  [WARN] Could not download figure: {e}")
                            continue
                    # Rewrite src relative to the paper's location in raw/papers/
                    rel = Path("../images") / paper_image_dir.name / filename
                    img["src"] = str(rel)

            md = markdownify(
                str(article),
                heading_style="ATX",
                strip=["script", "style", "nav", "footer", "header"],
            )
            md = re.sub(r"\n{3,}", "\n\n", md)

            # Add metadata header
            header = f"# arXiv: {arxiv_id}\n\n"
            header += f"Source: https://arxiv.org/abs/{arxiv_id}\n\n---\n\n"

            md_output.write_text(header + md.strip() + "\n", encoding="utf-8")
            typer.echo(f"Saved ar5iv markdown: {md_output}")

            # Warn if conversion looks incomplete (very few headings)
            section_count = md.count("\n## ")
            if section_count < 3:  # noqa: PLR2004
                typer.echo(
                    f"[WARN] ar5iv output has only {section_count} section(s) — "
                    "conversion may be incomplete. Consider deleting and re-ingesting "
                    "via PDF fallback.",
                )
            return
        typer.echo(
            f"ar5iv returned status {resp.status_code}, falling back to PDF.",
        )
    except requests.RequestException as e:
        typer.echo(f"ar5iv fetch failed: {e}, falling back to PDF.")

    # Strategy 2: Fall back to PDF download + extraction
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    typer.echo(f"Downloading PDF: {pdf_url}")

    try:
        resp = requests.get(
            pdf_url,
            timeout=120,
            headers={"User-Agent": "knowledge-base-ingest/0.1"},
        )
        resp.raise_for_status()
        pdf_output.write_bytes(resp.content)
        typer.echo(f"Saved PDF: {pdf_output}")
    except requests.RequestException as e:
        typer.echo(f"[ERROR] PDF download failed: {e}")
        return

    # Extract text from PDF
    try:
        with extras.required("ingest"):
            import fitz  # noqa: PLC0415

        doc = fitz.open(pdf_output)
        lines = [f"# arXiv: {arxiv_id}\n\n"]
        lines.append(f"Source: https://arxiv.org/abs/{arxiv_id}\n\n---\n")

        for page_num, page in enumerate(doc, 1):  # ty:ignore[invalid-argument-type]
            text = page.get_text()
            if text.strip():
                lines.append(f"\n## Page {page_num}\n")
                lines.append(text.strip())

        md_output.write_text("\n".join(lines), encoding="utf-8")
        typer.echo(f"Extracted PDF to markdown: {md_output}")
    except extras.MissingExtraError as e:
        # Only reachable on a half-installed extra: requests comes from the
        # same one and is imported above. The PDF is on disk either way, so
        # report the gap rather than failing the whole ingest.
        typer.echo(f"[WARN] PDF saved but not extracted — {e}")


@app.command()
def list_untranscribed(
    handwritten_dir: Annotated[
        Path | None,
        typer.Option(help="Handwritten notes. Defaults to <raw>/handwritten."),
    ] = None,
    transcriptions_dir: Annotated[
        Path | None,
        typer.Option(help="Transcription output. Defaults to <raw>/transcriptions."),
    ] = None,
) -> None:
    """List handwritten notes that have not yet been transcribed.

    This is a helper for the agent — it prints the files that need transcription,
    which the agent then processes using vision.
    """
    raw = config.resolve_dir(None, "raw")
    handwritten_dir = handwritten_dir or raw / "handwritten"
    transcriptions_dir = transcriptions_dir or raw / "transcriptions"

    if not handwritten_dir.exists():
        typer.echo(f"Handwritten directory not found: {handwritten_dir}")
        typer.echo(
            "Create a symlink: ln -s /path/to/samsung/notes/exports raw/handwritten",
        )
        return

    transcriptions_dir.mkdir(parents=True, exist_ok=True)

    image_extensions = {".png", ".jpg", ".jpeg", ".pdf", ".webp"}
    source_files = [
        f
        for f in sorted(handwritten_dir.iterdir())
        if f.suffix.lower() in image_extensions and not f.name.startswith(".")
    ]

    existing_transcriptions = {
        f.stem for f in transcriptions_dir.iterdir() if f.suffix == ".md"
    }

    untranscribed = [f for f in source_files if f.stem not in existing_transcriptions]

    if not untranscribed:
        typer.echo("All handwritten notes have been transcribed.")
        return

    typer.echo(f"Found {len(untranscribed)} untranscribed notes:\n")
    for f in untranscribed:
        typer.echo(f"  {f}")

    typer.echo(f"\nTranscriptions will be saved to: {transcriptions_dir}/")


if __name__ == "__main__":
    app()
