"""Ingestion helpers.

Download images, extract PDF text and figures, convert HTML to markdown, clip
web pages, fetch arXiv papers, and find new handwritten notes for transcription.

``convert`` turns a document of any supported format into markdown beside the
original, and ``list-unconverted`` finds what still needs converting. The
markdown records the original's SHA-256, so an edited original is noticed, and
a hand-written markdown file is never overwritten without ``--force``. PDFs and
HTML keep their own converters (PyMuPDF keeps figures, markdownify matches
``clip``), and every other supported format goes through the markitdown library
with no plugins and no external service, so nothing leaves the machine.
``list-unconverted`` needs no extra, so a core-only install can still find work.
"""

import base64
import datetime as dt
import hashlib
import importlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, NoReturn
from urllib.parse import urljoin

import typer

from okf_kb import config, extras, frontmatter, okf

if TYPE_CHECKING:
    from collections.abc import Callable

    import fitz

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


#: Embedded images narrower or shorter than this, in pixels, are skipped. Logos,
#: bullets and rule lines are embedded as images too, and a figure is never this
#: small.
MIN_FIGURE_PX = 64


def _pdf_markdown(
    doc: fitz.Document,
    header: list[str],
    image_dir: Path,
    md_dir: Path,
) -> str:
    """Render a PDF as markdown, saving its embedded figures beside the text.

    Each page's text becomes a ``## Page N`` section, followed by a reference to
    every figure first drawn on that page. Text extraction alone dropped every
    figure without a word, which left papers ingested from PDF citing figures
    the knowledge base did not have.

    Args:
        doc: An open ``fitz.Document``.
        header: Lines to put before the first page.
        image_dir: Where to save figures. Created only if there is one to save.
        md_dir: Directory of the markdown file, so image links resolve from it.

    Returns:
        The markdown text.

    """
    lines = list(header)
    seen: set[int] = set()
    saved = 0
    for page_num, page in enumerate(doc, 1):  # ty:ignore[invalid-argument-type]
        text = page.get_text()
        if text.strip():
            lines.append(f"\n## Page {page_num}\n")
            lines.append(text.strip())
        figure = 0
        for xref, *_ in page.get_images(full=True):
            if xref in seen:
                continue
            seen.add(xref)
            image = doc.extract_image(xref)
            if not image or min(image["width"], image["height"]) < MIN_FIGURE_PX:
                continue
            figure += 1
            image_dir.mkdir(parents=True, exist_ok=True)
            path = image_dir / f"page-{page_num:03d}-{figure}.{image['ext']}"
            path.write_bytes(image["image"])
            saved += 1
            rel = Path(os.path.relpath(path.resolve(), md_dir.resolve())).as_posix()
            lines.append(f"\n![Figure {figure}, page {page_num}]({rel})")
    if saved:
        typer.echo(f"Saved {saved} figure(s) to {image_dir}")
    return "\n".join(lines) + "\n"


def _pdf_to_markdown(
    pdf_file: Path,
    image_dir: Path,
    md_dir: Path,
) -> tuple[str, int]:
    """Open a PDF and render it with :func:`_pdf_markdown`.

    Args:
        pdf_file: The PDF to read.
        image_dir: Where to save its figures.
        md_dir: Directory of the markdown file, so image links resolve from it.

    Returns:
        The markdown text and the number of pages in the PDF.

    """
    with extras.required("ingest"):
        import fitz  # pymupdf  # noqa: PLC0415

    with fitz.open(pdf_file) as doc:
        md = _pdf_markdown(doc, [f"# {pdf_file.stem}\n"], image_dir, md_dir)
        return md, len(doc)


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
    image_dir: Annotated[
        Path | None,
        typer.Option(
            help="Directory for embedded figures. Defaults to <raw>/images/<stem>/.",
        ),
    ] = None,
) -> None:
    """Extract text and figures from a PDF and save as markdown."""
    if output is None:
        output = pdf_file.with_suffix(".md")
    if image_dir is None:
        image_dir = config.resolve_dir(None, "raw") / "images" / pdf_file.stem

    md, pages = _pdf_to_markdown(pdf_file, image_dir, output.parent)
    output.write_text(md, encoding="utf-8")
    typer.echo(f"Extracted {pages} pages to {output}")


def _slugify(text: str, max_length: int = 60) -> str:
    """Turn a page title into a filename stem.

    ``python-slugify`` belongs to the ``[video]`` extra, and a clipping must not
    need that, so this is the small ASCII subset ``clip`` needs.

    Args:
        text: The title.
        max_length: Longest slug to return, cut at a word boundary.

    Returns:
        Lowercase words joined by hyphens, or ``"clipping"`` if none remain.

    """
    words = re.findall(r"[a-z0-9]+", text.lower())
    slug = ""
    for word in words:
        candidate = f"{slug}-{word}" if slug else word
        if len(candidate) > max_length:
            break
        slug = candidate
    return slug or "clipping"


@app.command()
def clip(
    url: Annotated[str, typer.Argument(help="Web page to clip.")],
    slug: Annotated[
        str | None,
        typer.Option(help="Filename stem. Defaults to one derived from the title."),
    ] = None,
    images: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--images/--no-images",
            help="Download the page's images to <raw>/images/<slug>/.",
        ),
    ] = True,
) -> None:
    """Save a web page as markdown in <raw>/clippings/, verbatim.

    The page body is converted, not summarised: a clipping is a source, and
    every claim compiled from it is later verified against it. Navigation,
    headers, footers, scripts and forms are dropped. Relative image links are
    made absolute so they can be downloaded.

    Raises:
        typer.Exit: With code 1 when the page cannot be fetched or the clipping
            already exists.

    """
    with extras.required("ingest"):
        import requests  # noqa: PLC0415
        from bs4 import BeautifulSoup  # noqa: PLC0415
        from markdownify import markdownify  # noqa: PLC0415

    try:
        resp = requests.get(
            url,
            timeout=60,
            headers={"User-Agent": "knowledge-base-ingest/0.1"},
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        typer.echo(f"[ERROR] Could not fetch {url}: {e}", err=True)
        raise typer.Exit(1) from e

    soup = BeautifulSoup(resp.text, "html.parser")
    og_title = soup.find("meta", attrs={"property": "og:title"})
    title = (
        str(og_title.get("content", "")).strip()
        if og_title is not None
        else (soup.title.get_text(strip=True) if soup.title else "")
    ) or url
    author_tag = soup.find("meta", attrs={"name": "author"})
    author = str(author_tag.get("content", "")).strip() if author_tag else ""

    body = soup.find("article") or soup.find("main") or soup.body or soup
    for tag in body.find_all(
        ["script", "style", "nav", "header", "footer", "aside", "form"],
    ):
        tag.decompose()
    for img in body.find_all("img"):
        src = str(img.get("src", ""))
        if src and not src.startswith("data:"):
            img["src"] = urljoin(resp.url, src)

    md = markdownify(str(body), heading_style="ATX")
    md = re.sub(r"\n{3,}", "\n\n", md).strip()

    clippings = config.resolve_dir(None, "raw") / "clippings"
    clippings.mkdir(parents=True, exist_ok=True)
    output = clippings / f"{slug or _slugify(title)}.md"
    if output.exists():
        typer.echo(f"Already clipped: {output}", err=True)
        raise typer.Exit(1)

    meta: dict[str, Any] = {
        "type": "clipping",
        "title": title,
        "source_url": resp.url,
        "fetched": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if author:
        meta["author"] = author
    output.write_text(frontmatter.dumps(meta, f"# {title}\n\n{md}\n"), encoding="utf-8")
    typer.echo(f"Saved clipping: {output}")

    if images:
        download_images(markdown_file=output, image_dir=None)


def _html_to_markdown(html: str) -> str:
    """Convert HTML text to markdown, dropping scripts and styles.

    Args:
        html: The page source.

    Returns:
        The markdown, with runs of blank lines collapsed and one trailing newline.

    """
    with extras.required("ingest"):
        from markdownify import markdownify  # noqa: PLC0415

    md = markdownify(html, heading_style="ATX", strip=["script", "style"])
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


@app.command()
def html_to_md(
    html_file: Annotated[
        Path,
        typer.Argument(exists=True, help="HTML file to convert."),
    ],
    output: Annotated[Path | None, typer.Option(help="Output markdown file.")] = None,
) -> None:
    """Convert an HTML file to clean markdown."""
    if output is None:
        output = html_file.with_suffix(".md")

    md = _html_to_markdown(html_file.read_text(encoding="utf-8"))
    output.write_text(md, encoding="utf-8")
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
        header = [
            f"# arXiv: {arxiv_id}\n\n",
            f"Source: https://arxiv.org/abs/{arxiv_id}\n\n---\n",
        ]
        md = _pdf_markdown(doc, header, paper_image_dir, md_output.parent)
        md_output.write_text(md, encoding="utf-8")
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
            "Put scans or exports of handwritten notes there, or symlink the "
            f"folder your note app exports to: ln -s <export-dir> {handwritten_dir}",
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


#: Suffixes that go through markitdown, each with the modules that must import for
#: its converter to run. markitdown raises its own ``MissingDependencyException``
#: rather than an ``ImportError`` when a sub-extra's library is absent, which
#: ``extras.required`` would not translate, so ingest imports these first.
MARKITDOWN_MODULES: dict[str, tuple[str, ...]] = {
    ".docx": ("mammoth",),
    ".pptx": ("pptx",),
    ".xlsx": ("pandas", "openpyxl"),
    ".xls": ("pandas", "xlrd"),
    ".epub": (),
    ".msg": ("olefile",),
}
MARKITDOWN_SUFFIXES: frozenset[str] = frozenset(MARKITDOWN_MODULES)
HTML_SUFFIXES: frozenset[str] = frozenset({".html", ".htm"})
PDF_SUFFIX = ".pdf"

#: Document formats that no converter handles. They are reported and never
#: guessed at, because a wrong conversion would be cited as if it were the source.
UNSUPPORTED_SUFFIXES: frozenset[str] = frozenset(
    {".doc", ".ppt", ".rtf", ".odt", ".odp", ".ods", ".pages", ".key", ".numbers"},
)

_CONVERTIBLE_SUFFIXES = MARKITDOWN_SUFFIXES | HTML_SUFFIXES | {PDF_SUFFIX}

#: Raw-zone folders that ``list-unconverted`` leaves alone. ``transcribe`` owns
#: ``handwritten/``, and ``images/`` holds what conversions produce.
_SKIPPED_ZONES = ("handwritten", "images")

#: The groups ``list-unconverted`` reports, with what each one means.
_LISTING_GROUPS = {
    "missing": "no markdown yet",
    "stale": "changed since the last conversion",
    "unsupported": "no converter handles these formats",
    "orphaned": "markdown whose original no longer exists",
    "legacy": "markdown with no conversion record, reconvert with --force",
    "conflicting": "another original already owns the markdown file",
}

_DATA_URI_IMAGE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\(data:image/(?P<kind>[A-Za-z0-9.+-]+);base64,"
    r"(?P<data>[^)\s]+)\)",
)
_IMAGE_EXTENSIONS = {"jpeg": "jpg", "svg+xml": "svg", "tiff": "tif"}


def _fail(message: str) -> NoReturn:
    typer.echo(f"[ERROR] {message}", err=True)
    raise typer.Exit(1)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _smaller_side(data: bytes) -> int | None:
    """Read the shorter side of an image, or ``None`` if PyMuPDF cannot decode it."""
    with extras.required("ingest"):
        import fitz  # noqa: PLC0415

    try:
        pixmap = fitz.Pixmap(data)
    except fitz.mupdf.FzErrorBase, ValueError:
        # SVG, EMF and WMF are not raster formats, a corrupt image fails inside
        # MuPDF, and an empty payload raises ValueError. None of them is a reason
        # to drop an image the author embedded.
        return None
    return min(pixmap.width, pixmap.height)


def _extract_data_uri_images(text: str, image_dir: Path, md_dir: Path) -> str:
    """Save every base64 image in ``text`` to disk and link it by relative path.

    markitdown inlines Office images as data URIs, which would put megabytes of
    base64 into a raw file and make every diff unreadable. Images whose shorter
    side is under :data:`MIN_FIGURE_PX` are dropped, as for PDFs. An image whose
    size cannot be read is kept, with a warning.

    Args:
        text: Markdown holding ``![alt](data:image/<kind>;base64,...)`` links.
        image_dir: Where to save the images, as ``image-NNN.<ext>``. Created only
            if there is an image to save.
        md_dir: Directory of the markdown file, so links resolve from it.

    Returns:
        The markdown with each kept image linked relatively, and no blank-line runs.

    """
    position = 0
    saved = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal position, saved
        position += 1
        data = base64.b64decode(match["data"])
        side = _smaller_side(data)
        if side is None:
            typer.echo(
                f"[WARN] Could not read the size of image {position}, kept it.",
                err=True,
            )
        elif side < MIN_FIGURE_PX:
            return ""
        kind = match["kind"].lower()
        extension = _IMAGE_EXTENSIONS.get(
            kind,
            re.sub(r"\W", "", kind.removeprefix("x-")),
        )
        image_dir.mkdir(parents=True, exist_ok=True)
        path = image_dir / f"image-{position:03d}.{extension}"
        path.write_bytes(data)
        saved += 1
        rel = Path(os.path.relpath(path.resolve(), md_dir.resolve())).as_posix()
        alt = match["alt"] or f"Figure {position}"
        return f"![{alt}]({rel})"

    text = _DATA_URI_IMAGE.sub(replace, text)
    if saved:
        typer.echo(f"Saved {saved} image(s) to {image_dir}")
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def _markitdown_to_markdown(source: Path, image_dir: Path, md_dir: Path) -> str:
    """Convert an Office document, e-book or Outlook message with markitdown.

    Plugins are disabled and no ``llm_client`` or Document Intelligence endpoint
    is given, so the conversion runs locally and nothing leaves the machine.

    Args:
        source: The document to convert.
        image_dir: Where to save its images.
        md_dir: Directory of the markdown file, so image links resolve from it.

    Returns:
        The markdown text.

    Raises:
        typer.Exit: With code 1 when markitdown cannot read the file.

    """
    with extras.required("ingest"):
        for module in MARKITDOWN_MODULES[source.suffix.lower()]:
            importlib.import_module(module)
        from markitdown import (  # noqa: PLC0415
            FileConversionException,
            MarkItDown,
            UnsupportedFormatException,
        )

    try:
        result = MarkItDown(enable_plugins=False).convert(
            source,
            keep_data_uris=True,
        )
    except (FileConversionException, UnsupportedFormatException) as exc:
        _fail(f"Could not convert {source}: {exc}")
    return _extract_data_uri_images(result.text_content, image_dir, md_dir)


def _convert_pdf(source: Path, image_dir: Path, md_dir: Path) -> str:
    return _pdf_to_markdown(source, image_dir, md_dir)[0]


def _convert_html(source: Path, _image_dir: Path, _md_dir: Path) -> str:
    return _html_to_markdown(source.read_text(encoding="utf-8"))


#: Converter name and function for each suffix, taking ``(original, image_dir,
#: md_dir)`` and returning the markdown body. The name goes into ``converter:``.
_CONVERTERS: dict[str, tuple[str, Callable[[Path, Path, Path], str]]] = {
    PDF_SUFFIX: ("pymupdf", _convert_pdf),
    **dict.fromkeys(HTML_SUFFIXES, ("markdownify", _convert_html)),
    **dict.fromkeys(MARKITDOWN_SUFFIXES, ("markitdown", _markitdown_to_markdown)),
}


def _recorded_original(md: Path, meta: frontmatter.Frontmatter) -> Path | None:
    """Resolve the original a conversion names in ``converted_from``."""
    recorded = meta.get("converted_from")
    if not isinstance(recorded, str) or not recorded:
        return None
    return (md.parent / recorded).resolve()


def _frontmatter_of(md: Path) -> frontmatter.Frontmatter:
    """Read a file's frontmatter, naming a malformed block instead of failing.

    Listing must survive one bad file, so a malformed block is reported on stderr
    and read as no frontmatter, which makes the file ``legacy``.
    """
    try:
        return frontmatter.load(md).frontmatter
    except frontmatter.FrontmatterError as exc:
        typer.echo(f"[WARN] {exc}", err=True)
        return {}


def _classify(original: Path) -> str:
    """Say where an original stands against the markdown beside it.

    Returns:
        ``missing``, ``legacy``, ``conflicting``, ``stale`` or ``fresh``.

    """
    md = original.with_suffix(".md")
    if not md.exists():
        return "missing"
    meta = _frontmatter_of(md)
    recorded = _recorded_original(md, meta)
    if recorded is None:
        return "legacy"
    if recorded != original.resolve():
        return "conflicting"
    return "fresh" if meta.get("converted_sha256") == _sha256(original) else "stale"


def _git_files(raw: Path) -> list[Path] | None:
    """List tracked and untracked-but-not-ignored files under ``raw``.

    Returns:
        Paths relative to ``raw``, or ``None`` when ``raw`` is not in a git work
        tree or git is not installed.

    """
    try:
        # A fixed argument list with no user input, run in the raw directory.
        done = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],  # noqa: S607
            cwd=raw,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    if done.returncode != 0:
        return None
    return [Path(name) for name in done.stdout.decode().split("\0") if name]


def _raw_files(raw: Path) -> list[Path]:
    """List the files ``list-unconverted`` should consider, as absolute paths.

    Respects ``.gitignore`` by asking git, and outside a git work tree falls back
    to a plain walk. ``git ls-files --cached`` still names a tracked file that was
    deleted and not yet committed, so only paths that exist are kept, and that is
    what lets its markdown surface as orphaned. Dot-prefixed paths and the
    ``handwritten/`` and ``images/`` folders are skipped in both modes.
    """
    if not raw.is_dir():
        return []
    listed = _git_files(raw)
    if listed is None:
        typer.echo(
            "[NOTE] Not a git work tree, so .gitignore is not applied.",
            err=True,
        )
        listed = [path.relative_to(raw) for path in raw.rglob("*")]
    files = [
        raw / rel
        for rel in listed
        if rel.parts[0] not in _SKIPPED_ZONES
        and not any(part.startswith(".") for part in rel.parts)
        and (raw / rel).is_file()
    ]
    return sorted(set(files))


def _scan_unconverted(cfg: config.Config) -> dict[str, list[str]]:
    """Group the raw zone's documents by what conversion still owes them."""
    groups: dict[str, list[Path]] = {name: [] for name in _LISTING_GROUPS}
    for path in _raw_files(cfg.raw):
        suffix = path.suffix.lower()
        if suffix in _CONVERTIBLE_SUFFIXES:
            state = _classify(path)
            if state != "fresh":
                groups[state].append(path)
        elif suffix in UNSUPPORTED_SUFFIXES:
            groups["unsupported"].append(path)
        elif suffix == ".md":
            original = _recorded_original(path, _frontmatter_of(path))
            if original is not None and not original.exists():
                groups["orphaned"].append(path)
    return {
        name: sorted(cfg.relative(path).as_posix() for path in paths)
        for name, paths in groups.items()
    }


def _conversion_record(
    source: Path,
    output: Path,
    converter: str,
    digest: str,
) -> frontmatter.Frontmatter:
    """Say which bytes a markdown file was converted from, and how and when.

    Args:
        source: The original document.
        output: The markdown file being written.
        converter: ``pymupdf``, ``markdownify`` or ``markitdown``.
        digest: SHA-256 of the original's bytes.

    Returns:
        The four ``converted*`` frontmatter keys.

    """
    return {
        "converted_from": Path(os.path.relpath(source, output.parent)).as_posix(),
        "converted_sha256": digest,
        "converter": converter,
        "converted": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _converted_frontmatter(
    existing: frontmatter.Frontmatter,
    record: frontmatter.Frontmatter,
    output: Path,
    body: str,
    cfg: config.Config,
) -> frontmatter.Frontmatter:
    """Build the frontmatter of a converted file.

    Keeps every key already on the file, so ``compile: false``, tags and a
    hand-edited title survive a reconversion, then lays the conversion record
    over it and lets :func:`okf.migrate_raw` add the raw identity keys that are
    missing. A new file has no git history to date it, so today stands in for
    ``date_added``.

    Args:
        existing: Frontmatter of the markdown being replaced, or empty.
        record: The conversion record from :func:`_conversion_record`.
        output: The markdown file being written.
        body: The converted markdown.
        cfg: The bundle's configuration.

    Returns:
        The merged frontmatter, with the raw identity keys first.

    """
    # migrate_raw's `title` argument overrides the body's heading, so it is only
    # passed when the body has none.
    title = None if okf.raw_title(body) else output.stem
    migrated = okf.migrate_raw(
        frontmatter.Document(
            frontmatter={**existing, **record},
            body=body,
            path=output,
        ),
        output.relative_to(cfg.root.resolve()).as_posix(),
        cfg.root,
        title=title,
        raw_name=cfg.relative(cfg.raw).as_posix(),
    )
    result = dict(migrated.frontmatter)
    result.setdefault("type", "document")
    result.setdefault("date_added", dt.datetime.now(dt.UTC).date())
    return okf.reorder_raw(result)


@app.command()
def convert(
    file: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, help="Document to convert."),
    ],
    output: Annotated[
        Path | None,
        typer.Option(help="Output markdown file (default: beside the original)."),
    ] = None,
    image_dir: Annotated[
        Path | None,
        typer.Option(
            help="Directory for embedded images. Defaults to <raw>/images/<stem>/.",
        ),
    ] = None,
    force: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--force",
            help="Replace markdown that has no conversion record or belongs to "
            "another original, keeping its frontmatter.",
        ),
    ] = False,
) -> None:
    """Convert a document to markdown beside the original, recording its hash.

    PDFs keep their figures, HTML is converted as ``html-to-md`` does, and Word,
    PowerPoint, Excel, EPUB and Outlook messages go through markitdown. The
    markdown names the original and its SHA-256, so a later run can tell whether
    it is up to date. A markdown file with no such record may be hand-written, so
    it is only replaced with ``--force``.

    Raises:
        typer.Exit: With code 1 for a markdown or unsupported file, or for an
            existing markdown file that is not this original's conversion.

    """
    cfg = config.load()
    source = file.resolve()
    suffix = source.suffix.lower()
    if suffix == ".md":
        _fail(f"{file} is already markdown.")
    if suffix not in _CONVERTERS:
        _fail(
            f"Cannot convert {suffix or 'a file with no suffix'}. "
            f"Supported suffixes: {', '.join(sorted(_CONVERTERS))}.",
        )

    output = (output or source.with_suffix(".md")).resolve()
    if not output.is_relative_to(cfg.root.resolve()):
        _fail(f"The output {output} is outside the bundle at {cfg.root}.")
    image_dir = image_dir or cfg.raw / "images" / source.stem
    digest = _sha256(source)

    existing: frontmatter.Frontmatter = {}
    if output.exists():
        try:
            existing = frontmatter.load(output).frontmatter
        except frontmatter.FrontmatterError as exc:
            _fail(f"{exc}. Repair or remove the file, then convert again.")
        recorded = _recorded_original(output, existing)
        if recorded is None and not force:
            _fail(
                f"{output} has no converted_from, so it may be hand-written. "
                "Pass --force to replace its body and keep its frontmatter.",
            )
        if recorded not in (None, source) and not force:
            _fail(
                f"{output} was converted from {existing['converted_from']}, "
                f"not {source.name}. Pass --force to replace it.",
            )
        if (
            recorded == source
            and existing.get("converted_sha256") == digest
            and not force
        ):
            typer.echo(f"{output} is up to date.")
            return

    name, converter = _CONVERTERS[suffix]
    body = converter(source, image_dir, output.parent)
    record = _conversion_record(source, output, name, digest)
    meta = _converted_frontmatter(existing, record, output, body, cfg)
    output.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
    typer.echo(f"Converted {source} to {output}")


@app.command()
def list_unconverted(
    json_output: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--json-output", help="Print the groups as JSON."),
    ] = False,
) -> None:
    """List raw documents that have no up-to-date markdown beside them.

    This is a helper for the agent. It needs no extra, only hashing and
    frontmatter, so a core-only install can still find work. Paths are relative
    to the bundle root.
    """
    groups = _scan_unconverted(config.load())
    if json_output:
        typer.echo(json.dumps(groups, indent=2))
        return

    if not any(groups.values()):
        typer.echo("All raw documents have been converted.")
        return

    total = sum(map(len, groups.values()))
    typer.echo(f"Found {total} file{'' if total == 1 else 's'} to look at:\n")
    for name, meaning in _LISTING_GROUPS.items():
        if not groups[name]:
            continue
        typer.echo(f"{name} ({len(groups[name])}): {meaning}")
        for path in groups[name]:
            typer.echo(f"  {path}")
        typer.echo("")


if __name__ == "__main__":
    app()
