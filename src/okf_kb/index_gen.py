"""Generate the wiki's ``INDEX.md`` files from article frontmatter.

Every index in the wiki is derived, not written. The root index and one index
per article-bearing subdirectory are rendered from the OKF frontmatter the
articles already carry, so the counts and badges cannot drift away from what is
on disk — the hand-maintained root index had a ``sources-41`` badge matching
neither the frontmatter sum (42) nor the number of distinct sources (33).

Two things stay hand-authored, because no amount of frontmatter implies them:

* the *shape* of the root index — which directories group together and in what
  order — lives in :data:`ROOT_GROUPS`;
* the display title and emoji of each directory live in :data:`SECTION_TITLES`.

Both are module-level constants meant to be edited when the wiki gains a
section. Directories missing from :data:`ROOT_GROUPS` are still rendered, in a
trailing fallback group, so a new section is never silently dropped from the
index.

Per OKF §8 only the bundle root may carry frontmatter, so ``wiki/INDEX.md`` gets
the ``okf_version`` / ``kb_format`` block and the subdirectory indexes get none.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

# Typer resolves these annotations at runtime to parse CLI arguments, so
# Path cannot move into a type-checking block.
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Annotated, Any

import typer

from okf_kb import config
from okf_kb import frontmatter as fm

if TYPE_CHECKING:
    from collections.abc import Mapping

app = typer.Typer(help="Generate the wiki's INDEX.md files from article frontmatter.")

#: The generated index filename, and one of the OKF reserved names.
INDEX_FILENAME = "INDEX.md"

#: Frontmatter for the bundle root index only (OKF §8, §12).
ROOT_FRONTMATTER: dict[str, str] = {"okf_version": "0.2", "kb_format": "1.0"}

ROOT_TITLE = "🧠 Knowledge Base"

#: Standing prose under the root index badges. One sentence per line, per the
#: repository's diff-friendly markdown convention.
ROOT_INTRO_SUFFIX = (
    "Maintained by an LLM agent — see [Operations Log](./log.md) for history."
)

#: The closing section of the root index.
OPERATIONS_SECTION = (
    "## 📜 Operations\n"
    "\n"
    "- [Operations Log](./log.md) — Chronological history of all compilations, "
    "ingestions, Q&A, and lint passes"
)

#: Display title, including its emoji, for each wiki directory. Keyed by the
#: directory's wiki-relative POSIX path so nested project directories can be
#: named independently of their parent. Used for both the directory's own
#: ``INDEX.md`` heading and its heading in the root index.
SECTION_TITLES: dict[str, str] = {
    "foundations": "🏗️ Foundations",
    "efficiency": "⚡ Efficient Inference & Training",
    "alignment": "🎯 Alignment & Post-Training",
    "research": "🔭 Research Directions",
    "projects": "🏁 Projects",
    "projects/car-bench": "🚗 CAR-bench Challenge",
    "projects/bt-contract-intelligence": "📄 BT Contract Intelligence",
    "projects/ccep-pilot": "🏬 CCEP Pilot Program",
    "software-design": "🐍 Python & Software Design",
    "tools": "🛠️ Development & Tools",
    "personal": "📬 Other",
}

#: Optional one-line blurb rendered under a directory's heading, in both its own
#: index and the root index.
SECTION_DESCRIPTIONS: dict[str, str] = {
    "projects": (
        "Active projects and challenges I am working on, "
        "with their own hubs and supporting references."
    ),
}


@dataclass(frozen=True)
class RootGroup:
    """One top-level ``##`` section of the root index.

    Attributes:
        title: The rendered heading text, emoji included.
        directories: Wiki-relative directory paths gathered under the heading,
            in render order. A single-directory group renders that directory's
            contents straight under the ``##`` heading; a multi-directory group
            gives each directory its own ``###`` subheading.

    """

    title: str
    directories: tuple[str, ...]


#: The curated shape of the root index. Order is significant.
ROOT_GROUPS: tuple[RootGroup, ...] = (
    RootGroup(
        title="🤖 Machine Learning & LLMs",
        directories=("foundations", "efficiency", "alignment", "research"),
    ),
    RootGroup(title=SECTION_TITLES["projects"], directories=("projects",)),
    RootGroup(
        title=SECTION_TITLES["software-design"],
        directories=("software-design",),
    ),
    RootGroup(title=SECTION_TITLES["tools"], directories=("tools",)),
    RootGroup(title=SECTION_TITLES["personal"], directories=("personal",)),
)

#: Heading for directories present on disk but absent from :data:`ROOT_GROUPS`.
FALLBACK_GROUP_TITLE = "📁 Unfiled"

#: Emoji prefixing an article entry when its title carries none of its own.
DEFAULT_ARTICLE_EMOJI = "📄"

#: Emoji prefixing a child-directory entry.
DIRECTORY_EMOJI = "📂"

#: Rotated across an article's tag badges so adjacent tags stay distinguishable.
TAG_COLOURS: tuple[str, ...] = ("blue", "orange", "green", "purple", "red", "yellow")

#: Upper bound on tag badges per entry. Some articles carry a dozen tags, which
#: would swamp the one-line summary they sit beneath.
MAX_TAG_BADGES = 4

#: OKF §5.2 trust tiers, in increasing order of assurance.
TIER_UNVERIFIED = "unverified"
TIER_MACHINE = "machine-confirmed"
TIER_HUMAN = "human-reviewed"

#: Badge markdown per trust tier. Absent verification is the honest default for
#: agent-written articles, so it gets the quietest colour rather than a warning.
TIER_BADGES: dict[str, str] = {
    TIER_UNVERIFIED: (
        "![unreviewed](https://img.shields.io/badge/review-pending-lightgrey)"
    ),
    TIER_MACHINE: "![machine-confirmed](https://img.shields.io/badge/review-machine-blue)",
    TIER_HUMAN: "![human-reviewed](https://img.shields.io/badge/review-human-brightgreen)",
}

#: The lifecycle status that needs no badge, being the assumed default.
DEFAULT_STATUS = "stable"

#: Badge colour per non-default lifecycle status (OKF §5.4).
STATUS_COLOURS: dict[str, str] = {
    "draft": "yellow",
    "deprecated": "red",
    "superseded": "orange",
}

_HEALTH_UNKNOWN = "![Health](https://img.shields.io/badge/health-unknown-lightgrey)"
_HEALTH_PASSING = (
    "![Health](https://img.shields.io/badge/health-%E2%9C%93%20passing-brightgreen)"
)

#: Recovers the date from an already-rendered ``compiled`` badge. The date's
#: hyphens arrive doubled, since :func:`shield_escape` escapes them for
#: shields.io's field separator.
_COMPILED_BADGE_RE = re.compile(
    r"!\[Last Compiled\]\(https://img\.shields\.io/badge/compiled-"
    r"(\d{4})--(\d{2})--(\d{2})-lightgrey\)",
)

#: The OKF actor prefix that marks a human sign-off (§7).
_HUMAN_ACTOR_PREFIX = "human:"


def shield_escape(text: str) -> str:
    """Escape a string for use inside a shields.io badge path segment.

    shields.io reads ``-`` as its field separator and ``_`` as a space, so both
    must be doubled and literal spaces written as ``_``.

    Args:
        text: The raw label text.

    Returns:
        The escaped text, safe to interpolate into a badge URL.

    """
    return text.replace("_", "__").replace("-", "--").replace(" ", "_")


def split_emoji(title: str, default: str = DEFAULT_ARTICLE_EMOJI) -> tuple[str, str]:
    """Separate a leading emoji from a title.

    Several articles encode their icon in the frontmatter ``title`` itself
    (``"🏁 CAR-bench Challenge — Project Hub"``). The index renders the icon in
    the bullet rather than inside the link text, so it has to come back off.

    Args:
        title: The raw title.
        default: Emoji to return when the title carries none.

    Returns:
        A tuple of ``(emoji, remaining title)``. The title is returned unchanged
        when its first word is ordinary text.

    """
    stripped = title.strip()
    head, _, rest = stripped.partition(" ")
    if rest.strip() and head and not any(ch.isalnum() for ch in head):
        return head, rest.strip()
    return default, stripped


def trust_tier(frontmatter: fm.Frontmatter) -> str:
    """Derive an article's OKF §5.2 trust tier.

    Args:
        frontmatter: The article's parsed frontmatter.

    Returns:
        :data:`TIER_UNVERIFIED` when no ``verified`` record is present,
        :data:`TIER_HUMAN` when any recorded actor is a ``human:`` id, and
        :data:`TIER_MACHINE` otherwise. An empty or null ``verified`` value
        counts as unverified: it attests to nothing.

    """
    verified = frontmatter.get("verified")
    if not verified:
        return TIER_UNVERIFIED
    if any(actor.startswith(_HUMAN_ACTOR_PREFIX) for actor in _actor_strings(verified)):
        return TIER_HUMAN
    return TIER_MACHINE


def _actor_strings(value: Any) -> list[str]:  # noqa: ANN401
    """Collect every string nested anywhere inside a ``verified`` value.

    OKF leaves the ``verified`` shape open — a bare actor id, a list of ids, or
    a list of mappings with ``by`` and ``at`` are all seen in the wild. Rather
    than guess, every leaf string is inspected for the ``human:`` prefix.

    Args:
        value: The raw ``verified`` value.

    Returns:
        Every string leaf, in traversal order.

    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _actor_strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _actor_strings(item)]
    return []


@dataclass(frozen=True)
class Article:
    """An article as the index needs to see it.

    Attributes:
        path: Absolute path to the article.
        rel: POSIX path relative to the wiki root.
        frontmatter: The article's parsed frontmatter.

    """

    path: Path
    rel: str
    frontmatter: fm.Frontmatter

    @property
    def title(self) -> str:
        """The display title, with any leading emoji removed."""
        return split_emoji(self._raw_title)[1]

    @property
    def emoji(self) -> str:
        """The bullet emoji: the title's own, or the default."""
        return split_emoji(self._raw_title)[0]

    @property
    def _raw_title(self) -> str:
        declared = self.frontmatter.get("title")
        if isinstance(declared, str) and declared.strip():
            return declared
        return self.path.stem

    @property
    def description(self) -> str:
        """The one-line summary, or an empty string when undeclared."""
        declared = self.frontmatter.get("description")
        return declared.strip() if isinstance(declared, str) else ""

    @property
    def date_added(self) -> _dt.date | None:
        """The date the article entered the wiki, if declared."""
        return fm.as_date(self.frontmatter.get("date_added"))

    @property
    def tags(self) -> list[str]:
        """Declared tags, as strings."""
        tags = self.frontmatter.get("tags")
        if not isinstance(tags, list):
            return []
        return [str(tag) for tag in tags]

    @property
    def status(self) -> str:
        """The lifecycle status, defaulting to ``stable``."""
        status = self.frontmatter.get("status")
        if isinstance(status, str) and status.strip():
            return status.strip()
        return DEFAULT_STATUS

    @property
    def source_resources(self) -> list[str]:
        """Repo-relative paths of the article's declared sources."""
        return fm.source_resources(self.frontmatter)

    @property
    def tier(self) -> str:
        """The OKF §5.2 trust tier."""
        return trust_tier(self.frontmatter)

    @property
    def sort_key(self) -> tuple[_dt.date, str]:
        """Sort oldest first, then by filename, matching the curated order."""
        return (self.date_added or _dt.date.min, self.path.name)


@dataclass
class DirNode:
    """One directory of the wiki, with its articles and article-bearing children.

    Attributes:
        path: Absolute path to the directory.
        rel: POSIX path relative to the wiki root; ``""`` for the root itself.
        articles: Articles directly inside this directory, in render order.
        children: Child directories that contain at least one article, however
            deeply nested, in render order.

    """

    path: Path
    rel: str
    articles: list[Article] = field(default_factory=list)
    children: list[DirNode] = field(default_factory=list)

    @property
    def article_count(self) -> int:
        """Number of articles in this directory and all its descendants."""
        return len(self.articles) + sum(child.article_count for child in self.children)

    @property
    def name(self) -> str:
        """The directory's own name."""
        return self.path.name

    def walk(self) -> list[DirNode]:
        """Return this node and every descendant, parents before children."""
        nodes = [self]
        for child in self.children:
            nodes.extend(child.walk())
        return nodes

    def all_articles(self) -> list[Article]:
        """Return every article in this subtree, parents before children."""
        found = list(self.articles)
        for child in self.children:
            found.extend(child.all_articles())
        return found


def _discover(wiki_dir: Path) -> config.Config | None:
    """Find the config for the bundle containing a wiki directory.

    Args:
        wiki_dir: Path to the wiki root.

    Returns:
        The bundle's configuration, or ``None`` when the directory is not
        inside a bundle — a fixture wiki in a temporary directory, say, which
        must still render.

    """
    try:
        return config.load(wiki_dir)
    except config.ConfigError:
        return None


def _taxonomy(
    cfg: config.Config | None,
) -> tuple[str, tuple[RootGroup, ...] | None, Mapping[str, str] | None]:
    """Resolve the bundle's title and section taxonomy.

    A bundle that declares no groups or titles falls back to the built-in maps.
    That is safe rather than presumptuous: :func:`_grouped` drops any group
    whose directories are all absent from disk, so defaults naming directories
    another bundle does not have simply leave everything unfiled.

    Args:
        cfg: The bundle's configuration, if it has one.

    Returns:
        The root title, the groups to render, and the per-directory titles.
        Either of the latter two is ``None`` when the default should be used.

    """
    if cfg is None:
        return ROOT_TITLE, None, None
    groups = tuple(RootGroup(g.title, g.directories) for g in cfg.groups) or None
    titles = cfg.directory_titles or None
    return cfg.title, groups, titles


def _root_frontmatter(cfg: config.Config | None) -> dict[str, str]:
    """Build the root index's frontmatter, per OKF §8 and §12.

    The spec versions live in the bundle's config, so the generated index
    cannot drift from what the bundle declares about itself.

    Args:
        cfg: The bundle's configuration, if it has one.

    Returns:
        The ``okf_version`` / ``kb_format`` mapping.

    """
    if cfg is None:
        return dict(ROOT_FRONTMATTER)
    return {"okf_version": cfg.okf_version, "kb_format": cfg.kb_format}


def section_title(rel: str, titles: Mapping[str, str] | None = None) -> str:
    """Return the display title for a wiki directory.

    Args:
        rel: The directory's wiki-relative POSIX path.
        titles: Curated titles from the bundle's config. Defaults to the
            built-in map when the bundle declares none.

    Returns:
        The curated title, or a title-cased fallback derived from the directory
        name.

    """
    titles = SECTION_TITLES if titles is None else titles
    if rel in titles:
        return titles[rel]
    name = rel.rsplit("/", 1)[-1]
    return f"{DIRECTORY_EMOJI} {name.replace('-', ' ').replace('_', ' ').title()}"


def build_tree(wiki_dir: Path) -> DirNode:
    """Scan the wiki into a tree of article-bearing directories.

    Directories with no articles anywhere beneath them are pruned, as are
    hidden and underscore-prefixed directories.

    Args:
        wiki_dir: Path to the wiki root.

    Returns:
        The root node. Its ``rel`` is the empty string.

    Raises:
        FrontmatterError: If any article's frontmatter cannot be parsed.

    """
    return _build_node(wiki_dir, wiki_dir)


def _build_node(path: Path, wiki_dir: Path) -> DirNode:
    """Recursively build one :class:`DirNode`."""
    rel = path.relative_to(wiki_dir).as_posix()
    node = DirNode(path=path, rel="" if rel == "." else rel)

    for md_file in sorted(path.glob("*.md")):
        if not fm.is_article(md_file):
            continue
        document = fm.load(md_file)
        node.articles.append(
            Article(
                path=md_file,
                rel=md_file.relative_to(wiki_dir).as_posix(),
                frontmatter=document.frontmatter,
            ),
        )
    node.articles.sort(key=lambda article: article.sort_key)

    for child_dir in sorted(p for p in path.iterdir() if p.is_dir()):
        if child_dir.name.startswith((".", "_")):
            continue
        child = _build_node(child_dir, wiki_dir)
        if child.article_count:
            node.children.append(child)
    node.children.sort(key=_child_sort_key)

    return node


def _child_sort_key(node: DirNode) -> tuple[_dt.date, str]:
    """Order sibling directories by their earliest article, then by name."""
    dates = [
        article.date_added for article in node.all_articles() if article.date_added
    ]
    return (min(dates) if dates else _dt.date.max, node.name)


def unique_sources(articles: list[Article]) -> list[str]:
    """Return every distinct source resource across a set of articles.

    The same raw file commonly feeds several articles — the CCEP meeting notes
    feed three — so summing the per-article counts overstates how much source
    material the wiki actually rests on.

    Args:
        articles: The articles to survey.

    Returns:
        Distinct ``sources[].resource`` values, sorted.

    """
    return sorted({resource for a in articles for resource in a.source_resources})


def _tag_badges(tags: list[str]) -> list[str]:
    """Render up to :data:`MAX_TAG_BADGES` tag badges."""
    return [
        f"![tag](https://img.shields.io/badge/-{shield_escape(tag)}-"
        f"{TAG_COLOURS[position % len(TAG_COLOURS)]})"
        for position, tag in enumerate(tags[:MAX_TAG_BADGES])
    ]


def _status_badge(status: str) -> str | None:
    """Render a lifecycle badge, or ``None`` when the status is the default."""
    if status == DEFAULT_STATUS:
        return None
    colour = STATUS_COLOURS.get(status, "lightgrey")
    return f"![status](https://img.shields.io/badge/status-{shield_escape(status)}-{colour})"


def render_entry(article: Article, link: str) -> list[str]:
    """Render one article as a two-line index entry.

    Args:
        article: The article to render.
        link: The relative link target to use, e.g. ``./flash-attention-2.md``.

    Returns:
        The entry's lines, without a trailing blank line.

    """
    headline = f"- {article.emoji} [{article.title}]({link})"
    if article.description:
        headline = f"{headline} — {article.description}"

    meta: list[str] = []
    if article.date_added:
        meta.append(f"`{article.date_added.isoformat()}`")
    count = len(article.source_resources)
    meta.append(f"{count} source" if count == 1 else f"{count} sources")

    badges = _tag_badges(article.tags)
    status_badge = _status_badge(article.status)
    if status_badge:
        badges.append(status_badge)
    badges.append(TIER_BADGES[article.tier])
    meta.append(" ".join(badges))

    return [headline, "  " + " · ".join(meta)]


def _render_articles(articles: list[Article], link_prefix: str) -> list[str]:
    """Render a run of entries, separated by blank lines."""
    lines: list[str] = []
    for article in articles:
        filename = article.rel.rsplit("/", 1)[-1]
        lines.extend(render_entry(article, f"{link_prefix}{filename}"))
        lines.append("")
    return lines


def render_subdir_index(
    node: DirNode,
    titles: Mapping[str, str] | None = None,
) -> str:
    """Render the ``INDEX.md`` for one subdirectory.

    Carries no frontmatter: OKF §8 permits it only at the bundle root.

    Args:
        node: The directory to render. Must not be the wiki root.
        titles: Curated directory titles from the bundle's config.

    Returns:
        The complete file text, newline-terminated.

    """
    lines = [f"# {section_title(node.rel, titles)}", ""]

    description = SECTION_DESCRIPTIONS.get(node.rel)
    if description:
        lines.extend([description, ""])

    lines.extend(_render_articles(node.articles, "./"))

    if node.children:
        lines.extend(["## 📁 Subdirectories", ""])
        for child in node.children:
            _, title = split_emoji(section_title(child.rel, titles), default="")
            count = child.article_count
            noun = "article" if count == 1 else "articles"
            lines.append(
                f"- {DIRECTORY_EMOJI} [{title}](./{child.name}/) — {count} {noun}",
            )
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def _render_node_body(
    node: DirNode,
    level: int,
    titles: Mapping[str, str] | None = None,
) -> list[str]:
    """Render a directory's contents for the root index.

    Args:
        node: The directory to render.
        level: Heading level to give this directory's child directories.
        titles: Curated directory titles from the bundle's config.

    Returns:
        The rendered lines, ending with a blank line.

    """
    lines: list[str] = []
    description = SECTION_DESCRIPTIONS.get(node.rel)
    if description:
        lines.extend([description, ""])

    prefix = f"./{node.rel}/" if node.rel else "./"
    lines.extend(_render_articles(node.articles, prefix))

    for child in node.children:
        lines.extend([f"{'#' * level} {section_title(child.rel, titles)}", ""])
        lines.extend(_render_node_body(child, level + 1, titles))
    return lines


def _header_badges(
    article_count: int,
    source_count: int,
    compiled: _dt.date,
    *,
    health_passing: bool,
) -> list[str]:
    """Render the root index's computed badge block."""
    return [
        f"![Articles](https://img.shields.io/badge/articles-{article_count}-blue)",
        f"![Sources](https://img.shields.io/badge/sources-{source_count}-green)",
        _HEALTH_PASSING if health_passing else _HEALTH_UNKNOWN,
        (
            "![Last Compiled](https://img.shields.io/badge/compiled-"
            f"{shield_escape(compiled.isoformat())}-lightgrey)"
        ),
    ]


def _grouped(
    root: DirNode,
    groups_config: tuple[RootGroup, ...] | None = None,
) -> list[tuple[RootGroup, list[DirNode]]]:
    """Pair each root group with its directories, appending anything unfiled.

    Args:
        root: The wiki root node.
        groups_config: Groups declared by the bundle. Defaults to the built-in
            set when the bundle declares none.

    Returns:
        Groups in render order, each with the nodes it covers. Groups whose
        directories are all absent from disk are dropped; directories on disk
        that no group claims are appended in a fallback group, so a new section
        appears in the index rather than vanishing from it.

    """
    by_rel = {node.rel: node for node in root.walk() if node.rel}
    claimed: set[str] = set()
    groups: list[tuple[RootGroup, list[DirNode]]] = []

    for group in ROOT_GROUPS if groups_config is None else groups_config:
        nodes = [by_rel[rel] for rel in group.directories if rel in by_rel]
        claimed.update(descendant.rel for node in nodes for descendant in node.walk())
        if nodes:
            groups.append((group, nodes))

    unfiled = [node for node in root.children if node.rel not in claimed]
    if unfiled:
        groups.append(
            (
                RootGroup(
                    title=FALLBACK_GROUP_TITLE,
                    directories=tuple(node.rel for node in unfiled),
                ),
                unfiled,
            ),
        )
    return groups


def render_root_index(
    root: DirNode,
    compiled: _dt.date,
    *,
    health_passing: bool = False,
    cfg: config.Config | None = None,
) -> str:
    """Render the bundle-root ``wiki/INDEX.md``.

    Args:
        root: The wiki root node.
        compiled: Date to stamp into the ``compiled`` badge.
        health_passing: Whether to claim passing health. Left off unless a real
            ``kb-health`` run has confirmed it — the badge is a claim about the
            wiki, not a decoration.
        cfg: The bundle's configuration, supplying its title, spec versions and
            section taxonomy. Falls back to the built-in defaults when absent.

    Returns:
        The complete file text, newline-terminated.

    """
    title, groups_config, titles = _taxonomy(cfg)
    description = config.DEFAULT_DESCRIPTION if cfg is None else cfg.description
    articles = root.all_articles()
    body = [f"# {title}", ""]
    body.extend(
        _header_badges(
            len(articles),
            len(unique_sources(articles)),
            compiled,
            health_passing=health_passing,
        ),
    )
    body.extend(["", f"{description}\n{ROOT_INTRO_SUFFIX}", ""])

    if root.articles:
        body.extend(["---", "", f"## {FALLBACK_GROUP_TITLE}", ""])
        body.extend(_render_articles(root.articles, "./"))

    for group, nodes in _grouped(root, groups_config):
        body.extend(["---", "", f"## {group.title}", ""])
        if len(nodes) == 1:
            body.extend(_render_node_body(nodes[0], 3, titles))
        else:
            for node in nodes:
                body.extend([f"### {section_title(node.rel, titles)}", ""])
                body.extend(_render_node_body(node, 4, titles))

    body.extend(["---", "", OPERATIONS_SECTION, ""])

    text = "\n".join(body).rstrip("\n") + "\n"
    return fm.dumps(_root_frontmatter(cfg), "\n" + text)


def read_compiled(wiki_dir: Path) -> _dt.date | None:
    """Recover the compile date already stamped into the root index.

    The badge records when the wiki was last *compiled*, not when ``kb-index``
    last ran — and ``kb-index`` runs on every commit via pre-commit. Reading the
    committed value back is what keeps an unrelated commit from restamping it.

    Args:
        wiki_dir: Path to the wiki root.

    Returns:
        The date in the existing badge, or ``None`` if the index is absent or
        carries no readable badge.

    """
    index = wiki_dir / INDEX_FILENAME
    if not index.is_file():
        return None
    match = _COMPILED_BADGE_RE.search(index.read_text(encoding="utf-8"))
    if match is None:
        return None
    try:
        return _dt.date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return None


def build_indexes(
    wiki_dir: Path,
    compiled: _dt.date | None = None,
    *,
    health_passing: bool = False,
    cfg: config.Config | None = None,
) -> dict[Path, str]:
    """Render every index file the wiki should contain.

    Args:
        wiki_dir: Path to the wiki root.
        compiled: Date for the ``compiled`` badge. Defaults to the date already
            stamped in the root index, so a routine regeneration preserves it;
            only an explicit value moves it. Falls back to today for a wiki with
            no index yet.
        health_passing: Whether to claim passing health in the root badge.
        cfg: The bundle's configuration. Discovered from ``wiki_dir`` when
            omitted, and falls back to the built-in defaults outside a bundle,
            so rendering a fixture wiki needs no config file.

    Returns:
        A mapping from index path to its full rendered text, root first.

    Raises:
        FrontmatterError: If any article's frontmatter cannot be parsed.

    """
    if cfg is None:
        cfg = _discover(wiki_dir)
    _, _, titles = _taxonomy(cfg)

    root = build_tree(wiki_dir)
    stamp = compiled or read_compiled(wiki_dir) or _dt.date.today()  # noqa: DTZ011

    rendered: dict[Path, str] = {
        wiki_dir / INDEX_FILENAME: render_root_index(
            root,
            stamp,
            health_passing=health_passing,
            cfg=cfg,
        ),
    }
    for node in root.walk():
        if node.rel:
            rendered[node.path / INDEX_FILENAME] = render_subdir_index(node, titles)
    return rendered


def _without_health_badge(text: str) -> str:
    """Normalise the health badge out of an index for comparison.

    The badge reflects whether ``kb-health`` passed, which is a property of the
    run rather than of the wiki's content. Comparing it would make ``--check``
    report every index stale whenever the committed file records a passing run
    and the check itself was invoked without ``--health-passing``.

    Args:
        text: Rendered index markdown.

    Returns:
        The text with either health badge collapsed to a single placeholder.

    """
    return text.replace(_HEALTH_PASSING, "\x00health\x00").replace(
        _HEALTH_UNKNOWN,
        "\x00health\x00",
    )


def stale_indexes(rendered: dict[Path, str]) -> list[tuple[Path, str]]:
    """Find index files that are missing or no longer match their source.

    The health badge is excluded from the comparison — ``--check`` answers
    "does this index reflect the wiki's current content?", not "did health pass
    on this particular invocation?".

    Args:
        rendered: The mapping returned by :func:`build_indexes`.

    Returns:
        One ``(path, reason)`` pair per out-of-date file, in path order.

    """
    problems: list[tuple[Path, str]] = []
    for path, text in sorted(rendered.items()):
        if not path.is_file():
            problems.append((path, "missing"))
        elif _without_health_badge(
            path.read_text(encoding="utf-8"),
        ) != _without_health_badge(text):
            problems.append((path, "out of date"))
    return problems


def write_indexes(rendered: dict[Path, str]) -> list[Path]:
    """Write index files, skipping those already byte-identical.

    Args:
        rendered: The mapping returned by :func:`build_indexes`.

    Returns:
        The paths actually written, in path order.

    """
    written: list[Path] = []
    for path, text in sorted(rendered.items()):
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written.append(path)
    return written


def _parse_compiled(value: str | None) -> _dt.date | None:
    """Parse the ``--compiled`` option.

    Args:
        value: An ISO ``YYYY-MM-DD`` string, or ``None``.

    Returns:
        The parsed date, or ``None`` when no value was given.

    Raises:
        BadParameter: If the value is not an ISO date.

    """
    if value is None:
        return None
    try:
        return _dt.date.fromisoformat(value)
    except ValueError as exc:
        msg = f"expected YYYY-MM-DD, got {value!r}"
        raise typer.BadParameter(msg) from exc


@app.command()
def main(
    wiki_dir: Annotated[
        Path | None,
        typer.Option(exists=True, help="Wiki directory. Defaults to the bundle's."),
    ] = None,
    check: Annotated[  # noqa: FBT002
        bool,
        typer.Option("--check", help="Do not write; fail if any index is stale."),
    ] = False,
    compiled: Annotated[
        str | None,
        typer.Option(
            help=(
                "Set the compiled badge to this date (YYYY-MM-DD). Without it "
                "the badge is left as it stands."
            ),
        ),
    ] = None,
    stamp_compiled: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--stamp-compiled",
            help=(
                "Move the compiled badge to today. Only /kb:compile should pass "
                "this — every other caller must leave the badge alone."
            ),
        ),
    ] = False,
    health_passing: Annotated[  # noqa: FBT002
        bool,
        typer.Option(
            "--health-passing/--no-health-passing",
            help="Claim passing health. Only pass this after a real kb-health run.",
        ),
    ] = False,
) -> None:
    """Generate the wiki's root and per-directory INDEX.md files.

    The compiled badge is preserved unless ``--compiled`` or ``--stamp-compiled``
    says otherwise, so the routine pre-commit regeneration cannot restamp it.

    Raises:
        BadParameter: If both ``--compiled`` and ``--stamp-compiled`` are given.
        Exit: With status 1 under ``--check`` when an index is missing or stale.

    """
    if stamp_compiled and compiled is not None:
        msg = "pass either --compiled or --stamp-compiled, not both"
        raise typer.BadParameter(msg)

    stamp = _dt.date.today() if stamp_compiled else _parse_compiled(compiled)  # noqa: DTZ011
    rendered = build_indexes(
        config.resolve_dir(wiki_dir, "wiki"),
        stamp,
        health_passing=health_passing,
    )

    if check:
        problems = stale_indexes(rendered)
        if problems:
            typer.echo(f"{len(problems)} index file(s) need regeneration:")
            for path, reason in problems:
                typer.echo(f"  - {path}: {reason}")
            typer.echo("Run `kb-index` to regenerate.")
            raise typer.Exit(1)
        typer.echo(f"All {len(rendered)} index file(s) up to date.")
        return

    written = write_indexes(rendered)
    for path in written:
        typer.echo(f"Wrote {path}")
    typer.echo(
        f"{len(rendered)} index file(s) generated, {len(written)} changed.",
    )


if __name__ == "__main__":
    app()
