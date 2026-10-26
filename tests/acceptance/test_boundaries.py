"""Acceptance tests AC-1 to AC-4: the article module and the import contracts.

AC-4 is the one that proves the contracts bite: it breaks a copy of the package
on purpose and expects the named contract to fail, because a contract that never
fails protects nothing.
"""

# ruff: noqa: ANN202, S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100, S603, S607

from __future__ import annotations

import ast
import importlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[2]
PACKAGE = REPO_ROOT / "src" / "okf_kb"
LINT_IMPORTS = Path(sys.executable).parent / "lint-imports"

READ_SIDE = ("graph", "search", "read", "stats", "health", "mcp_server")

CONTRACT_NAMES = (
    "Read-side modules sit above the shared model and config",
    "The MCP server cannot reach a writing module",
    "Nothing outside okf_kb.video imports it",
)


def test_ac_1_article_module_exposes_the_moved_names():
    article = importlib.import_module("okf_kb.article")

    assert article.INDEX_FILENAME == "INDEX.md"
    assert isinstance(article.DEFAULT_ARTICLE_EMOJI, str)
    assert article.split_emoji("Tülu 3: Open Post-Training") == (
        "📄",
        "Tülu 3: Open Post-Training",
    )
    assert article.split_emoji("🏁 Project Hub") == ("🏁", "Project Hub")

    item = article.Article(
        path=Path("/wiki/hub.md"),
        rel="hub.md",
        frontmatter={"title": "🏁 Project Hub", "description": " One line. "},
    )
    assert (item.emoji, item.title, item.description) == (
        "🏁",
        "Project Hub",
        "One line.",
    )


def _imports(module: str) -> set[str]:
    """Return the okf_kb modules that one module imports, at any nesting depth."""
    tree = ast.parse((PACKAGE / f"{module}.py").read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "okf_kb":
                found.update(alias.name for alias in node.names)
            elif node.module.startswith("okf_kb."):
                found.add(node.module.split(".")[1])
        elif isinstance(node, ast.Import):
            found.update(
                alias.name.split(".")[1]
                for alias in node.names
                if alias.name.startswith("okf_kb.")
            )
    return {name for name in found if (PACKAGE / f"{name}.py").exists()}


def _reachable(module: str) -> set[str]:
    seen: set[str] = set()
    pending = [module]
    while pending:
        for name in _imports(pending.pop()) - seen:
            seen.add(name)
            pending.append(name)
    return seen


@pytest.mark.parametrize("module", READ_SIDE)
def test_ac_2_read_side_modules_do_not_reach_the_index_generator(module):
    assert "index_gen" not in _reachable(module)


def _lint(cwd: Path, *args: str, pythonpath: Path | None = None):
    env = dict(os.environ)
    if pythonpath is not None:
        env["PYTHONPATH"] = str(pythonpath)
    return subprocess.run(
        [str(LINT_IMPORTS), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_ac_3_the_package_keeps_every_contract():
    result = _lint(REPO_ROOT)
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    for name in CONTRACT_NAMES:
        assert name in output, name


def test_ac_4_a_forbidden_import_breaks_the_named_contract(tmp_path):
    copy = tmp_path / "okf_kb"
    shutil.copytree(PACKAGE, copy, ignore=shutil.ignore_patterns("__pycache__"))
    server = copy / "mcp_server.py"
    server.write_text(
        server.read_text(encoding="utf-8") + "\nimport okf_kb.ingest  # noqa: F401\n",
        encoding="utf-8",
    )

    result = _lint(
        tmp_path,
        "--config",
        str(REPO_ROOT / "pyproject.toml"),
        pythonpath=tmp_path,
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert re.search(r"The MCP server cannot reach a writing module.*BROKEN", output)
