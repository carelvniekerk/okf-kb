"""``kb-mcp``: the read-only wiki tools as a stdio MCP server.

The ``kb-query`` plugin's ``wiki`` skill calls these tools rather than the
``kb-*`` commands, so the same skill runs in Claude Code and in the Claude
desktop app. Desktop chat runs skills in a cloud sandbox with neither the
package nor the bundles on disk, and reaches local capabilities only through
MCP servers it launches itself.

Every tool wraps the function its CLI command calls, so the two cannot drift.
Scope resolves per call through :func:`config.resolve_roots`, from the
server's working directory: Claude Code starts it in the project, where walk-up
and ``.okf-kb.toml`` apply, while the desktop app starts it outside any
project, which leaves only the user config. Nothing here writes, and no tool
may: a writing tool here would reach bundles the user is not standing in,
which the ``--kb`` rule forbids for the CLI.
"""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from okf_kb import config, doctor, graph, read
from okf_kb import search as search_mod

#: Registered name. The plugin's ``.mcp.json`` and the desktop config use it
#: too, and Claude Code derives the tool names in ``SKILL.md`` from it.
SERVER_NAME = "okf-kb"

#: Most articles the procedure reads per question.
READ_LIMIT = 10

INSTRUCTIONS = f"""\
Read-only access to the user's Open Knowledge Format knowledge bases (wikis).
Check them before answering from training data whenever a question may touch
something the user has written down, researched or discussed.

Call `bundles` first, once per conversation. An empty list means no knowledge
base is in scope: say so in one line and answer without it. Then `search`. If
one hit clearly answers the question, `read` it and stop. Otherwise use
`neighbours` on the top hits and `roots` for the taxonomy, then `read` what you
select, at most {READ_LIMIT} articles. Report paths grouped by bundle and say
whether coverage is sufficient or where the gaps are. If the wiki has nothing,
say so; do not fill the gap from training data and present it as the wiki's.

Tool errors are written for the user: relay them verbatim, and never compose an
install or configuration command.
"""

server = MCPServer(SERVER_NAME, instructions=INSTRUCTIONS)

_READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

Kb = Annotated[
    list[str] | None,
    Field(
        description="Knowledge bases to use: names, paths, or 'all'. Omit for "
        "the default scope, which `bundles` reports.",
    ),
]


def _bundles(kb: list[str] | None) -> tuple[config.Bundle, ...]:
    """Resolve the bundles in scope, as a tool error when that fails.

    Args:
        kb: Explicit bundles, or ``None`` for the default scope.

    Returns:
        The bundles.

    Raises:
        ToolError: If the configuration is broken or nothing is in scope.

    """
    try:
        return config.resolve_roots(kb)
    except config.ConfigError as exc:
        raise ToolError(str(exc)) from exc


def _graphs(kb: list[str] | None) -> list[graph.Graph]:
    """Build one link graph per bundle in scope.

    Args:
        kb: Explicit bundles, or ``None`` for the default scope.

    Returns:
        The graphs.

    """
    return [graph.Graph.build(b) for b in _bundles(kb)]


@server.tool(title="List knowledge bases in scope", annotations=_READ_ONLY)
def bundles(kb: Kb = None) -> dict[str, Any]:
    """List the knowledge bases in scope. Call this first, once.

    Each entry has `name`, `path`, `source` (`walk-up` means the session is
    inside that bundle) and `articles`. An empty `bundles` list is not an
    error: `searched` says where the server looked.
    """
    try:
        return doctor.scope_report(kb)
    except config.ConfigError as exc:
        raise ToolError(str(exc)) from exc


@server.tool(title="Search the wiki", annotations=_READ_ONLY)
def search(  # noqa: PLR0913, PLR0917
    query: Annotated[str, Field(description="Search terms.")],
    kb: Kb = None,
    top_k: Annotated[int, Field(ge=1, le=50, description="Results.")] = 5,
    tag: Annotated[str | None, Field(description="Only this tag.")] = None,
    article_type: Annotated[
        str | None,
        Field(description="Only this OKF type, e.g. concept or paper-summary."),
    ] = None,
    titles_only: Annotated[  # noqa: FBT002
        bool,
        Field(description="Rank on titles alone: a cheap first probe."),
    ] = False,
    include_deprecated: Annotated[  # noqa: FBT002
        bool,
        Field(description="Keep articles marked status: deprecated."),
    ] = False,
) -> dict[str, Any]:
    """BM25 search across the wikis in scope, ranked as one corpus.

    Call before answering from training data. Each result carries `bundle`,
    `rel`, `title`, `description`, `score` and a `snippet`; pass `rel` and
    `bundle` to `read`.
    """
    results = search_mod.search(
        query,
        _bundles(kb),
        top_k,
        filter_tag=tag,
        filter_type=article_type,
        include_deprecated=include_deprecated,
        fields=search_mod.Field.TITLE if titles_only else search_mod.Field.BODY,
    )
    return {"results": results}


@server.tool(title="Follow links and backlinks", annotations=_READ_ONLY)
def neighbours(
    paths: Annotated[
        list[str],
        Field(min_length=1, description="Starting articles, as `rel` paths."),
    ],
    kb: Kb = None,
    depth: Annotated[int, Field(ge=1, le=3, description="Hops.")] = 1,
) -> dict[str, Any]:
    """List the articles within `depth` links of the given ones, either way.

    Use when search hits are several and mediocre, or the question asks how
    things relate. Each entry has `distance`, `out` (links it makes) and
    `inbound` (backlinks). Index files are reported but not walked through.
    """
    try:
        return {"neighbours": graph.neighbours_payload(_graphs(kb), paths, depth)}
    except graph.GraphError as exc:
        raise ToolError(str(exc)) from exc


@server.tool(title="List index sections", annotations=_READ_ONLY)
def roots(kb: Kb = None) -> dict[str, Any]:
    """List each wiki's root index sections and the articles filed under them.

    Use to place search hits in a bundle's taxonomy.
    """
    return {"bundles": graph.roots_payload(_graphs(kb))}


@server.tool(title="Connect two articles", annotations=_READ_ONLY)
def shortest_path(
    a: Annotated[str, Field(description="One article, as a `rel` path.")],
    b: Annotated[str, Field(description="The other, in the same bundle.")],
    kb: Kb = None,
) -> dict[str, Any]:
    """Find a shortest chain of links between two articles of one bundle.

    `hops` gives each link's direction: `forward` when the earlier article
    links to the later, `backward` for a backlink, `both` for each. `path` is
    null when the two are not connected.
    """
    try:
        return graph.shortest_path_payload(_graphs(kb), a, b)
    except graph.GraphError as exc:
        raise ToolError(str(exc)) from exc


@server.tool(name="read", title="Read an article", annotations=_READ_ONLY)
def read_article(
    path: Annotated[str, Field(description="The `rel` path from a result.")],
    kb: Kb = None,
    section: Annotated[
        str | None,
        Field(description='Return only this section, e.g. "## Sources".'),
    ] = None,
    strip_frontmatter: Annotated[  # noqa: FBT002
        bool,
        Field(description="Drop the YAML frontmatter."),
    ] = False,
) -> str:
    """Read one wiki article, or one section of it.

    Pass the result's `bundle` as `kb` when the same path could exist in more
    than one bundle. Refuses anything that is not a markdown file inside a wiki
    in scope.
    """
    try:
        bundle, rel, text = read.read_article(
            path,
            _bundles(kb),
            section,
            strip_frontmatter,
        )
    except read.ReadError as exc:
        raise ToolError(str(exc)) from exc
    return f"==> {bundle.name}: {rel} <==\n{text.rstrip()}"


def main() -> None:
    """Serve the tools over stdio until the client disconnects."""
    server.run("stdio")


if __name__ == "__main__":
    main()
