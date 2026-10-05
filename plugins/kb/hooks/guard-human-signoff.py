#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Make every new human sign-off on a wiki article reach the permission prompt.

A `verified` entry with a `human:` actor claims that a named person read the
article against its sources. /kb:verify asks for that confirmation in the
conversation, but a skill is prose that Claude may skip, so this PreToolUse
hook returns "ask" whenever an edit would add such an entry. Any failure to
read the input or the file also returns "ask", so a broken guard prompts
rather than allowing silently.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

#: A verified entry's actor, in flow (`{ by: human:x }`) or block style.
HUMAN_ACTOR = re.compile(r"""\bby:\s*["']?human:""")


def frontmatter(text: str) -> str:
    """Return the YAML frontmatter block.

    Args:
        text: The whole markdown file.

    Returns:
        The text between the opening and closing `---`, or an empty string if
        the file has no frontmatter.

    """
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    return text[3:end] if end != -1 else ""


def after_edit(tool: str, tool_input: dict[str, Any], before: str) -> str:
    """Apply the tool call to the current text, as Claude Code would.

    Args:
        tool: `Edit`, `MultiEdit` or `Write`.
        tool_input: The tool call's input.
        before: The file's current text, empty if it does not exist.

    Returns:
        The file's text after the call.

    """
    if tool == "Write":
        return tool_input["content"]
    edits = tool_input.get("edits") or [tool_input]
    text = before
    for edit in edits:
        count = -1 if edit.get("replace_all") else 1
        text = text.replace(edit["old_string"], edit["new_string"], count)
    return text


def ask(reason: str) -> None:
    """Print the PreToolUse decision that sends the call to the user.

    Args:
        reason: Shown to the user in the permission prompt.

    """
    decision = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": reason,
    }
    print(json.dumps({"hookSpecificOutput": decision}))


def main() -> None:
    """Read the PreToolUse event from stdin and ask if it adds a sign-off."""
    try:
        event = json.load(sys.stdin)
        tool, tool_input = event["tool_name"], event["tool_input"]
        path = Path(tool_input["file_path"])
        before = path.read_text(encoding="utf-8") if path.exists() else ""
        after = after_edit(tool, tool_input, before)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        ask(
            f"The human sign-off guard could not check this edit ({exc}). "
            "Approve only if it adds no human: entry under verified.",
        )
        return
    added = len(HUMAN_ACTOR.findall(frontmatter(after))) - len(
        HUMAN_ACTOR.findall(frontmatter(before)),
    )
    if added > 0:
        ask(
            f"This edit adds a human sign-off to {path.name}. Approve only if "
            "that person read the article against its sources and confirmed it.",
        )


if __name__ == "__main__":
    main()
