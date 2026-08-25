"""Automated wiki health checks.

Checks that can be performed without LLM judgment:
- Orphan articles (no incoming links)
- Broken markdown links
- Broken image references
- Missing raw/images/<stem>/ subdirectories for documents that reference images
- Articles with no Sources section
- Sources sections pointing to raw/ files that no longer exist
- OKF v0.2 §11 conformance (parseable frontmatter carrying a ``type``)
- Article-bearing directories missing their generated ``INDEX.md``

Frontmatter is read exclusively through :mod:`okf_kb.frontmatter`, so
every check transparently accepts both the legacy ``source_files`` list and the
OKF ``sources`` list-of-mappings shape.

Writes a timestamped report to output/health-<YYYY-MM-DD-HHMM>.md.
Exits non-zero if any issues are found (suitable for use as a git hook).
"""

from __future__ import annotations

import re
from datetime import date, datetime

# Typer resolves these annotations at runtime to parse CLI arguments, so
# Path cannot move into a type-checking block.
from pathlib import Path  # noqa: TC003
from typing import Annotated
from urllib.parse import unquote

import typer

from okf_kb import config, frontmatter
from okf_kb.frontmatter import is_article

app = typer.Typer(help="Run automated health checks on the knowledge base wiki.")

#: Wiki files that are structural rather than articles. They carry no
#: frontmatter and no ``## Sources`` section, so article-level checks skip them.


def iter_articles(wiki_dir: Path) -> list[Path]:
    """List wiki article paths in sorted order.

    Args:
        wiki_dir: Path to the wiki directory.

    Returns:
        Sorted paths of every markdown file for which :func:`is_article` holds.

    """
    return [p for p in sorted(wiki_dir.rglob("*.md")) if is_article(p)]


def _frontmatter_of(md_file: Path) -> frontmatter.Frontmatter:
    """Parse an article's frontmatter, tolerating unusable blocks.

    Malformed frontmatter is reported once by :func:`check_okf_conformance`;
    the other checks treat such a file as having nothing to check rather than
    aborting the whole run.

    Args:
        md_file: Path to the markdown file.

    Returns:
        The parsed frontmatter mapping, or an empty mapping if absent or
        malformed.

    """
    try:
        data, _ = frontmatter.parse(md_file.read_text(encoding="utf-8"))
    except frontmatter.FrontmatterError:
        return {}
    return data


def _resolve_link(link: str, source_file: Path) -> Path:
    """Resolve a relative markdown link to an absolute path."""
    return (source_file.parent / unquote(link)).resolve()


def check_wiki_links(wiki_dir: Path) -> list[str]:
    """Find broken internal markdown links in wiki articles."""
    issues = []
    for md_file in sorted(wiki_dir.rglob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        for match in re.finditer(r"\[([^\]]*)\]\(([^)#\s]+)\)", text):
            target = match.group(2)
            if target.startswith("http"):
                continue
            resolved = _resolve_link(target, md_file)
            if not resolved.exists():
                rel = md_file.relative_to(wiki_dir.parent)
                issues.append(f"Broken link in `{rel}`: `{target}`")
    return issues


def check_image_refs(scan_dirs: list[Path], root: Path) -> list[str]:
    """Find broken image references in markdown files."""
    issues = []
    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for md_file in sorted(scan_dir.rglob("*.md")):
            text = md_file.read_text(encoding="utf-8")
            for match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", text):
                src = match.group(1)
                if src.startswith("http"):
                    continue
                resolved = _resolve_link(src, md_file)
                if not resolved.exists():
                    rel = md_file.relative_to(root)
                    issues.append(f"Broken image in `{rel}`: `{src}`")
    return issues


def check_image_subdirs(
    scan_dirs: list[Path],
    image_base: Path,
    root: Path,
) -> list[str]:
    """Warn when a document references images but has no raw/images/<stem>/ subdir."""
    issues = []
    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for md_file in sorted(scan_dir.rglob("*.md")):
            text = md_file.read_text(encoding="utf-8")
            has_local_image = bool(
                re.search(r"!\[[^\]]*\]\((?!https?://)[^)]+\)", text),
            )
            if has_local_image:
                subdir = image_base / md_file.stem
                if not subdir.exists():
                    rel = md_file.relative_to(root)
                    issues.append(
                        f"Missing image directory `raw/images/{md_file.stem}/` "
                        f"for `{rel}`",
                    )
    return issues


def check_okf_conformance(wiki_dir: Path) -> list[str]:
    """Check articles against the OKF v0.2 §11 minimum requirements.

    Every non-reserved markdown file under the wiki must carry parseable
    frontmatter with a non-empty ``type`` key. ``INDEX.md``, ``log.md`` and
    partials (``_*.md``) are exempt.

    Args:
        wiki_dir: Path to the wiki directory.

    Returns:
        One issue string per non-conforming article.

    """
    issues = []
    for md_file in iter_articles(wiki_dir):
        rel = md_file.relative_to(wiki_dir)
        try:
            data, _ = frontmatter.parse(md_file.read_text(encoding="utf-8"))
        except frontmatter.FrontmatterError as exc:
            issues.append(f"Malformed frontmatter in `{rel}`: {exc}")
            continue
        if not data:
            issues.append(f"Missing frontmatter in `{rel}` (OKF v0.2 §11)")
            continue
        type_value = data.get("type")
        if not isinstance(type_value, str) or not type_value.strip():
            issues.append(f"Missing or empty `type` in `{rel}` (OKF v0.2 §11)")
    return issues


def check_subdir_indexes(wiki_dir: Path) -> list[str]:
    """Find wiki directories that hold articles but have no ``INDEX.md``.

    Every article-bearing directory is expected to carry a generated index, so
    the wiki can be navigated by folder as well as from the root. A directory
    counts as article-bearing when an article sits anywhere beneath it, which
    includes pure container directories such as ``projects/``.

    Args:
        wiki_dir: Path to the wiki directory.

    Returns:
        One issue string per directory missing its index, in path order.

    """
    with_articles: set[Path] = set()
    for md_file in iter_articles(wiki_dir):
        for parent in md_file.parents:
            with_articles.add(parent)
            if parent == wiki_dir:
                break

    issues = []
    for directory in sorted(with_articles):
        if directory == wiki_dir:
            continue
        if not (directory / "INDEX.md").is_file():
            rel = directory.relative_to(wiki_dir)
            issues.append(f"Missing `INDEX.md` in `{rel}/` (run `kb-index`)")
    return issues


def check_source_files_frontmatter(wiki_dir: Path) -> list[str]:
    """Find articles with ## Sources but no declared sources in frontmatter."""
    issues = []
    for md_file in iter_articles(wiki_dir):
        text = md_file.read_text(encoding="utf-8")
        if "## Sources" not in text:
            continue
        data = _frontmatter_of(md_file)
        if not data:
            continue
        if not frontmatter.source_resources(data):
            rel = md_file.relative_to(wiki_dir)
            issues.append(
                f"Missing `source_files` frontmatter in `{rel}` "
                f"(has ## Sources section)",
            )
    return issues


def check_staleness(wiki_dir: Path) -> list[str]:
    """Find articles whose ``stale_after`` date has passed.

    OKF §5.5 defines content as stale when today is on or after ``stale_after``.
    An absent key means the article was never given an expiry, not that it is
    fresh.

    Args:
        wiki_dir: Path to the wiki directory.

    Returns:
        One issue string per stale article, oldest expiry first.

    """
    today = date.today()  # noqa: DTZ011
    issues: list[tuple[date, str]] = []

    for md_file in iter_articles(wiki_dir):
        data = _frontmatter_of(md_file)
        expiry = frontmatter.as_date(data.get("stale_after"))
        if expiry is not None and today >= expiry:
            days = (today - expiry).days
            issues.append(
                (
                    expiry,
                    f"`{md_file.name}` went stale on {expiry} ({days} day(s) ago)",
                ),
            )

    return [text for _, text in sorted(issues)]


def trust_tiers(wiki_dir: Path) -> dict[str, int]:
    """Count articles in each OKF trust tier (§5.2).

    Tiers are derived from ``verified``, never asserted: an absent key means
    unverified, a ``human:`` actor means human-reviewed, and anything else that
    verified it means machine-confirmed.

    Args:
        wiki_dir: Path to the wiki directory.

    Returns:
        Counts keyed by ``unverified``, ``machine-confirmed`` and
        ``human-reviewed``.

    """
    counts = {"unverified": 0, "machine-confirmed": 0, "human-reviewed": 0}

    for md_file in iter_articles(wiki_dir):
        entries = _frontmatter_of(md_file).get("verified")
        if isinstance(entries, dict):
            # §11: consumers must treat a bare mapping as a single-element list.
            entries = [entries]
        if not isinstance(entries, list) or not entries:
            counts["unverified"] += 1
            continue
        actors = [str(e.get("by", "")) for e in entries if isinstance(e, dict)]
        key = (
            "human-reviewed"
            if any(a.startswith("human:") for a in actors)
            else "machine-confirmed"
        )
        counts[key] += 1

    return counts


def check_stale_source_files(wiki_dir: Path, root: Path) -> list[str]:
    """Find declared source paths pointing to raw/ files that don't exist.

    Declared resources are repo-root-relative (``raw/...``), since ``raw/`` sits
    outside the wiki bundle. They must be resolved against the bundle root
    rather than the working directory, or every one of them reads as missing
    whenever the command is run from anywhere but the root.

    Args:
        wiki_dir: Path to the wiki directory.
        root: The bundle root that declared resources are relative to.

    Returns:
        One issue string per declared resource that does not exist.

    """
    issues = []
    for md_file in iter_articles(wiki_dir):
        data = _frontmatter_of(md_file)
        for item in frontmatter.source_resources(data):
            path = root / item.strip()
            if not path.exists():
                rel = md_file.relative_to(wiki_dir)
                issues.append(
                    f"Stale source_files entry in `{rel}`: `{item.strip()}` "
                    f"does not exist",
                )
    return issues


def check_sources_sections(wiki_dir: Path) -> list[str]:
    """Find wiki articles that have no Sources section."""
    issues = []
    for md_file in iter_articles(wiki_dir):
        text = md_file.read_text(encoding="utf-8")
        if "## Sources" not in text:
            rel = md_file.relative_to(wiki_dir)
            issues.append(f"No `## Sources` section in `{rel}`")
    return issues


def _split_safely(text: str) -> tuple[dict, str]:
    """Parse frontmatter, falling back to an empty mapping on malformed input."""
    try:
        return frontmatter.parse(text)
    except frontmatter.FrontmatterError:
        return {}, text


def check_sources_listed(wiki_dir: Path) -> list[str]:
    """Find sources declared in frontmatter but not linked in ``## Sources``.

    The body section is authored, not generated — it carries per-source
    annotations and, on several articles, a nested ``### Bibliography`` of
    published work that frontmatter does not model. So the two are kept in
    agreement by checking rather than by overwriting.

    Args:
        wiki_dir: Path to the wiki directory.

    Returns:
        One issue string per source missing from its article's body.

    """
    issues: list[str] = []

    for md_file in iter_articles(wiki_dir):
        text = md_file.read_text(encoding="utf-8")
        _, body = _split_safely(text)
        start = body.find("\n## Sources")
        if start == -1:
            continue  # reported separately by check_sources_sections
        section = body[start:]

        for resource in frontmatter.source_resources(_frontmatter_of(md_file)):
            stem = resource.rsplit("/", 1)[-1]
            if stem not in unquote(section):
                issues.append(
                    f"`{md_file.name}` declares source `{resource}` "
                    f"but does not link it in ## Sources",
                )

    return issues


def check_stale_sources(wiki_dir: Path) -> list[str]:
    """Find Sources entries pointing to raw/ files that no longer exist."""
    issues = []
    source_pattern = re.compile(r"\[([^\]]+)\]\(((?:\.\.\/)+raw\/[^)]+)\)")
    for md_file in sorted(wiki_dir.rglob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        in_sources = False
        for line in text.splitlines():
            if line.startswith("## Sources"):
                in_sources = True
                continue
            if in_sources and line.startswith("## "):
                in_sources = False
            if not in_sources:
                continue
            for match in source_pattern.finditer(line):
                raw_link = match.group(2)
                resolved = _resolve_link(raw_link, md_file)
                if not resolved.exists():
                    rel = md_file.relative_to(wiki_dir)
                    issues.append(
                        f"Stale source in `{rel}`: `{raw_link}` does not exist",
                    )
    return issues


def check_orphans(wiki_dir: Path) -> list[str]:
    """Find wiki articles not linked from any other article or INDEX.md."""
    md_files = sorted(wiki_dir.rglob("*.md"))
    all_files = {f.resolve() for f in md_files}
    linked: set[Path] = set()

    for md_file in md_files:
        text = md_file.read_text(encoding="utf-8")
        for match in re.finditer(r"\[([^\]]*)\]\(([^)#\s]+)\)", text):
            target = match.group(2)
            if target.startswith("http"):
                continue
            resolved = _resolve_link(target, md_file)
            linked.add(resolved)

    root = wiki_dir.resolve()
    orphans = [f for f in all_files if f not in linked and is_article(f)]
    return [f"Orphan article: `{p.relative_to(root)}`" for p in sorted(orphans)]


@app.command()
def main(
    wiki_dir: Annotated[
        Path | None,
        typer.Option(help="Wiki directory. Defaults to the bundle's."),
    ] = None,
    raw_dir: Annotated[
        Path | None,
        typer.Option(help="Raw sources directory. Defaults to the bundle's."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option(help="Output directory for report. Defaults to the bundle's."),
    ] = None,
    fail_on_issues: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--fail/--no-fail", help="Exit non-zero if issues found."),
    ] = True,
) -> None:
    """Run automated health checks and write a timestamped report to output/.

    Raises:
        Exit: With status 1 when issues are found and ``--fail`` is in effect.

    """
    wiki_dir = config.resolve_dir(wiki_dir, "wiki")
    raw_dir = config.resolve_dir(raw_dir, "raw")
    output_dir = config.resolve_dir(output_dir, "output")

    # Issue text is written relative to this, so a report reads the same however
    # it was invoked. Falls back to the wiki's parent when the directories were
    # passed explicitly and there is no bundle to discover.
    root = config.find_root() or wiki_dir.parent

    output_dir.mkdir(parents=True, exist_ok=True)
    image_base = raw_dir / "images"
    papers_dir = raw_dir / "papers"

    sections: dict[str, list[str]] = {
        "OKF conformance": check_okf_conformance(wiki_dir),
        "Directory indexes": check_subdir_indexes(wiki_dir),
        "Orphan Articles": check_orphans(wiki_dir),
        "Broken Wiki Links": check_wiki_links(wiki_dir),
        "Broken Image References": check_image_refs([wiki_dir, papers_dir], root),
        "Missing Image Subdirectories": check_image_subdirs(
            [papers_dir],
            image_base,
            root,
        ),
        "Articles Missing Sources Section": check_sources_sections(wiki_dir),
        "Stale Source Links": check_stale_sources(wiki_dir),
        "Missing source_files Frontmatter": check_source_files_frontmatter(wiki_dir),
        "Stale source_files Entries": check_stale_source_files(wiki_dir, root),
        "Stale Content (stale_after passed)": check_staleness(wiki_dir),
        "Sources Declared But Not Linked": check_sources_listed(wiki_dir),
    }

    total_issues = sum(len(v) for v in sections.values())
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    report_path = output_dir / f"health-{timestamp}.md"

    tiers = trust_tiers(wiki_dir)
    lines = [
        f"# Wiki Health Report — {timestamp}",
        "",
        f"**Total issues:** {total_issues}",
        "",
        "## Trust tiers (OKF §5.2) — informational",
        "",
        "Derived from `verified`, not asserted. An unverified article is not a",
        "defect; it simply has not been read back against its sources by a human.",
        "Use `/verify` to record a sign-off.",
        "",
        f"- unverified: {tiers['unverified']}",
        f"- machine-confirmed: {tiers['machine-confirmed']}",
        f"- human-reviewed: {tiers['human-reviewed']}",
        "",
    ]
    for section, issues in sections.items():
        status = "OK" if not issues else f"{len(issues)} issue(s)"
        lines.append(f"## {section} — {status}")
        lines.append("")
        if issues:
            lines.extend(f"- {issue}" for issue in issues)
        else:
            lines.append("_No issues found._")
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    typer.echo(f"Health report written to {report_path}")

    if total_issues:
        typer.echo(f"Found {total_issues} issue(s). See report for details.")
        if fail_on_issues:
            raise typer.Exit(1)
    else:
        typer.echo("All checks passed.")


if __name__ == "__main__":
    app()
