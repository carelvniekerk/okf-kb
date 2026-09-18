"""Tests for the wiki link graph and ``kb-graph``.

The fixture is five articles with one cycle and one orphan, which is enough to
pin down what an index cannot provide: backlinks, depth-limited neighbourhoods
and shortest paths. The rule most likely to regress is that traversal does not
expand through ``INDEX.md``, since an index links to every article it lists and
would collapse every neighbourhood into the whole wiki.
"""

# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from okf_kb import config, graph

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

ROOT_INDEX = """\
---
okf_version: "0.2"
---

# Test wiki

![Articles](https://img.shields.io/badge/articles-5-blue)

---

## Research

- 📄 [Alpha](./a.md) — first
- 📄 [Beta](./b.md)

### Sub

- 📄 [Gamma](./c.md)

## Tools

- 📄 [Delta](./d.md)
- 📄 [Delta again](./d.md)

## 📜 Operations

- [Operations Log](./log.md)
"""


def _write(wiki: Path, rel: str, text: str) -> None:
    path = wiki / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _article(title: str, body: str, extra: str = "") -> str:
    return f"---\ntype: concept\ntitle: {title}\n{extra}---\n\n# {title}\n\n{body}\n"


@pytest.fixture
def wiki(tmp_path) -> Path:
    """Five articles: a -> b -> c -> a is a cycle, c -> d, and e is an orphan."""
    wiki = tmp_path / "kb" / "wiki"
    _write(wiki, "INDEX.md", ROOT_INDEX)
    _write(
        wiki,
        "a.md",
        _article("🧪 Alpha", "See [b](./b.md) and [raw](../raw/src.md)."),
    )
    _write(wiki, "b.md", _article("Beta", "On to [c](./c.md#part)."))
    _write(
        wiki,
        "c.md",
        _article("Gamma", "Back to [a](./a.md), then [d](./d.md)."),
    )
    _write(wiki, "d.md", _article("Delta", "A leaf.", "status: deprecated\n"))
    _write(wiki, "e.md", _article("Epsilon", "Nobody links here. [gone](./gone.md)"))
    _write(wiki, "log.md", "# Log\n\n- touched [b](./b.md)\n")
    return wiki


@pytest.fixture
def g(wiki) -> graph.Graph:
    return graph.Graph.from_wiki(wiki, bundle="kb")


def _rels(nodes) -> list[str]:
    return [n.rel.as_posix() for n in nodes]


# -- nodes and edges -------------------------------------------------------------


def test_nodes_are_articles_and_indexes(g):
    assert _rels(g.nodes()) == ["INDEX.md", "a.md", "b.md", "c.md", "d.md", "e.md"]


def test_backlinks_include_non_node_sources(g, wiki):
    inbound = g.node("b.md").inbound
    assert set(inbound) == {wiki / "INDEX.md", wiki / "a.md", wiki / "log.md"}


def test_out_keeps_non_node_targets(g, wiki):
    assert g.node("a.md").out == (wiki / "b.md", (wiki.parent / "raw" / "src.md"))


def test_indexes_name_the_listing_index_once(g, wiki):
    assert g.node("d.md").indexes == (wiki / "INDEX.md",)
    assert g.node("e.md").indexes == ()


def test_metadata_reuses_index_gen(g):
    alpha = g.node("a.md")
    assert alpha.title == "Alpha"
    assert alpha.type == "concept"
    assert alpha.tier == "unverified"
    assert g.node("d.md").status == "deprecated"


def test_orphans(g):
    assert _rels(g.orphans()) == ["e.md"]


def test_broken_records_the_raw_target(g, wiki):
    assert (wiki / "e.md", "./gone.md") in g.broken()
    assert (wiki / "a.md", "../raw/src.md") in g.broken()


# -- canonical paths -------------------------------------------------------------


def test_canonical_accepts_absolute_root_and_wiki_relative(g, wiki):
    expected = (wiki / "a.md").resolve()
    assert g.canonical(wiki / "a.md") == expected
    assert g.canonical("wiki/a.md") == expected
    assert g.canonical("a.md") == expected


def test_canonical_refuses_a_path_outside_the_wiki(g, wiki):
    with pytest.raises(graph.GraphError, match="not inside the wiki"):
        g.canonical(wiki.parent / "raw" / "src.md")
    with pytest.raises(graph.GraphError):
        g.canonical("../../etc/passwd")


def test_node_refuses_a_non_node(g):
    with pytest.raises(graph.GraphError, match="not an article or index"):
        g.node("log.md")


# -- traversal -------------------------------------------------------------------


def test_neighbours_depth_one_follows_links_both_ways(g):
    found = {n.rel.as_posix(): d for n, d in g.neighbours("a.md", depth=1)}
    assert found == {"INDEX.md": 1, "b.md": 1, "c.md": 1}


def test_neighbours_depth_two_does_not_walk_through_the_index(g):
    found = {n.rel.as_posix(): d for n, d in g.neighbours("a.md", depth=2)}
    assert found == {"INDEX.md": 1, "b.md": 1, "c.md": 1, "d.md": 2}


def test_neighbours_from_an_index_expand_it(g):
    found = {n.rel.as_posix() for n, _ in g.neighbours("INDEX.md", depth=1)}
    assert found == {"a.md", "b.md", "c.md", "d.md"}


def test_neighbours_are_sorted_by_distance_then_path(g):
    assert [d for _, d in g.neighbours("a.md", depth=2)] == [1, 1, 1, 2]


def test_neighbours_reject_depth_zero(g):
    with pytest.raises(graph.GraphError, match="depth"):
        g.neighbours("a.md", depth=0)


def test_shortest_path_uses_backlinks(g):
    assert _rels(g.shortest_path("a.md", "d.md")) == ["a.md", "c.md", "d.md"]


def test_shortest_path_does_not_shortcut_through_the_index(g):
    """Every indexed article is two hops apart through INDEX.md."""
    assert _rels(g.shortest_path("b.md", "d.md")) == ["b.md", "c.md", "d.md"]


def test_shortest_path_to_an_orphan_is_none(g):
    assert g.shortest_path("a.md", "e.md") is None


def test_shortest_path_to_itself(g):
    assert _rels(g.shortest_path("a.md", "a.md")) == ["a.md"]


# -- roots -----------------------------------------------------------------------


def test_roots_reads_headings_levels_and_entries(g, wiki):
    sections = {s.title: s for s in g.roots()}
    assert list(sections) == ["Research", "Sub", "Tools", "📜 Operations"]
    assert sections["Research"].level == 2
    assert sections["Sub"].level == 3
    assert sections["Research"].entries == (wiki / "a.md", wiki / "b.md")
    assert sections["Tools"].entries == (wiki / "d.md",)
    assert {s.bundle for s in g.roots()} == {"kb"}


def test_roots_without_an_index_is_empty(tmp_path):
    wiki = tmp_path / "wiki"
    _write(wiki, "a.md", _article("A", "Body."))
    assert graph.Graph.from_wiki(wiki).roots() == ()


# -- CLI -------------------------------------------------------------------------


@pytest.fixture
def two_bundles(tmp_path, monkeypatch, wiki):
    """Add a second bundle and a project file that names both."""
    (wiki.parent / "okf.toml").write_text("", encoding="utf-8")
    other = tmp_path / "other"
    _write(other / "wiki", "a.md", _article("Other alpha", "Body."))
    _write(other / "wiki", "z.md", _article("Zed", "See [a](./a.md)."))
    (other / "okf.toml").write_text("", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    (project / config.PROJECT_FILENAME).write_text(
        f'[paths]\nkb = "{wiki.parent}"\nother = "{other}"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv(config.ENV_ROOT, raising=False)
    monkeypatch.chdir(project)
    return wiki


@pytest.mark.usefixtures("two_bundles")
def test_cli_roots_groups_sections_by_bundle():
    result = runner.invoke(graph.app, ["roots", "--json-output"])
    assert result.exit_code == 0, result.output
    payload = {
        entry["bundle"]: entry["sections"] for entry in json.loads(result.output)
    }
    assert payload["other"] == []
    assert payload["kb"][0] == {
        "title": "Research",
        "level": 2,
        "entries": ["a.md", "b.md"],
    }


@pytest.mark.usefixtures("two_bundles")
def test_cli_node_reports_deduplicated_backlinks():
    result = runner.invoke(graph.app, ["node", "c.md", "--kb", "kb", "--json-output"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["bundle"] == "kb"
    assert data["inbound"] == ["INDEX.md", "b.md"]
    assert data["out"] == ["a.md", "d.md"]


@pytest.mark.usefixtures("two_bundles")
def test_cli_an_ambiguous_path_asks_for_kb():
    result = runner.invoke(graph.app, ["node", "a.md"])
    assert result.exit_code == 1
    assert "more than one bundle" in result.output


@pytest.mark.usefixtures("two_bundles")
def test_cli_neighbours_of_several_starts_exclude_the_starts():
    result = runner.invoke(
        graph.app,
        ["neighbours", "b.md", "d.md", "--kb", "kb", "--depth", "1", "--json-output"],
    )
    assert result.exit_code == 0, result.output
    found = {(n["rel"], n["distance"]) for n in json.loads(result.output)}
    assert found == {("INDEX.md", 1), ("a.md", 1), ("c.md", 1)}


def test_cli_shortest_path_across_bundles_is_refused(two_bundles):
    result = runner.invoke(
        graph.app,
        ["shortest-path", str(two_bundles / "a.md"), "z.md"],
    )
    assert result.exit_code == 1
    assert "different bundles" in result.output


@pytest.mark.usefixtures("two_bundles")
def test_cli_shortest_path_reports_no_path_as_null():
    result = runner.invoke(
        graph.app,
        ["shortest-path", "b.md", "e.md", "--kb", "kb", "--json-output"],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {"bundle": "kb", "path": None, "hops": None}


@pytest.mark.usefixtures("two_bundles")
def test_cli_shortest_path_draws_each_hop_the_way_it_was_linked():
    """The hop from a to c is a backlink, the hop from c to d a forward link."""
    result = runner.invoke(graph.app, ["shortest-path", "a.md", "d.md", "--kb", "kb"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "a.md <- c.md -> d.md"

    result = runner.invoke(
        graph.app,
        ["shortest-path", "a.md", "d.md", "--kb", "kb", "--json-output"],
    )
    assert json.loads(result.output)["hops"] == ["backward", "forward"]


def test_direction_of_a_mutual_link_is_both(tmp_path):
    wiki = tmp_path / "wiki"
    _write(wiki, "x.md", _article("X", "[y](./y.md)"))
    _write(wiki, "y.md", _article("Y", "[x](./x.md)"))
    g = graph.Graph.from_wiki(wiki)
    assert g.direction(wiki / "x.md", wiki / "y.md") == "both"
