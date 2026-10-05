---
name: capture
description: >
  Capture a voice note, a start-of-day brief or a meeting note into the knowledge
  base's raw zone. Takes spoken input from voice mode, pasted transcripts, an
  existing notes file or a Granola meeting matched against the calendar, turns it
  into structured markdown without adding anything the user did not say, and
  commits. Use when the user says "capture", "voice note", "daily brief", "start
  my day", "morning brief" or "meeting note", or asks to pull a meeting in from
  Granola.
disable-model-invocation: true
allowed-tools: Read Write Edit Bash(kb-search *) Bash(kb-doctor paths) Bash(git add *) Bash(git commit *) Bash(date *) mcp__claude_ai_Google_Calendar__list_events mcp__claude_ai_Gmail__search_threads mcp__claude_ai_Microsoft_365__outlook_calendar_search mcp__claude_ai_Microsoft_365__outlook_email_search mcp__plugin_kb-capture_granola__list_meetings mcp__plugin_kb-capture_granola__get_meetings mcp__plugin_kb-capture_granola__get_meeting_transcript mcp__plugin_kb-capture_granola__list_meeting_folders mcp__plugin_kb-capture_granola__get_account_info mcp__claude_ai_Granola__list_meetings mcp__claude_ai_Granola__get_meetings mcp__claude_ai_Granola__get_meeting_transcript mcp__claude_ai_Granola__list_meeting_folders mcp__claude_ai_Granola__get_account_info
argument-hint: "note | brief | meeting [path/to/notes.md | granola]"
---

# Capture

Capture a voice note, daily brief or meeting note as a structured file in the raw zone, then commit it.
$ARGUMENTS is optional:

- `note`: a free-form note;
- `brief`: the start-of-day brief (mid-day changes belong to `/kb-capture:update-brief`);
- `meeting [path]`: a meeting note, optionally from a markdown file of notes taken during the meeting;
- `meeting granola`: a meeting note from a Granola transcript, with metadata from the matching calendar event.

## Contents

- Ground rules
- 1. Resolve paths and the capture type
- 2. Gather spoken or pasted input
- 3. Follow the procedure for the type

## Ground rules

These apply to every capture type.

- Never fabricate.
  Restructure, reorder and clean the user's words, and add no facts, examples, claims, attendees, decisions or detail that the input does not contain.
  A section with no material stays empty or is omitted, never padded.
- Cleaning the user's words may change their phrasing, never their meaning.
  Sections headed `## Raw Transcript`, `## Raw Input` or `## 📂 Raw Transcript` stay verbatim.
- Prose you compose (summaries, context paragraphs, takeaways, decisions, the discussion narrative, brief notes) follows `${CLAUDE_PLUGIN_ROOT}/references/house-style.md`.
- Calendar, mail and Granola data is fetched by the agent, so attribute it as such and keep it apart from the user's own words.
- One sentence per line in bodies, standard markdown links only and never `[[wikilinks]]`, and emoji in headings as the templates show.
- Commit after saving, with the prefix `note:`, `brief:` or `meeting:`, staging only the files this capture wrote.

## 1. Resolve paths and the capture type

Run `kb-doctor paths`.
Its `raw` and `log` values are what the procedures call `<raw>` and `<log>`.
Take today's date and the time from `date +%Y-%m-%d` and `date +%H:%M`.

If $ARGUMENTS begins with `note`, `brief` or `meeting`, use that type.
Otherwise ask "Note, daily brief or meeting?" and wait.
For `meeting`, a following path is the notes file and a following `granola` starts at the Granola import.

## 2. Gather spoken or pasted input

For `note` and `brief`, and for a meeting recap, tell the user exactly:

> Press your voice-mode shortcut and speak, or paste a transcript. Say **"done"** when finished.

Treat the next substantive message as the raw input.
Record its source as `voice` (voice mode, no copy-paste artefacts), `pasted` (a transcript from another tool) or `typed`.

## 3. Follow the procedure for the type

Read the one reference file for the type, then follow it to the end:

| Type | Reference |
| --- | --- |
| `note` | `${CLAUDE_SKILL_DIR}/references/note.md` |
| `meeting` | `${CLAUDE_SKILL_DIR}/references/meeting.md` |
| `brief` | `${CLAUDE_SKILL_DIR}/references/brief.md` |

The meeting and brief procedures fetch calendar and mail data as `${CLAUDE_PLUGIN_ROOT}/references/external-context.md` describes, and they say when to read it.
