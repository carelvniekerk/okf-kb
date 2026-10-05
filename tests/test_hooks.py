"""Tests for the `kb` plugin's hooks.

A guard that should prompt but exits quietly looks exactly like a working one,
so each case feeds the handler a real PreToolUse event on stdin and checks the
decision it prints. The cases that must ask cover every way a human sign-off
can be written; the cases that must allow are the near misses that share its
words: a `human:` source author, `by: human:` in the body, and machine
confirmation by a `process:` actor.
"""

# ruff: noqa: S101, D100, D101, D102, D103, ANN001, ANN201, PLR2004, SLF001, INP001, RUF100, S603

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).parents[1] / "plugins" / "kb" / "hooks"
GUARD = HOOKS / "guard-human-signoff.py"

ARTICLE = """---
type: concept
title: Paged attention
generated:
  by: claude-opus-5-5
  at: '2026-10-02T07:49:22Z'
sources:
  - id: vllm-paper
    resource: raw/papers/2309.06180.md
    author: human:carel
date_updated: 2026-10-02
---

# Paged attention

Body text mentioning by: human:carel in prose.
"""

FLOW_ENTRY = "verified:\n  - { by: human:carel, at: 2026-10-05T10:00:00Z }\n"
SIGNED = ARTICLE.replace("date_updated", FLOW_ENTRY + "date_updated")


def decide(tool: str, tool_input: dict) -> str:
    """Run the guard on one event and return allow, ask or error:<code>."""
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool,
        "tool_input": tool_input,
    }
    # The script is stdlib-only, so the test interpreter runs it directly
    # instead of through `uv run --script`.
    out = subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        return f"error:{out.returncode}"
    if not out.stdout.strip():
        return "allow"
    return json.loads(out.stdout)["hookSpecificOutput"]["permissionDecision"]


@pytest.fixture
def plain(tmp_path):
    path = tmp_path / "plain.md"
    path.write_text(ARTICLE, encoding="utf-8")
    return path


@pytest.fixture
def signed(tmp_path):
    path = tmp_path / "signed.md"
    path.write_text(SIGNED, encoding="utf-8")
    return path


def _edit(path, old, new) -> dict:
    return {"file_path": str(path), "old_string": old, "new_string": new}


def test_a_flow_style_sign_off_asks(plain):
    tool_input = _edit(plain, "date_updated", FLOW_ENTRY + "date_updated")
    assert decide("Edit", tool_input) == "ask"


def test_a_block_style_sign_off_asks(plain):
    block = 'verified:\n  - by: "human:carel"\n    at: 2026-10-05\n'
    assert decide("Edit", _edit(plain, "date_updated", block + "date_updated")) == "ask"


def test_a_write_that_adds_a_sign_off_asks(plain):
    assert decide("Write", {"file_path": str(plain), "content": SIGNED}) == "ask"


def test_a_second_signer_asks(signed):
    entry = "  - { by: human:anna, at: 2026-10-06T09:00:00Z }\n"
    assert (
        decide("Edit", _edit(signed, "date_updated", entry + "date_updated")) == "ask"
    )


def test_a_sign_off_in_a_later_multi_edit_asks(plain):
    tool_input = {
        "file_path": str(plain),
        "edits": [
            {"old_string": "Body text", "new_string": "Body"},
            {"old_string": "date_updated", "new_string": FLOW_ENTRY + "date_updated"},
        ],
    }
    assert decide("MultiEdit", tool_input) == "ask"


def test_malformed_input_fails_closed(plain):
    assert decide("Edit", {"file_path": str(plain)}) == "ask"


def test_machine_confirmation_is_allowed(plain):
    entry = "verified:\n  - { by: process:kb-health, at: x }\n"
    assert (
        decide("Edit", _edit(plain, "date_updated", entry + "date_updated")) == "allow"
    )


def test_a_human_source_author_is_not_a_sign_off(plain):
    tool_input = _edit(plain, "author: human:carel", "author: human:anna")
    assert decide("Edit", tool_input) == "allow"


def test_by_human_in_the_body_is_not_a_sign_off(plain):
    tool_input = _edit(plain, "Body text", "Body text, again by: human:anna")
    assert decide("Edit", tool_input) == "allow"


def test_editing_a_signed_article_without_adding_a_sign_off_is_allowed(signed):
    assert decide("Edit", _edit(signed, "Body text", "Body")) == "allow"


def test_a_new_note_is_allowed(tmp_path):
    tool_input = {
        "file_path": str(tmp_path / "new.md"),
        "content": "---\ntype: note\n---\n# Note\n",
    }
    assert decide("Write", tool_input) == "allow"


def test_the_config_runs_the_guard_on_markdown_edits_and_writes():
    config = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
    group = config["hooks"]["PreToolUse"][0]
    assert group["matcher"] == "Edit|Write|MultiEdit"
    rules = {handler["if"] for handler in group["hooks"]}
    assert rules == {"Edit(**/*.md)", "Write(**/*.md)"}
    for handler in group["hooks"]:
        assert (
            handler["args"][-1] == "${CLAUDE_PLUGIN_ROOT}/hooks/guard-human-signoff.py"
        )


def test_the_guard_is_executable():
    """A non-executable script fails to start, which leaves the guard off."""
    assert os.access(GUARD, os.X_OK)
