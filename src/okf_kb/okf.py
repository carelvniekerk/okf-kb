"""OKF v0.2 schema construction for wiki articles.

Builds the Open Knowledge Format frontmatter families from the repository's
existing metadata plus git history:

* provenance (§5.1) — ``sources``, replacing the legacy ``sources: <int>`` count
  and ``source_files`` string list with a list of mappings carrying ``id``,
  ``resource``, ``title``, ``author`` and ``last_modified``;
* trust (§5.2) — ``generated``, stamped with the producing model, timestamp and
  skill version;
* lifecycle (§5.4-5.5) — ``status`` and ``stale_after``.

The bundle root is ``wiki/`` and ``raw/`` sits outside it, so ``sources[].resource``
uses repo-root-relative paths rather than bundle-absolute ones. That keeps the
values byte-identical to the ``source_files`` entries they replace and stable
under article moves, at the cost of needing the repo root as the resolution base
— which the bundle-root index declares.

`verified` is deliberately never written here. Under §5.2 an absent ``verified``
key means *unverified*, which is the honest state for agent-written articles
that no human has signed off. Only an explicit human review may add it.
"""

from __future__ import annotations

import re
from datetime import UTC
from html import unescape
from typing import TYPE_CHECKING, Any

from okf_kb import frontmatter as fm
from okf_kb import gitmeta

if TYPE_CHECKING:
    from datetime import date
    from pathlib import Path

#: Canonical key order for a migrated article. OKF core first, then the trust
#: and lifecycle families, then provenance, then local extensions. Keys absent
#: from an article are simply skipped.
KEY_ORDER: tuple[str, ...] = (
    # OKF core (§4.1)
    "type",
    "title",
    "description",
    "tags",
    "resource",
    # OKF trust (§5.2)
    "generated",
    "verified",
    # OKF lifecycle (§5.4-5.5)
    "status",
    "stale_after",
    # OKF provenance (§5.1)
    "sources",
    # local extensions, preserved under §11's tolerance of unknown keys
    "source_type",
    "date_added",
    "date_updated",
    "arxiv",
)

#: Which actor authored the material in each `raw/` subdirectory. Git author is
#: useless here because every file is committed by the repository owner
#: regardless of who or what wrote it, so the directory's role is the signal.
_AUTHOR_BY_ZONE: dict[str, str] = {
    "notes": "human:carel",
    "meetings": "human:carel",
    "handwritten": "human:carel",
    # Fetched rather than authored: the intellectual author is the upstream
    # paper's, which this field does not attempt to capture.
    "papers": "process:kb-ingest",
    "clippings": "process:kb-ingest",
}

#: Zones whose contents an agent wrote, so the producing model is the author.
_AGENT_AUTHORED_ZONES: frozenset[str] = frozenset(
    {"research", "videos", "transcriptions", "daily-briefs"},
)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_HEADING = re.compile(r"^#\s+(.+)$", re.MULTILINE)
#: Notion exports append a 32-character hex id to the filename stem.
_NOTION_SUFFIX = re.compile(r"\s+[0-9a-f]{32}$")
#: `kb-ingest arxiv` writes a `# arXiv: <id>` banner above the real title, so
#: the first heading in a fetched paper is never the paper's name.
_ARXIV_BANNER = re.compile(r"^arxiv:\s*[\d.v]+$", re.IGNORECASE)
#: Upper bound on a generated source id, to keep footnote keys typable.
_MAX_ID_LENGTH = 40

#: Qualifier appended when two sources in one article resolve to the same title.
#: Reading notes about a paper usually repeat the paper's own heading, so the
#: bare titles collide and give the reader nothing to choose between.
_ZONE_QUALIFIER: dict[str, str] = {
    "notes": "reading notes",
    "papers": "paper",
    "meetings": "meeting notes",
    "transcriptions": "transcription",
    "research": "research brief",
    "videos": "video",
    "clippings": "web clipping",
    "daily-briefs": "daily brief",
}


#: Leading key order for a normalised ``raw/`` reference file. Deliberately
#: shorter than :data:`KEY_ORDER`: ``raw/`` is OKF's *references* zone (§6.3), so
#: it carries just enough identity to be citable and is not held to full bundle
#: conformance. Every other key keeps its original relative position.
RAW_KEY_ORDER: tuple[str, ...] = (
    "type",
    "title",
    "description",
    "author",
    "date_added",
)

#: Document type for each ``raw/`` subdirectory, used only when the file does not
#: already declare one. Named after what the material *is*, not what a wiki
#: article made of it would be.
_RAW_TYPE_BY_ZONE: dict[str, str] = {
    "papers": "paper",
    "notes": "note",
    "clippings": "clipping",
    "research": "research-brief",
    "transcriptions": "transcription",
    "daily-briefs": "daily-brief",
    "meetings": "meeting-log",
}

#: Compilation update strategy for each zone (see the `source_type` table in
#: CLAUDE.md). Daily briefs are classified ``meeting`` because they are
#: chronological logs of decisions and action items, which is the strategy that
#: label selects — not because they record a meeting.
_RAW_SOURCE_TYPE_BY_ZONE: dict[str, str] = {
    "meetings": "meeting",
    "daily-briefs": "meeting",
}

#: Fallback when a zone has no explicit entry above.
_DEFAULT_RAW_SOURCE_TYPE = "technical"

#: Headings written by an ingestion tool rather than by the document's author:
#: the ``# arXiv: <id>`` banner from ``kb-ingest arxiv`` and the bare ``# <id>``
#: that PDF extraction leaves when the paper's own title never became a heading.
_INGEST_BANNER = re.compile(r"^(arxiv:\s*)?\d{4}\.\d{4,5}(v\d+)?$", re.IGNORECASE)


#: An INDEX.md article entry: `- <emoji> [Title](./path.md) — one-line summary`.
_INDEX_ENTRY = re.compile(
    r"^-\s+\S+\s+\[([^\]]+)\]\(\./([^)]+\.md)\)\s+—\s+(.+?)\s*$",
    re.MULTILINE,
)


def descriptions_from_index(index_path: Path) -> dict[str, str]:
    """Harvest per-article one-line summaries from a hand-written INDEX.

    The existing INDEX entries are already the one-sentence descriptions OKF
    §4.1 recommends, written by hand and reviewed over time. Seeding
    ``description`` from them keeps the wording rather than inventing new
    summaries, and lets the index be regenerated from frontmatter afterwards.

    Args:
        index_path: Path to the INDEX file.

    Returns:
        A mapping from wiki-relative article path to its summary. Empty if the
        index does not exist.

    """
    if not index_path.is_file():
        return {}

    text = index_path.read_text(encoding="utf-8")
    found: dict[str, str] = {}
    for _title, path, summary in _INDEX_ENTRY.findall(text):
        # INDEX entries are rendered markdown, so entities and emphasis leak in.
        clean = unescape(summary).replace("**", "").strip()
        found[path] = clean
    return found


def source_id(resource: str, taken: set[str] | None = None) -> str:
    """Derive a stable, readable id for a source.

    Ids key per-claim footnotes (``[^fa2-paper]``) to ``sources[].id``, so they
    need to be human-typable as well as unique within the article.

    Args:
        resource: The source path, e.g. ``raw/papers/2307.08691.md``.
        taken: Ids already used in this article. A numeric suffix is appended on
            collision. Mutated in place when supplied.

    Returns:
        A kebab-case id unique within ``taken``.

    Examples:
        >>> source_id("raw/papers/2307.08691.md")
        '2307-08691'
        >>> source_id("raw/meetings/2026-08-04-ccep-kpi-discussion.md")
        '2026-08-04-ccep-kpi-discussion'

    """
    stem = resource.rsplit("/", 1)[-1].removesuffix(".md")
    stem = _NOTION_SUFFIX.sub("", stem)
    slug = _NON_ALNUM.sub("-", stem.lower()).strip("-") or "source"
    if len(slug) > _MAX_ID_LENGTH:
        # Trim back to the last word boundary so the id stays readable rather
        # than ending mid-word.
        head = slug[:_MAX_ID_LENGTH]
        boundary = head.rfind("-")
        slug = (head[:boundary] if boundary > 0 else head).rstrip("-")

    if taken is None:
        return slug

    candidate = slug
    counter = 2
    while candidate in taken:
        candidate = f"{slug}-{counter}"
        counter += 1
    taken.add(candidate)
    return candidate


def source_title(resource: str, root: Path) -> str:
    """Derive a human-readable title for a source.

    Prefers the source's own frontmatter ``title``, then its first H1 heading,
    then a prettified filename.

    Args:
        resource: Repo-relative source path.
        root: Repository root, used to resolve ``resource``.

    Returns:
        A display title. Never empty.

    """
    path = root / resource
    if path.is_file():
        try:
            doc = fm.load(path)
        except fm.FrontmatterError:
            doc = None
        if doc is not None:
            declared = doc.frontmatter.get("title")
            if isinstance(declared, str) and declared.strip():
                return declared.strip()
            for heading in _HEADING.finditer(doc.body):
                candidate = heading.group(1).strip()
                if candidate and not _ARXIV_BANNER.match(candidate):
                    return candidate

    stem = resource.rsplit("/", 1)[-1].removesuffix(".md")
    return _NOTION_SUFFIX.sub("", stem).strip() or resource


def source_zone(resource: str) -> str:
    """Return the ``raw/`` subdirectory a source lives in.

    Args:
        resource: Repo-relative source path.

    Returns:
        The zone name, or an empty string for files directly under ``raw/``.

    """
    parts = resource.split("/")
    if len(parts) >= 3 and parts[0] == "raw":  # noqa: PLR2004
        return parts[1]
    return ""


def source_author(resource: str, root: Path) -> str | None:
    """Determine the OKF actor that authored a source.

    Args:
        resource: Repo-relative source path.
        root: Repository root.

    Returns:
        An actor id per OKF §7, or ``None`` when it cannot be determined.

    """
    zone = source_zone(resource)
    if zone in _AUTHOR_BY_ZONE:
        return _AUTHOR_BY_ZONE[zone]

    if zone in _AGENT_AUTHORED_ZONES:
        sha = gitmeta.creation_commit(_as_path(resource), zone="raw", cwd=root)
        if sha:
            commit = gitmeta.commit_info(sha, cwd=root)
            if commit.model:
                return commit.model
        return "claude"

    # Files directly under raw/ predate the subdirectory convention and were all
    # hand-curated.
    return "human:carel"


def _as_path(resource: str) -> Path:
    from pathlib import Path  # noqa: PLC0415

    return Path(resource)


def build_sources(frontmatter: fm.Frontmatter, root: Path) -> list[dict[str, Any]]:
    """Build the OKF ``sources`` list from an article's existing metadata.

    Args:
        frontmatter: The article's current frontmatter. Read via
            :func:`okf_kb.frontmatter.source_resources`, so both the
            legacy ``source_files`` and an already-migrated ``sources`` work.
        root: Repository root.

    Returns:
        A list of OKF source mappings in the original declaration order.

    """
    taken: set[str] = set()
    entries: list[dict[str, Any]] = []

    for resource in fm.source_resources(frontmatter):
        entry: dict[str, Any] = {
            "id": source_id(resource, taken),
            "resource": resource,
            "title": source_title(resource, root),
        }
        author = source_author(resource, root)
        if author:
            entry["author"] = author
        modified = gitmeta.last_modified(_as_path(resource), cwd=root)
        if modified:
            # A real date object serialises bare (`2026-04-07`), matching the
            # existing `date_added` / `date_updated` style rather than quoting.
            entry["last_modified"] = fm.as_date(modified) or modified
        entries.append(entry)

    _disambiguate_titles(entries)
    return entries


def _disambiguate_titles(entries: list[dict[str, Any]]) -> None:
    """Qualify duplicate source titles in place with their zone's role.

    Args:
        entries: Source mappings, each with ``title`` and ``resource``.

    """
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["title"]] = counts.get(entry["title"], 0) + 1

    for entry in entries:
        if counts[entry["title"]] < 2:  # noqa: PLR2004
            continue
        qualifier = _ZONE_QUALIFIER.get(source_zone(entry["resource"]))
        if qualifier:
            entry["title"] = f"{entry['title']} ({qualifier})"


def build_generated(article: Path, root: Path) -> dict[str, Any] | None:
    """Build the OKF ``generated`` block for an article from git history.

    Args:
        article: Repo-relative path to the article.
        root: Repository root.

    Returns:
        A mapping with ``by``, ``at`` and (where known) ``skill`` and ``commit``,
        or ``None`` if the article has no git history.

    """
    prov = gitmeta.provenance(article, zone="wiki", cwd=root)
    if prov is None:
        return None

    block: dict[str, Any] = {}
    if prov.commit.model:
        block["by"] = prov.commit.model
    # OKF §5.2 shows `at` as ISO 8601 UTC. Normalised to `Z` so timestamps are
    # comparable across articles regardless of the committer's local offset.
    block["at"] = (
        prov.commit.date.astimezone(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )
    if prov.skill_ref:
        block["skill"] = prov.skill_ref
    block["commit"] = prov.commit.sha
    return block


def reorder(frontmatter: fm.Frontmatter) -> fm.Frontmatter:
    """Return the frontmatter with keys in the canonical OKF-first order.

    Keys not listed in :data:`KEY_ORDER` are preserved and appended after the
    known ones, in their original relative order.

    Args:
        frontmatter: The mapping to reorder.

    Returns:
        A new mapping with the same contents in canonical order.

    """
    ordered = {key: frontmatter[key] for key in KEY_ORDER if key in frontmatter}
    for key, value in frontmatter.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def migrate(
    document: fm.Document,
    article: Path,
    root: Path,
    description: str | None = None,
) -> fm.Document:
    """Migrate one article's frontmatter to the OKF v0.2 shape.

    Replaces the ``sources`` integer count and ``source_files`` list with the
    OKF ``sources`` family, stamps ``generated`` from git history, defaults
    ``status`` to ``stable``, and reorders keys canonically. Existing values are
    not overwritten, so re-running is idempotent.

    Args:
        document: The parsed article.
        article: Repo-relative path to the article, used for git lookups.
        root: Repository root.
        description: One-sentence summary for OKF ``description``. Ignored when
            the article already declares one.

    Returns:
        A new document with migrated frontmatter and an unchanged body.

    """
    data = dict(document.frontmatter)

    if description and "description" not in data:
        data["description"] = description

    if "title" not in data:
        heading = _HEADING.search(document.body)
        if heading:
            data["title"] = heading.group(1).strip()

    if "resource" not in data and data.get("arxiv"):
        # The canonical URI of the underlying asset (OKF §4.1). For a paper
        # summary that is the arXiv abstract page.
        data["resource"] = f"https://arxiv.org/abs/{data['arxiv']}"

    sources = build_sources(data, root)
    data.pop("source_files", None)
    if sources:
        data["sources"] = sources
    else:
        data.pop("sources", None)

    if "generated" not in data:
        generated = build_generated(article, root)
        if generated:
            data["generated"] = generated

    data.setdefault("status", "stable")

    return fm.Document(
        frontmatter=reorder(data),
        body=document.body,
        path=document.path,
    )


def raw_type(resource: str) -> str | None:
    """Derive the document type for a ``raw/`` file from its zone.

    Args:
        resource: Repo-relative source path, e.g. ``raw/papers/2307.08691.md``.

    Returns:
        The type name, or ``None`` for a zone with no mapping (including files
        directly under ``raw/``), where the caller must supply one.

    Examples:
        >>> raw_type("raw/papers/2307.08691.md")
        'paper'
        >>> raw_type("raw/notes/vllm-mac-installation.md")
        'note'

    """
    return _RAW_TYPE_BY_ZONE.get(source_zone(resource))


def raw_source_type(resource: str) -> str:
    """Derive the compilation update strategy for a ``raw/`` file from its zone.

    Args:
        resource: Repo-relative source path.

    Returns:
        One of ``technical``, ``discussion``, ``experiment`` or ``meeting``.

    """
    return _RAW_SOURCE_TYPE_BY_ZONE.get(
        source_zone(resource),
        _DEFAULT_RAW_SOURCE_TYPE,
    )


def raw_title(body: str) -> str | None:
    """Extract a document's own title from its body.

    Ingestion tools prepend a provenance banner above the real title, so the
    first heading in a fetched paper names the arXiv id rather than the paper.
    Those headings are skipped.

    Args:
        body: The document body, excluding frontmatter.

    Returns:
        The first heading that is not an ingestion banner, or ``None`` when the
        document has no usable heading and the caller must supply a title.

    """
    for heading in _HEADING.finditer(body):
        candidate = heading.group(1).strip()
        if candidate and not _INGEST_BANNER.match(candidate):
            return candidate
    return None


def creation_date(resource: str, root: Path) -> date | None:
    """Find the date a ``raw/`` file first entered the repository.

    Args:
        resource: Repo-relative source path.
        root: Repository root.

    Returns:
        The creating commit's date, or ``None`` when the path has no history in
        the ``raw/`` zone.

    """
    sha = gitmeta.creation_commit(_as_path(resource), zone="raw", cwd=root)
    if sha is None:
        return None
    return gitmeta.commit_info(sha, cwd=root).date.date()


def strip_self_reference(frontmatter: fm.Frontmatter, resource: str) -> bool:
    """Drop provenance keys that name the file as its own source.

    Several ``raw/`` files were written from the wiki article template and
    inherited a ``sources: 1`` / ``source_files: [<itself>]`` pair. A source is
    not its own source, and leaving the pair in place makes
    ``kb-provenance map`` report the file as feeding itself.

    A ``sources`` count with no ``source_files`` list is left alone: on the
    research briefs it counts the external works consulted, which is real
    provenance rather than a self-reference.

    Args:
        frontmatter: The mapping to clean, mutated in place.
        resource: Repo-relative path of the file the mapping belongs to.

    Returns:
        ``True`` if anything was removed.

    """
    declared = frontmatter.get("source_files")
    if not isinstance(declared, list) or not declared:
        return False
    if any(str(entry) != resource for entry in declared):
        return False

    del frontmatter["source_files"]
    frontmatter.pop("sources", None)
    return True


def reorder_raw(frontmatter: fm.Frontmatter) -> fm.Frontmatter:
    """Return the frontmatter with the raw-reference identity keys first.

    Args:
        frontmatter: The mapping to reorder.

    Returns:
        A new mapping holding the same items, with :data:`RAW_KEY_ORDER` leading
        and every other key following in its original relative order.

    """
    ordered = {key: frontmatter[key] for key in RAW_KEY_ORDER if key in frontmatter}
    for key, value in frontmatter.items():
        if key not in ordered:
            ordered[key] = value
    return ordered


def migrate_raw(
    document: fm.Document,
    resource: str,
    root: Path,
    title: str | None = None,
    description: str | None = None,
) -> fm.Document:
    """Normalise one ``raw/`` reference file's frontmatter.

    Gives every source the minimum identity needed to cite it — what it is, what
    it is called, what it contains, who produced it and when — and removes the
    self-referencing provenance pair. Existing values always win, so re-running
    is idempotent and no hand-written metadata is overwritten.

    The body is returned untouched.

    Args:
        document: The parsed source file.
        resource: Repo-relative path to the file, used for zone lookups and git
            archaeology.
        root: Repository root.
        title: Title to use when the file declares none in its frontmatter.
            Overrides the body heading, which lets the caller correct the cases
            where extraction picks up LaTeX cruft or a mid-document heading.
        description: One-sentence summary of what the document contains.
            Ignored when the file already declares one.

    Returns:
        A new document with normalised frontmatter and an unchanged body.

    """
    data = dict(document.frontmatter)
    strip_self_reference(data, resource)

    if "type" not in data:
        derived_type = raw_type(resource)
        if derived_type:
            data["type"] = derived_type

    if "title" not in data:
        derived_title = title or raw_title(document.body)
        if derived_title:
            data["title"] = derived_title

    if description and "description" not in data:
        data["description"] = description

    if "author" not in data:
        author = source_author(resource, root)
        if author:
            data["author"] = author

    if "date_added" not in data:
        added = creation_date(resource, root)
        if added:
            data["date_added"] = added

    data.setdefault("source_type", raw_source_type(resource))

    return fm.Document(
        frontmatter=reorder_raw(data),
        body=document.body,
        path=document.path,
    )


def render_sources_section(sources: list[dict[str, Any]], article: Path) -> str:
    """Render the body ``## Sources`` list from the OKF ``sources`` array.

    Used when creating a new article. It is deliberately NOT used to rewrite
    existing ones: several articles carry per-source annotations explaining what
    each source contributed, and nest a ``### Bibliography`` subsection of
    published work beneath the heading. Both hold information frontmatter does
    not, so regenerating over them would lose content. ``check_sources_listed``
    in :mod:`okf_kb.health` enforces agreement instead.

    Note this is *provenance* — which files in this knowledge base the article
    was compiled from. It is not a bibliography: several articles additionally
    carry numbered ``[^N]`` footnotes citing published work, which is a separate
    system and is deliberately left alone.

    Args:
        sources: The article's ``sources`` frontmatter array.
        article: Repo-relative path to the article, used to compute link depth.

    Returns:
        The complete section including its heading, ending in a newline.

    """
    from urllib.parse import quote  # noqa: PLC0415

    depth = len(article.parent.parts)
    prefix = "../" * depth

    lines = ["## Sources", ""]
    for entry in sources:
        resource = str(entry.get("resource", ""))
        title = str(entry.get("title") or resource)
        href = prefix + quote(resource)
        lines.append(f"- [{title}]({href})")
    lines.append("")
    return "\n".join(lines)
