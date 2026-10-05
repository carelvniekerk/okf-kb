---
name: meeting
description: >
  Start a blank meeting note in raw/meetings/ to fill in live during a meeting,
  with today's date, the current time and the attendees filled in, and open it in
  VS Code. Use when the user asks to start a meeting note for a meeting that is
  happening now. A meeting that already happened belongs to /kb-capture:capture
  meeting.
disable-model-invocation: true
allowed-tools: Read Write Bash(kb-doctor paths) Bash(date *) Bash(code *)
argument-hint: <meeting title (optional)>
---

# Meeting

Write a blank, structured meeting note to fill in live, and open it.
$ARGUMENTS, if given, is the meeting title.

The note is deliberately left uncommitted, because it changes throughout the meeting.
`/kb:compile` asks before it includes an uncommitted file, so a compile run mid-meeting does not pick it up silently.
For a meeting that already happened, `/kb-capture:capture meeting` structures notes or a recap, and `/kb-capture:capture meeting granola` builds the note from a Granola recording and the calendar event.

## Workflow

1. Run `kb-doctor paths` and take `<raw>` from its `raw` value.
2. Get the title from $ARGUMENTS, or ask "Meeting title?" and wait.
3. Ask "Attendees (comma-separated, or `skip` to fill in later)?" and wait.
4. Take the date and time from `date +%Y-%m-%d` and `date +%H:%M`, without asking.
5. Pick a short kebab-case slug of at most five words.
   The path is `<raw>/meetings/YYYY-MM-DD-<slug>.md`, and if it exists, append `-2`, `-3` and so on.
6. Write the scaffold below.
   With `skip`, write `attendees: []` and replace the bullets under `## 👥 Attendees` with `<!-- add as people join -->`.
7. Run `code "<absolute path>"`, then print the absolute path in one line so the user can also open it elsewhere.
   Do not commit and do not offer to compile.

```markdown
---
type: meeting-log
title: <Title> (YYYY-MM-DD)
description: <one sentence on what was decided or discussed>
author: human:<id>   # the bundle's human id, from its CLAUDE.md
date_added: YYYY-MM-DD
source_type: meeting
tags: [meeting]
meeting_date: YYYY-MM-DD HH:MM
attendees: [Name1, Name2]
---

# <Title> (YYYY-MM-DD)

![Type](https://img.shields.io/badge/type-meeting--log-blue) ![Added](https://img.shields.io/badge/added-YYYY--MM--DD-lightgrey)

## 👥 Attendees

<!-- edit as people join -->
- Name1
- Name2

## 🎯 Key Takeaways

<!-- after the meeting: up to five bullets -->

## 📌 Decisions

<!-- decisions reached; delete the section if none -->

## ✅ Action Items

<!-- - [ ] action · **owner** · deadline -->

## 💬 Discussion

<!-- main notes; H3 headings for separate topics -->

## 🔮 Open Questions

<!-- questions raised but not answered -->

## Related Articles

<!-- filled in later by /kb:compile -->

## Sources

- Live notes captured on YYYY-MM-DD from HH:MM.
```

Do not add `<!-- source: ... -->` markers to the scaffold.
`/kb:compile` adds them when it integrates the finished note, and so does `/kb-capture:capture meeting` if the user later restructures it.
