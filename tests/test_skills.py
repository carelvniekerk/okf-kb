"""Contract tests for the skills under ``plugins/``.

The skills are prose, so nothing type-checks them, and ``claude plugin validate``
checks only that the frontmatter parses. These pin down the failures that
reached users anyway: a tool name that no server provides, a bundled file the
skill points at but the plugin does not ship, a path hardcoded where the bundle
names its own zones, a ``Bash(git *)`` grant that pre-approves ``git push``, and
a skill long enough that compaction drops its second half.
"""

# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from okf_kb import extras

PLUGINS = Path(__file__).parents[1] / "plugins"
SKILLS = sorted(PLUGINS.glob("*/skills/*/SKILL.md"))
REFERENCES = sorted(PLUGINS.glob("*/references/*.md")) + sorted(
    PLUGINS.glob("*/skills/*/references/*.md"),
)

#: Every key Claude Code reads from skill frontmatter. It ignores any other key
#: without a word, so a misspelt one silently does nothing.
KNOWN_KEYS = {
    "name",
    "description",
    "when_to_use",
    "argument-hint",
    "arguments",
    "disable-model-invocation",
    "user-invocable",
    "allowed-tools",
    "disallowed-tools",
    "model",
    "effort",
    "context",
    "agent",
    "background",
    "hooks",
    "paths",
    "shell",
    "license",
    "compatibility",
    "metadata",
}

#: Skills Claude may invoke on its own. Every other skill writes files or
#: commits, so only the user starts it.
MODEL_INVOCABLE = {"kb-query/wiki"}

#: Skills that write into a bundle, and so must learn its zone names first.
WRITERS = {
    "kb/adopt",
    "kb/compile",
    "kb/verify",
    "kb-ingest/ingest",
    "kb-ingest/transcribe",
    "kb-video/video",
    "kb-capture/capture",
    "kb-capture/meeting",
    "kb-capture/update-brief",
}

#: The compaction budget re-attaches the first 5,000 tokens of a skill. Four
#: characters a token is a rough estimate, so leave a margin under it.
MAX_SKILL_CHARS = 18_000


def _id(path: Path) -> str:
    return f"{path.parents[2].name}/{path.parent.name}"


def _split(path: Path) -> tuple[dict, str]:
    _, front, body = path.read_text(encoding="utf-8").split("---", 2)
    return yaml.safe_load(front), body


def _grants(meta: dict) -> list[str]:
    return re.findall(r"\S+\([^)]*\)|\S+", meta.get("allowed-tools", ""))


@pytest.mark.parametrize("path", SKILLS, ids=_id)
def test_frontmatter_is_well_formed(path):
    meta, _ = _split(path)

    assert set(meta) <= KNOWN_KEYS, set(meta) - KNOWN_KEYS
    assert meta["name"] == path.parent.name
    assert re.fullmatch(r"[a-z0-9-]{1,64}", meta["name"])
    assert len(meta["description"]) <= 1024
    assert len(meta["description"]) + len(meta.get("when_to_use", "")) <= 1536
    assert not re.search(r"\b(MUST|FIRST|ALWAYS|NEVER)\b", meta["description"])


@pytest.mark.parametrize("path", SKILLS, ids=_id)
def test_only_the_query_skill_is_model_invocable(path):
    meta, _ = _split(path)
    expected = _id(path) not in MODEL_INVOCABLE
    assert meta.get("disable-model-invocation", False) is expected


@pytest.mark.parametrize("path", SKILLS, ids=_id)
def test_grants_are_narrow(path):
    """``Bash(git *)`` pre-approves push, reset --hard and clean for the turn."""
    for grant in _grants(_split(path)[0]):
        assert grant not in {"Bash(git *)", "Bash(git:*)", "Bash(mv *)", "Bash(rm *)"}
        assert not grant.startswith(("Bash(git push", "Bash(git reset", "Bash(uv "))


@pytest.mark.parametrize("path", SKILLS, ids=_id)
def test_plugin_tool_grants_name_a_server_the_plugin_ships(path):
    """Claude Code prefixes a plugin server's tools with the plugin's name."""
    plugin = path.parents[2]
    mcp = plugin / ".mcp.json"
    servers = set(json.loads(mcp.read_text())["mcpServers"]) if mcp.exists() else set()
    for grant in _grants(_split(path)[0]):
        found = re.match(r"mcp__plugin_([\w-]+?)_([\w-]+)__\w+$", grant)
        if found:
            assert found.group(1) == plugin.name, grant
            assert found.group(2) in servers, grant


@pytest.mark.parametrize("path", SKILLS, ids=_id)
def test_skills_fit_the_compaction_budget(path):
    text = path.read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 500
    assert len(text) <= MAX_SKILL_CHARS, len(text)


@pytest.mark.parametrize(
    "path",
    SKILLS + REFERENCES,
    ids=lambda p: str(p.relative_to(PLUGINS)),
)
def test_long_files_open_with_contents(path):
    """A partial read of a long file must still show its full scope."""
    text = path.read_text(encoding="utf-8")
    if len(text.splitlines()) > 100:
        assert "## Contents" in text


@pytest.mark.parametrize(
    "path",
    SKILLS + REFERENCES,
    ids=lambda p: str(p.relative_to(PLUGINS)),
)
def test_bundled_paths_exist_inside_the_plugin(path):
    """A path outside the plugin is not copied into the install cache."""
    plugin = next(p for p in PLUGINS.iterdir() if p in path.parents)
    skill_dir = path.parent if path.name == "SKILL.md" else None
    text = path.read_text(encoding="utf-8")
    for var, rel in re.findall(
        r"\$\{(CLAUDE_SKILL_DIR|CLAUDE_PLUGIN_ROOT)\}/([\w./-]+)",
        text,
    ):
        if var == "CLAUDE_SKILL_DIR":
            assert skill_dir is not None, f"{path}: CLAUDE_SKILL_DIR outside SKILL.md"
            target = (skill_dir / rel).resolve()
        else:
            target = (plugin / rel).resolve()
        assert target.exists(), f"{path}: {rel}"
        assert plugin.resolve() in target.parents, f"{path}: {rel} leaves the plugin"


def test_every_house_style_copy_is_identical():
    copies = sorted(PLUGINS.glob("*/references/house-style.md"))
    assert len(copies) >= 3
    first = copies[0].read_text(encoding="utf-8")
    for copy in copies[1:]:
        assert copy.read_text(encoding="utf-8") == first, copy


@pytest.mark.parametrize("path", [p for p in SKILLS if _id(p) in WRITERS], ids=_id)
def test_writing_skills_resolve_the_bundle_paths(path):
    meta, body = _split(path)
    assert "kb-doctor paths" in body
    assert any(
        g.startswith(("Bash(kb-doctor paths", "Bash(kb-doctor *", "Bash(kb-*"))
        for g in _grants(meta)
    )


@pytest.mark.parametrize(
    "path",
    SKILLS + REFERENCES,
    ids=lambda p: str(p.relative_to(PLUGINS)),
)
def test_bodies_do_not_hardcode_the_zones(path):
    """A bundle adopted from an existing folder keeps its own zone names."""
    text = path.read_text(encoding="utf-8")
    body = text.split("---", 2)[2] if path.name == "SKILL.md" else text
    hits = re.findall(r"(?<![<\w/.$-])(?:raw|wiki)/[\w.<-]", body)
    assert not hits, hits


@pytest.mark.parametrize(
    "path",
    SKILLS + REFERENCES,
    ids=lambda p: str(p.relative_to(PLUGINS)),
)
def test_no_staging_everything(path):
    """`git add -A` sweeps a live meeting note into a compile commit."""
    assert not re.search(
        r"git add (-A|--all|\.)(\s|$)",
        path.read_text(encoding="utf-8"),
    )


# -- init's templates -----------------------------------------------------------

TEMPLATES = PLUGINS / "kb" / "skills" / "init" / "templates"


@pytest.mark.parametrize(
    "full",
    [False, True],
    ids=["no-optional-plugins", "all-plugins"],
)
def test_json_templates_parse_with_and_without_fragments(full):
    fragments = TEMPLATES / "fragments"
    extra = ',\n        "kb-ingest@okf-kb": true,\n        "kb-video@okf-kb": true'
    fills = {
        "{{CAPTURE_TASKS}}": (fragments / "capture-tasks.json").read_text()
        if full
        else "",
        "{{FOAM_TASK}}": (fragments / "foam-task.json").read_text() if full else "",
        "{{EXTRA_PLUGINS}}": extra if full else "",
    }
    for name in ("settings.json", "vscode-tasks.json"):
        text = (TEMPLATES / name).read_text(encoding="utf-8")
        for placeholder, value in fills.items():
            text = text.replace(placeholder, value)
        assert "{{" not in text, name
        json.loads(text)


def test_fallback_install_commands_match_the_package():
    """The tooling reference is the one place an install command is hand-written."""
    text = (PLUGINS / "kb" / "references" / "tooling.md").read_text(encoding="utf-8")
    commands = re.findall(r"`(uv tool install \"[^`]+)`", text)
    expected = {
        f'uv tool install "okf-kb{marker} @ {extras.GIT_SOURCE}"'
        for marker in ("", "[ingest]", "[video]", "[all]")
    }
    assert set(commands) == expected
