"""Tests for ``kb-mcp``, the wiki tools as an MCP server.

Two contracts matter. The server must stay read-only and confined to the wikis
in scope, since the desktop app reaches it with no bundle to stand in; so the
refusals from ``kb-read`` must survive the move to MCP as tool errors rather
than as reads. And the ``wiki`` skill, the server's instructions and the tool
list must describe one set of tools: the skill is prose, so nothing else
notices when a tool is renamed underneath it.
"""

# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

import re
from pathlib import Path

import anyio
import pytest
import yaml
from mcp import Client
from mcp.types import CallToolResult, TextContent, Tool

from okf_kb import config, mcp_server

SKILL = (
    Path(__file__).parents[1] / "plugins" / "kb-query" / "skills" / "wiki" / "SKILL.md"
)

#: Claude Code's name for a tool of a server shipped in a plugin's .mcp.json.
PLUGIN_PREFIX = f"mcp__plugin_kb-query_{mcp_server.SERVER_NAME}__"

EXPECTED_TOOLS = {"bundles", "search", "neighbours", "roots", "shortest_path", "read"}


def _call(name: str, arguments: dict | None = None) -> CallToolResult:
    async def go() -> CallToolResult:
        async with Client(mcp_server.server) as client:
            return await client.call_tool(name, arguments or {})

    return anyio.run(go)


def _tools() -> list[Tool]:
    async def go() -> list[Tool]:
        async with Client(mcp_server.server) as client:
            return (await client.list_tools()).tools

    return anyio.run(go)


def _text(result) -> str:
    return "".join(b.text for b in result.content if isinstance(b, TextContent))


def _write(wiki: Path, rel: str, text: str) -> None:
    path = wiki / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _article(title: str, body: str) -> str:
    return f"---\ntype: concept\ntitle: {title}\n---\n\n# {title}\n\n{body}\n"


@pytest.fixture
def scope(tmp_path, monkeypatch) -> Path:
    """Two bundles named by a project file; ``a.md`` exists in both."""
    kb = tmp_path / "kb"
    _write(kb / "wiki", "a.md", _article("Alpha", "Speculative decoding. [b](./b.md)"))
    _write(kb / "wiki", "b.md", _article("Beta", "Draft models. [c](./c.md)"))
    _write(kb / "wiki", "c.md", _article("Gamma", "Verification."))
    (kb / "okf.toml").write_text("", encoding="utf-8")
    other = tmp_path / "other"
    _write(other / "wiki", "a.md", _article("Other alpha", "Unrelated."))
    (other / "okf.toml").write_text("", encoding="utf-8")
    (tmp_path / "secret.md").write_text("secret\n", encoding="utf-8")

    project = tmp_path / "project"
    project.mkdir()
    (project / config.PROJECT_FILENAME).write_text(
        f'[paths]\nkb = "{kb}"\nother = "{other}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv(config.ENV_ROOT, raising=False)
    monkeypatch.chdir(project)
    return tmp_path


# -- the tool set ----------------------------------------------------------------


def test_every_tool_is_read_only():
    tools = _tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True, tool.name
        assert tool.annotations.destructive_hint is False, tool.name


def test_the_instructions_name_every_tool_the_procedure_uses():
    named = set(re.findall(r"`(\w+)`", mcp_server.INSTRUCTIONS))
    assert EXPECTED_TOOLS - {"shortest_path"} <= named


def test_the_skill_grants_exactly_the_server_tools():
    text = SKILL.read_text(encoding="utf-8")
    meta = yaml.safe_load(text.split("---", 2)[1])
    granted = meta["allowed-tools"].split()
    assert set(granted) == {PLUGIN_PREFIX + name for name in EXPECTED_TOOLS}


def test_the_skill_names_every_tool_and_no_kb_command():
    body = SKILL.read_text(encoding="utf-8").split("---", 2)[2]
    for name in EXPECTED_TOOLS:
        assert f"`{name}`" in body, name
    assert not re.search(r"\bkb-(search|graph|read|doctor)\b", body)


# -- scope -----------------------------------------------------------------------


def test_no_scope_is_a_state_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv(config.ENV_ROOT, raising=False)
    monkeypatch.chdir(tmp_path)
    result = _call("bundles")
    assert not result.is_error
    assert result.structured_content["bundles"] == []
    assert result.structured_content["searched"]


@pytest.mark.usefixtures("scope")
def test_bundles_lists_the_project_scope():
    result = _call("bundles")
    names = {b["name"] for b in result.structured_content["bundles"]}
    assert names == {"kb", "other"}


@pytest.mark.usefixtures("scope")
def test_an_unknown_kb_is_a_tool_error_naming_it():
    result = _call("search", {"query": "x", "kb": ["nope"]})
    assert result.is_error
    assert "nope" in _text(result)


# -- search, graph, read ---------------------------------------------------------


@pytest.mark.usefixtures("scope")
def test_search_carries_what_read_needs():
    result = _call("search", {"query": "speculative decoding"})
    assert not result.is_error
    top = result.structured_content["results"][0]
    assert (top["bundle"], top["rel"]) == ("kb", "a.md")


@pytest.mark.usefixtures("scope")
def test_neighbours_follow_backlinks():
    result = _call("neighbours", {"paths": ["b.md"], "kb": ["kb"]})
    found = {n["rel"] for n in result.structured_content["neighbours"]}
    assert found == {"a.md", "c.md"}


@pytest.mark.usefixtures("scope")
def test_shortest_path_across_bundles_is_a_tool_error(scope):
    result = _call(
        "shortest_path",
        {
            "a": str(scope / "kb" / "wiki" / "c.md"),
            "b": str(scope / "other" / "wiki" / "a.md"),
        },
    )
    assert result.is_error
    assert "different bundles" in _text(result)


@pytest.mark.usefixtures("scope")
def test_read_heads_the_text_with_bundle_and_path():
    result = _call("read", {"path": "a.md", "kb": ["kb"], "strip_frontmatter": True})
    assert not result.is_error
    assert _text(result).startswith("==> kb: a.md <==\n# Alpha")


@pytest.mark.usefixtures("scope")
def test_read_of_a_path_in_two_bundles_asks_for_kb():
    result = _call("read", {"path": "a.md"})
    assert result.is_error
    assert "more than one bundle" in _text(result)


@pytest.mark.usefixtures("scope")
@pytest.mark.parametrize("path", ["../../secret.md", "../secret.md"])
def test_read_refuses_traversal_out_of_the_wiki(path):
    result = _call("read", {"path": path, "kb": ["kb"]})
    assert result.is_error
    assert "==>" not in _text(result)


@pytest.mark.usefixtures("scope")
def test_read_refuses_an_absolute_path_outside_the_wiki(scope):
    result = _call("read", {"path": str(scope / "secret.md"), "kb": ["kb"]})
    assert result.is_error
    assert "not a file inside any wiki" in _text(result)
