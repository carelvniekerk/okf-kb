"""The link graph of a wiki, and ``kb-graph``, which lets an agent walk it.

The generated indexes are a table of contents rendered from the directory
layout, so crawling them only gets an agent as far as a directory listing. The
real structure of a wiki is the relative cross-links in article bodies. This
module turns those into a graph whose most useful edge is the one no index can
give: the backlink.

Nodes are the articles, plus every ``INDEX.md`` as an entry point. Links are
read from every markdown file in the wiki, including ``log.md`` and partials,
because a link from any of them is what keeps an article from being an orphan.

Traversal is undirected, since "how is this connected" does not care which
side wrote the link. It reports ``INDEX.md`` nodes but does not expand through
them unless it starts at one: an index links to every article it lists, so
walking through it would put every article two hops from every other.

There is one graph per bundle. Links are relative paths inside one wiki, so a
union of several bundles would only be a set of disconnected graphs.
"""

from __future__ import annotations

import os
import re
from collections import deque
from dataclasses import dataclass, field

# Typer resolves these annotations at runtime to parse CLI arguments, so
# Path cannot move into a type-checking block.
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import typer

from okf_kb import config, frontmatter, links
from okf_kb.frontmatter import is_article
from okf_kb.index_gen import INDEX_FILENAME, Article

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

app = typer.Typer(help="Walk the link graph of the knowledge base wiki.")

#: Headings in the root index that open a section: ``##`` to ``####``.
_HEADING_RE = re.compile(r"^(#{2,4})\s+(.+?)\s*$")


class GraphError(ValueError):
    """Raised when a path cannot be placed in the graph."""


@dataclass(frozen=True)
class Node:
    """One article or index in the graph.

    ``out`` and ``inbound`` keep one entry per link occurrence, in scan order,
    so link counts come straight from their lengths. ``out`` includes targets
    that are not nodes, such as ``raw/`` sources and broken links; ``inbound``
    may name files that are not nodes, such as ``log.md``.

    Attributes:
        path: Absolute path.
        rel: Path relative to the wiki.
        bundle: Name of the bundle the node belongs to.
        title: Display title, with any leading emoji removed; the file stem
            when none is declared.
        type: The OKF ``type``, if declared.
        description: The one-line summary, if declared.
        tags: Declared tags.
        status: Lifecycle status, ``stable`` when undeclared.
        tier: OKF trust tier, derived from ``verified``.
        out: Absolute targets of this node's links to markdown files.
        inbound: Absolute paths of the files linking here.
        indexes: The ``INDEX.md`` files that list this node.

    """

    path: Path
    rel: Path
    bundle: str
    title: str
    type: str | None
    description: str | None
    tags: tuple[str, ...]
    status: str
    tier: str
    out: tuple[Path, ...]
    inbound: tuple[Path, ...]
    indexes: tuple[Path, ...]

    @property
    def is_index(self) -> bool:
        """Whether this node is an ``INDEX.md`` entry point."""
        return self.path.name == INDEX_FILENAME


@dataclass(frozen=True)
class Section:
    """A heading of the root ``INDEX.md`` and the files listed beneath it.

    Attributes:
        bundle: Name of the bundle.
        title: The heading text.
        level: Heading level, 2 to 4.
        entries: Absolute paths of the markdown files linked under the heading
            and before the next one, in order, without repeats.

    """

    bundle: str
    title: str
    level: int
    entries: tuple[Path, ...]


@dataclass
class _Scan:
    """Mutable accumulators used while building a graph."""

    out: dict[Path, list[Path]] = field(default_factory=dict)
    inbound: dict[Path, list[Path]] = field(default_factory=dict)
    broken: list[tuple[Path, str]] = field(default_factory=list)


class Graph:
    """The link graph of one bundle's wiki."""

    def __init__(
        self,
        bundle: str,
        wiki: Path,
        root: Path,
        nodes: dict[Path, Node],
        broken: Sequence[tuple[Path, str]],
    ) -> None:
        """Hold an already-scanned graph. Use :meth:`build` or :meth:`from_wiki`.

        Args:
            bundle: The bundle's name.
            wiki: The resolved wiki directory.
            root: The resolved bundle root.
            nodes: Every node, keyed by absolute path.
            broken: ``(source, raw target)`` for each link to a missing file.

        """
        self.bundle = bundle
        self.wiki = wiki
        self.root = root
        self._nodes = nodes
        self._broken = tuple(broken)

    @classmethod
    def build(cls, bundle: config.Bundle) -> Graph:
        """Scan the wiki of a resolved bundle.

        Args:
            bundle: The bundle.

        Returns:
            Its graph.

        """
        return cls.from_wiki(bundle.config.wiki, bundle.name, bundle.config.root)

    @classmethod
    def from_wiki(
        cls,
        wiki: Path,
        bundle: str = "",
        root: Path | None = None,
    ) -> Graph:
        """Scan a wiki directory that need not belong to a configured bundle.

        Args:
            wiki: The wiki directory.
            bundle: Name to record on each node.
            root: The bundle root, for resolving root-relative paths. Defaults
                to the wiki's parent.

        Returns:
            The graph.

        """
        wiki = wiki.resolve()
        root = (root or wiki.parent).resolve()
        sources = sorted(wiki.rglob("*.md"))
        node_paths = [p for p in sources if _is_node(p)]
        members = set(node_paths)

        scan = _Scan(
            out={p: [] for p in node_paths},
            inbound={p: [] for p in node_paths},
        )
        for source in sources:
            for link in links.outgoing(source):
                if source in members:
                    scan.out[source].append(link.target)
                if link.target in members:
                    scan.inbound[link.target].append(source)
                if not link.target.exists():
                    scan.broken.append((source, link.raw))

        nodes = {
            path: _make_node(path, wiki, bundle, scan.out[path], scan.inbound[path])
            for path in node_paths
        }
        return cls(bundle, wiki, root, nodes, scan.broken)

    def canonical(self, path: Path | str) -> Path:
        """Turn an absolute, root-relative or wiki-relative path into an absolute one.

        A relative path is tried against the bundle root first and the wiki
        second, so ``wiki/a.md`` and ``a.md`` name the same file.

        Args:
            path: The path as a user or agent wrote it.

        Returns:
            The absolute path, which lies inside the wiki but need not exist.

        Raises:
            GraphError: If no reading of the path lies inside the wiki.

        """
        given = Path(path).expanduser()
        candidates = (
            [given] if given.is_absolute() else [self.root / given, self.wiki / given]
        )
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved == self.wiki or self.wiki in resolved.parents:
                return resolved
        name = self.bundle or "this bundle"
        msg = f"{path} is not inside the wiki of {name} ({self.wiki})"
        raise GraphError(msg)

    def has(self, path: Path | str) -> bool:
        """Whether a path names a node of this graph.

        Args:
            path: The path in any form :meth:`canonical` accepts.

        Returns:
            ``True`` when it resolves to a node.

        """
        try:
            return self.canonical(path) in self._nodes
        except GraphError:
            return False

    def node(self, path: Path | str) -> Node:
        """Look up one node.

        Args:
            path: The path in any form :meth:`canonical` accepts.

        Returns:
            The node.

        Raises:
            GraphError: If the path is outside the wiki or is not a node.

        """
        resolved = self.canonical(path)
        if resolved not in self._nodes:
            msg = f"{self.display(resolved)} is not an article or index in {self.wiki}"
            raise GraphError(msg)
        return self._nodes[resolved]

    def nodes(self) -> tuple[Node, ...]:
        """Every node, in path order.

        Returns:
            The nodes.

        """
        return tuple(self._nodes.values())

    def display(self, path: Path) -> str:
        """Express a path relative to the wiki, for output.

        Args:
            path: An absolute path.

        Returns:
            A POSIX path relative to the wiki. Targets outside it, such as
            ``raw/`` sources, come out with leading ``../``.

        """
        return Path(os.path.relpath(path, self.wiki)).as_posix()

    def roots(self) -> tuple[Section, ...]:
        """Read the sections of the root ``INDEX.md``.

        This parses the file on disk, so it reports what a reader of the index
        sees. A wiki that has never been indexed has no sections.

        Returns:
            One section per ``##`` to ``####`` heading, in document order.

        """
        index = self.wiki / INDEX_FILENAME
        if not index.is_file():
            return ()
        _, body = _tolerant_split(index.read_text(encoding="utf-8"))

        sections: list[tuple[str, int, list[Path]]] = []
        for line in body.splitlines():
            heading = _HEADING_RE.match(line)
            if heading:
                sections.append((heading.group(2), len(heading.group(1)), []))
                continue
            if not sections:
                continue
            entries = sections[-1][2]
            for target in links.internal_targets(line):
                resolved = links.resolve(target, index)
                if resolved not in entries:
                    entries.append(resolved)
        return tuple(
            Section(self.bundle, title, level, tuple(entries))
            for title, level, entries in sections
        )

    def neighbours(
        self,
        path: Path | str,
        depth: int = 2,
    ) -> tuple[tuple[Node, int], ...]:
        """Find the nodes within ``depth`` links of a node, in either direction.

        Args:
            path: The starting node.
            depth: Maximum number of hops, at least 1.

        Returns:
            ``(node, distance)`` pairs, nearest first and then in path order,
            excluding the start.

        Raises:
            GraphError: If ``depth`` is below 1 or the start is not a node.

        """
        if depth < 1:
            msg = f"depth must be at least 1, got {depth}"
            raise GraphError(msg)
        start = self.node(path).path
        distances = self._bfs(start, depth)
        del distances[start]
        found = [(self._nodes[p], d) for p, d in distances.items()]
        return tuple(sorted(found, key=lambda pair: (pair[1], pair[0].rel)))

    def shortest_path(self, a: Path | str, b: Path | str) -> tuple[Node, ...] | None:
        """Find a shortest chain of links between two nodes, in either direction.

        Args:
            a: One end.
            b: The other end.

        Returns:
            The nodes along the path, ``a`` first and ``b`` last, or ``None``
            when they are not connected.

        Raises:
            GraphError: If either end is not a node.

        """
        start, goal = self.node(a).path, self.node(b).path
        previous: dict[Path, Path | None] = {start: None}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            if current == goal:
                chain: list[Node] = []
                step: Path | None = current
                while step is not None:
                    chain.append(self._nodes[step])
                    step = previous[step]
                return tuple(reversed(chain))
            if current != start and self._nodes[current].is_index:
                continue
            for neighbour in self._adjacent(current):
                if neighbour not in previous:
                    previous[neighbour] = current
                    queue.append(neighbour)
        return None

    def orphans(self) -> tuple[Node, ...]:
        """Find articles nothing links to.

        Returns:
            Article nodes with no inbound link from any markdown file, in path
            order. Index nodes are never orphans.

        """
        return tuple(
            n for n in self._nodes.values() if not n.is_index and not n.inbound
        )

    def broken(self) -> tuple[tuple[Path, str], ...]:
        """Find links to markdown files that do not exist.

        Returns:
            ``(source file, target as written)`` pairs, in scan order. The
            source may be any markdown file in the wiki, not only a node.

        """
        return self._broken

    def _adjacent(self, path: Path) -> Iterable[Path]:
        """Yield the nodes one link away from a node, in either direction.

        Args:
            path: A node's path.

        Yields:
            Neighbouring node paths, each once, outgoing first.

        """
        node = self._nodes[path]
        seen: set[Path] = set()
        for other in (*node.out, *node.inbound):
            if other in self._nodes and other not in seen:
                seen.add(other)
                yield other

    def _bfs(self, start: Path, depth: int) -> dict[Path, int]:
        """Breadth-first search that does not expand through index nodes.

        Args:
            start: The starting node's path. It is always expanded, even when
                it is an index.
            depth: Maximum number of hops.

        Returns:
            Distance from ``start`` for every node reached, the start included.

        """
        distances = {start: 0}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            distance = distances[current]
            if distance == depth:
                continue
            if current != start and self._nodes[current].is_index:
                continue
            for neighbour in self._adjacent(current):
                if neighbour not in distances:
                    distances[neighbour] = distance + 1
                    queue.append(neighbour)
        return distances


def locate(graphs: Sequence[Graph], path: Path | str) -> tuple[Graph, Node]:
    """Find which of several graphs a path names a node in.

    Args:
        graphs: The graphs in scope.
        path: The path in any form :meth:`Graph.canonical` accepts.

    Returns:
        The graph and the node.

    Raises:
        GraphError: If no graph has the node, or more than one does.

    """
    matches = [g for g in graphs if g.has(path)]
    if len(matches) == 1:
        return matches[0], matches[0].node(path)
    if not matches:
        wikis = ", ".join(f"{g.bundle} ({g.wiki})" for g in graphs)
        msg = f"{path} is not an article or index in any wiki in scope: {wikis}"
        raise GraphError(msg)
    names = ", ".join(g.bundle for g in matches)
    msg = f"{path} exists in more than one bundle ({names}); narrow with --kb"
    raise GraphError(msg)


def _is_node(path: Path) -> bool:
    """Whether a markdown file becomes a node.

    Args:
        path: A markdown file in the wiki.

    Returns:
        ``True`` for articles and for ``INDEX.md`` files.

    """
    return is_article(path) or path.name == INDEX_FILENAME


def _tolerant_split(text: str) -> tuple[frontmatter.Frontmatter, str]:
    """Split frontmatter from body, treating a malformed block as absent.

    ``kb-health`` reports malformed frontmatter; the graph only needs to keep
    going past it.

    Args:
        text: Markdown text.

    Returns:
        The frontmatter mapping and the body.

    """
    try:
        return frontmatter.parse(text)
    except frontmatter.FrontmatterError:
        return {}, text


def _make_node(
    path: Path,
    wiki: Path,
    bundle: str,
    out: list[Path],
    inbound: list[Path],
) -> Node:
    """Build a node, reading its metadata through ``index_gen.Article``.

    Args:
        path: The file.
        wiki: The resolved wiki directory.
        bundle: The bundle's name.
        out: Targets of its links.
        inbound: Files linking to it.

    Returns:
        The node.

    """
    fm, _ = _tolerant_split(path.read_text(encoding="utf-8"))
    rel = path.relative_to(wiki)
    article = Article(path=path, rel=rel.as_posix(), frontmatter=fm)
    declared_type = fm.get("type")
    return Node(
        path=path,
        rel=rel,
        bundle=bundle,
        title=article.title,
        type=declared_type if isinstance(declared_type, str) else None,
        description=article.description or None,
        tags=tuple(article.tags),
        status=article.status,
        tier=article.tier,
        out=tuple(out),
        inbound=tuple(inbound),
        indexes=tuple(dict.fromkeys(p for p in inbound if p.name == INDEX_FILENAME)),
    )


# -- CLI -----------------------------------------------------------------------

KbOption = Annotated[
    list[str] | None,
    typer.Option(
        "--kb",
        help="Knowledge base to walk: a name, a path, or 'all'. Repeatable.",
    ),
]
JsonOption = Annotated[
    bool,
    typer.Option("--json-output/--no-json-output", help="Output as JSON."),
]


def _graphs(kb: list[str] | None) -> list[Graph]:
    """Build one graph per bundle in scope, exiting cleanly on a config error.

    Args:
        kb: Values of ``--kb``.

    Returns:
        The graphs.

    Raises:
        Exit: With status 1 when no bundle can be resolved.

    """
    try:
        return [Graph.build(bundle) for bundle in config.resolve_roots(kb)]
    except config.ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc


def _fail(exc: GraphError) -> typer.Exit:
    """Report a graph error and build the exit to raise.

    Args:
        exc: The error.

    Returns:
        An exit with status 1.

    """
    typer.echo(f"error: {exc}", err=True)
    return typer.Exit(1)


def _node_json(graph: Graph, node: Node) -> dict[str, Any]:
    """Serialise a node with wiki-relative paths and no repeated links.

    Args:
        graph: The node's graph, for path display.
        node: The node.

    Returns:
        A JSON-ready mapping.

    """
    return {
        "bundle": node.bundle,
        "path": str(node.path),
        "rel": node.rel.as_posix(),
        "title": node.title,
        "type": node.type,
        "description": node.description,
        "tags": list(node.tags),
        "status": node.status,
        "tier": node.tier,
        "out": [graph.display(p) for p in dict.fromkeys(node.out)],
        "inbound": [graph.display(p) for p in dict.fromkeys(node.inbound)],
        "indexes": [graph.display(p) for p in node.indexes],
    }


def _emit(payload: object) -> None:
    """Print a payload as indented JSON.

    Args:
        payload: A JSON-ready value.

    """
    import json  # noqa: PLC0415

    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


@app.command()
def roots(kb: KbOption = None, json_output: JsonOption = False) -> None:  # noqa: FBT002
    """List each bundle's root index sections and the files under them."""
    graphs = _graphs(kb)
    if json_output:
        _emit(
            [
                {
                    "bundle": g.bundle,
                    "sections": [
                        {
                            "title": s.title,
                            "level": s.level,
                            "entries": [g.display(p) for p in s.entries],
                        }
                        for s in g.roots()
                    ],
                }
                for g in graphs
            ],
        )
        return
    for graph in graphs:
        typer.echo(f"{graph.bundle}  {graph.wiki}")
        sections = graph.roots()
        if not sections:
            typer.echo(f"  (no sections: {INDEX_FILENAME} is missing or empty)")
        for section in sections:
            indent = "  " * (section.level - 1)
            typer.echo(f"{indent}{'#' * section.level} {section.title}")
            for entry in section.entries:
                typer.echo(f"{indent}  {graph.display(entry)}")


@app.command()
def node(
    path: Annotated[str, typer.Argument(help="Absolute, bundle- or wiki-relative.")],
    kb: KbOption = None,
    json_output: JsonOption = False,  # noqa: FBT002
) -> None:
    """Show one article's metadata, links out, backlinks and indexes.

    Raises:
        Exit: With status 1 when the path is not a node in scope.

    """
    try:
        graph, found = locate(_graphs(kb), path)
    except GraphError as exc:
        raise _fail(exc) from exc
    data = _node_json(graph, found)
    if json_output:
        _emit(data)
        return
    typer.echo(f"{data['title']}  [{data['bundle']}] {data['rel']}")
    typer.echo(
        f"  type: {data['type']}  status: {data['status']}  tier: {data['tier']}",
    )
    if data["description"]:
        typer.echo(f"  {data['description']}")
    for label in ("out", "inbound", "indexes"):
        typer.echo(f"  {label}:")
        for item in data[label]:
            typer.echo(f"    {item}")


@app.command()
def neighbours(
    paths: Annotated[list[str], typer.Argument(help="One or more starting nodes.")],
    depth: Annotated[int, typer.Option(min=1, help="Maximum number of hops.")] = 2,
    kb: KbOption = None,
    json_output: JsonOption = False,  # noqa: FBT002
) -> None:
    """List the nodes within --depth links of the given ones, nearest first.

    Links are followed in both directions, so backlinks count. Index files are
    reported but not walked through.

    Raises:
        Exit: With status 1 when a path is not a node in scope.

    """
    graphs = _graphs(kb)
    best: dict[Path, tuple[Graph, Node, int]] = {}
    starts: set[Path] = set()
    try:
        for path in paths:
            graph, start = locate(graphs, path)
            starts.add(start.path)
            for found, distance in graph.neighbours(start.path, depth):
                current = best.get(found.path)
                if current is None or distance < current[2]:
                    best[found.path] = (graph, found, distance)
    except GraphError as exc:
        raise _fail(exc) from exc

    ordered = sorted(
        (entry for key, entry in best.items() if key not in starts),
        key=lambda e: (e[2], e[1].bundle, e[1].rel),
    )
    if json_output:
        _emit([{**_node_json(g, n), "distance": d} for g, n, d in ordered])
        return
    for _, found, distance in ordered:
        typer.echo(
            f"{distance}  [{found.bundle}] {found.rel.as_posix()}  {found.title}",
        )


@app.command("shortest-path")
def shortest_path(
    a: Annotated[str, typer.Argument(help="One end.")],
    b: Annotated[str, typer.Argument(help="The other end.")],
    kb: KbOption = None,
    json_output: JsonOption = False,  # noqa: FBT002
) -> None:
    """Show a shortest chain of links between two articles, in either direction.

    Raises:
        Exit: With status 1 when an end is not a node in scope, or the two ends
            are in different bundles.

    """
    graphs = _graphs(kb)
    try:
        graph_a, node_a = locate(graphs, a)
        graph_b, node_b = locate(graphs, b)
    except GraphError as exc:
        raise _fail(exc) from exc
    if graph_a is not graph_b:
        typer.echo(
            f"error: different bundles: {a} is in {graph_a.bundle}, "
            f"{b} is in {graph_b.bundle}; links never cross bundles",
            err=True,
        )
        raise typer.Exit(1)

    chain = graph_a.shortest_path(node_a.path, node_b.path)
    rels = None if chain is None else [n.rel.as_posix() for n in chain]
    if json_output:
        _emit({"bundle": graph_a.bundle, "path": rels})
        return
    if rels is None:
        typer.echo(f"no path between {a} and {b}")
        return
    typer.echo(" -> ".join(rels))


if __name__ == "__main__":
    app()
