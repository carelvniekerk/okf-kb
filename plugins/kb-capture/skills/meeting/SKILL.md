---
name: meeting
description: >
  Spin up a blank meeting note scaffold in raw/meetings/ ready to fill in live during a meeting.
  Pre-fills frontmatter with today's date and current time, and opens the file in VSCode.
  For post-hoc meeting structuring, use /kb-capture:capture meeting instead.
when_to_use: When the user types /kb-capture:meeting or asks to start a meeting note for a live meeting.
allowed-tools: Read Write Bash(date *) Bash(code *) Bash(git *)
disable-model-invocation: true
argument-hint: <meeting title (optional)>
---

# Meeting

Spin up a blank meeting note scaffolded from the standard template, ready to fill in live during the meeting.

$ARGUMENTS is optional: pass the meeting title to skip the prompt.

This is for **live note-taking** — it drops an empty structured file at `raw/meetings/YYYY-MM-DD-<slug>.md` with frontmatter pre-filled using today's date and current time, and empty section headers ready to type into.
Use `/kb-capture:capture meeting` instead for post-hoc structuring of unstructured notes or voice recap.

## 1. Get metadata

1. **Title:** if `$ARGUMENTS` is non-empty, use it.
   Otherwise ask: *"Meeting title?"* and wait.
2. **Attendees:** ask: *"Attendees (comma-separated, or `skip` to fill in later)?"* and wait.
3. **Current date & time:** determine today's local date as `YYYY-MM-DD` and the current local time as `HH:MM` (24h).
   Do not ask — use the system clock.

## 2. Derive filename

- Slug: short kebab-case from the title (≤ 5 words).
- Path: `raw/meetings/YYYY-MM-DD-<slug>.md`.
- Collision: if the path exists, append `-2`, `-3`, etc.

## 3. Write the scaffold

```markdown
---
type: meeting-log
title: <Title> — YYYY-MM-DD
description: <one sentence — what was decided or discussed>
author: human:<id>   # the bundle's human id, per CLAUDE.md
date_added: YYYY-MM-DD
source_type: meeting
tags: [meeting]
meeting_date: YYYY-MM-DD HH:MM
attendees: [Name1, Name2]      # or [] if user said skip
---

# <Title> — YYYY-MM-DD

![Type](https://img.shields.io/badge/type-meeting--log-blue) ![Added](https://img.shields.io/badge/added-YYYY--MM--DD-lightgrey)

## 👥 Attendees

<!-- pre-filled from prompt; edit as people join -->
- Name1
- Name2

## 🎯 Key Takeaways

<!-- fill in after the meeting — 3–5 bullets -->

## 📌 Decisions

<!-- decisions reached; delete section if none -->

## ✅ Action Items

<!-- - [ ] action — **owner** — deadline -->

## 💬 Discussion

<!-- main notes go here; use H3 subheadings for multiple topics -->

## 🔮 Open Questions

<!-- questions raised but not answered -->

## Related Articles

<!-- populated later via /kb:compile or manual kb-search -->

## Sources

- Live notes captured on YYYY-MM-DD starting HH:MM.
```

Fill in `<Title>`, the date/time values, and the attendees list.
If the user said `skip` for attendees, leave the list empty (`attendees: []`) and replace the sample bullets under `## 👥 Attendees` with a single comment: `<!-- add as people join -->`.

Do **not** use source provenance markers (`<!-- source: ... -->`) in this scaffold — those get added by `/kb:compile` when the filled-in file is integrated into the wiki, or by `/kb-capture:capture meeting` if the user later runs it to restructure.

## 4. Open and report

- Run `code "<absolute-path>"` to open the file in VSCode.
- Print the absolute file path so the user can also open it in Obsidian.
- Do **not** commit.
  The meeting content will be edited live; commit after the meeting when the notes are settled.
- Do not offer to compile.

Keep the final message terse — a single line with the path is enough.
