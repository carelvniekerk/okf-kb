# Capturing a meeting

The procedure for `/kb-capture:capture meeting`, for a meeting that has already happened.
A meeting still in progress belongs to `/kb-capture:meeting`, which writes a blank note to fill in live.

## Contents

- 1. Gather the inputs
- 2. Import from Granola
- 3. Gather the metadata
- 4. Match the calendar event
- 5. Resolve speaker labels
- 6. Name the file
- 7. Find related articles
- 8. Structure the meeting note
- 9. Save, commit and offer to compile

## 1. Gather the inputs

A meeting can be built from any combination of a Granola transcript, a markdown notes file, and a spoken or pasted recap.
At least one is required.

1. Granola: with `meeting granola`, go to step 2.
   Otherwise ask "Pull the transcript from Granola? (y / n)", and on a yes, run step 2.
2. Notes file: use the path from the arguments, or ask "Path to a markdown notes file from the meeting? (`skip` for none)".
   Check that the file exists and read it fully.
   Treat it as unstructured input, since it will not follow the wiki's conventions.
3. Recap: ask "Add a spoken or pasted recap as well? (y / n)", and on a yes, gather it as the skill's step 2 describes.

If none of the three produced input, stop and say a meeting note needs at least one.

## 2. Import from Granola

The `kb-capture` plugin ships the Granola MCP server, whose tools arrive as `mcp__plugin_kb-capture_granola__*` once the user authenticates.
A user with Granola as a claude.ai connector has the same tools as `mcp__claude_ai_Granola__*`.
Use whichever prefix is connected, since they take identical arguments.
If neither responds, say in one line that Granola is not connected and that `/mcp` authenticates it, then carry on with the other inputs.
A missing connector is a skip, never a reason to abandon the capture.

Pick the meeting:

1. Ask "Which day?" unless the user said, defaulting to today.
2. Call `list_meetings` with `time_range: "this_week"` for a day in the current week, or `time_range: "custom"` with `custom_start` and `custom_end` bracketing the day.
   Pass `folder_id` only if `[capture.granola]` in `okf.toml` sets one.
3. List the results numbered, one line each (`HH:MM: <title> (<n> attendees)`), and wait for the pick, even when there is only one, so the user recognises it.
4. If the list is empty, say so and report the `mcp_note_access.scopes` from `get_account_info`, because an empty result usually means a scope or plan limit rather than a missing meeting.

Fetch the content for the chosen id:

- `get_meetings` with a one-element `meeting_ids` returns the AI summary, the user's private notes and the attendee metadata.
- `get_meeting_transcript` returns the verbatim record and needs a paid Granola plan.
  If it errors or is empty, note it in one line and build the note from the summary and notes.
  Do not retry, and do not suggest an upgrade.

Granola's participant metadata is not an attendance record: its own schema says it "can be incomplete and does not prove attendance", and `captured_by_me` marks the note's owner, not the organiser.
The calendar event in step 4 is the authority on who was invited, and Granola is the authority on what was said.

## 3. Gather the metadata

Take what you can from the inputs and ask for the rest:

- the title, from the content if it is obvious, otherwise asked;
- the date, today by default, asked only if the notes suggest another day;
- the attendees, as names found in the inputs, confirmed with "I found these attendees: <list>. Anything to add or correct?".

Never invent a name.

## 4. Match the calendar event

Run this whenever the meeting's date and time are known.
Read `${CLAUDE_PLUGIN_ROOT}/references/external-context.md`, and if no calendars are configured, skip this step silently.

Fetch the meeting's day from every configured calendar, and match an event whose start is within 15 minutes of the meeting's and whose title recognisably overlaps.
With exactly one match, adopt it.
With several, list them numbered and ask which.
With none, say so in one line and keep the metadata from step 3, without widening the window to force a match.

From the matched event take the scheduled start, the full invitee list (with roles or organisations where given), the organiser and the location.
Merge the invitees with the names from the inputs, and confirm the combined list with the user, because an invitation lists who was asked, not who came.
A failed calendar fetch never blocks the capture: note it and carry on.

## 5. Resolve speaker labels

Granola labels the note-taker `Me`, unidentified speakers `Them`, and known speakers by name.

- Rewrite `Me` as the display name for the bundle's human id.
- Rewrite `Them` as a name only when the matched event has exactly two attendees, so exactly one candidate exists.
- With three or more attendees, leave `Them` as it is, because guessing a speaker is fabrication.
- Leave named speakers exactly as Granola gives them.

## 6. Name the file

Pick a short kebab-case slug of at most five words for the title.
The path is `<raw>/meetings/YYYY-MM-DD-<slug>.md` with the meeting's date, and if it exists, append `-2`, `-3` and so on.

For a Granola import, first search `<raw>/meetings/` for a file whose frontmatter has the same `granola_id`.
If one exists, stop and name it, so the same meeting is not filed twice.

## 7. Find related articles

Run `kb-search "<meeting topic and key terms>" --json-output` and pick two to four genuinely related articles for `## Related Articles`.

## 8. Structure the meeting note

Start from the scaffold that `/kb-capture:meeting` writes, which is the canonical meeting outline:

```markdown
---
type: meeting-log
title: <Title> (YYYY-MM-DD)
description: <one sentence on what was decided or discussed>
author: human:<id>
date_added: YYYY-MM-DD
date_updated: YYYY-MM-DD
source_type: meeting
tags: [meeting, <one to three topic tags>]
meeting_date: YYYY-MM-DD
attendees: [<confirmed names>]
granola_id: <uuid>   # only for a Granola import
---

# <Title> (YYYY-MM-DD)

<One paragraph on what the meeting was about and why it happened.>

![Type](https://img.shields.io/badge/type-meeting--log-blue) ![Added](https://img.shields.io/badge/added-YYYY--MM--DD-lightgrey)

## 👥 Attendees
## 🎯 Key Takeaways
## 📌 Decisions
## ✅ Action Items
## 💬 Discussion
## 🔮 Open Questions
## Related Articles
## Raw Input
## Sources
```

- `meeting_date` is `YYYY-MM-DD`, or the event's `YYYY-MM-DD HH:MM` when step 4 matched one.
  `granola_id` is what makes the re-import check in step 6 work.
- `## 👥 Attendees`: `- <Name>: <role, if mentioned>`.
- `## 🎯 Key Takeaways`: up to five bullets on the most important outcomes.
- `## 📌 Decisions`: `- <decision>: <rationale, if given>`, and omit the section when nothing was decided.
- `## ✅ Action Items`: `- [ ] <action> · **<owner>** · <deadline, if given>`.
  The owner is whoever volunteered or was assigned, and stays blank when nobody was.
- `## 💬 Discussion`: the cleaned-up narrative, grouped by topic under H3 headings when there were several threads, keeping the arguments made, data cited and examples given.
- `## 🔮 Open Questions`: questions raised and not answered, and questions an unresolved decision clearly implies.

`## Raw Input` holds the verbatim records, wrapped in one provenance marker:

```markdown
## Raw Input

<!-- source: <raw>/meetings/YYYY-MM-DD-<slug>.md -->

### Original notes (`<original filename>`)

<The notes file verbatim, if one was given.>

### Recap transcript (<voice | pasted | typed>)

<The recap verbatim, lightly cleaned, if one was given.>

### Granola transcript

<The transcript verbatim, with speaker labels resolved as in step 5, if one was imported.>

<!-- /source -->
```

Never summarise, trim or reorder the Granola transcript, because the raw zone holds source records at full length.
Granola's AI summary and the user's private notes are already processed content, not raw input: fold them into the discussion and takeaways, and attribute them under `## Sources`.

`## Sources` lists each input that was used:

- `- <notes file path>`;
- `- Recap captured <voice | pasted | typed> on YYYY-MM-DD.`;
- `` - Granola meeting `<granola_id>`: transcript and notes, imported YYYY-MM-DD. ``, with "transcript unavailable on this plan" in place of "transcript and notes" when `get_meeting_transcript` returned nothing;
- `- Calendar event from <calendar name>, YYYY-MM-DD HH:MM.`, only when step 4 matched one.

## 9. Save, commit and offer to compile

1. Write the file.
2. `git add <the meeting note> && git commit -m "meeting: <title> (YYYY-MM-DD)"`.
3. Append to `<log>`: `## [YYYY-MM-DD] 📥 ingest | meeting: <title>`.
4. Ask: "Compile this into the wiki now, or later?"

Never delete or move the notes file the user passed in.
