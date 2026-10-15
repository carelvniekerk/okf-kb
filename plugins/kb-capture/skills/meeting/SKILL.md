---
name: meeting
description: >
  Start a blank meeting note in raw/meetings/ to fill in live during a meeting,
  with the title, date, time and attendees taken from the matching Google or
  Microsoft 365 calendar event, and open it in VS Code. Use when the user asks
  to start or scaffold a meeting note, for a meeting happening now, just ended
  or on a named day, such as "a meeting for client X from just now". Notes or a
  recap of a meeting that already happened belong to /kb-capture:capture meeting.
disable-model-invocation: true
allowed-tools: Read Write Bash(kb-doctor paths) Bash(date *) Bash(code *) mcp__claude_ai_Google_Calendar__list_events mcp__claude_ai_Microsoft_365__outlook_calendar_search
argument-hint: "<client, title or topic, and when: now, yesterday, a date (all optional)>"
---

# Meeting

Write a blank, structured meeting note to fill in live, and open it.
$ARGUMENTS is free text that may hold the client or meeting title and a time, such as `client X from yesterday`.

The note is deliberately left uncommitted, because it changes throughout the meeting.
`/kb:compile` asks before it includes an uncommitted file, so a compile run mid-meeting does not pick it up silently.
For notes or a recap of a meeting that already happened, `/kb-capture:capture meeting` structures them into the note.

## Workflow

1. Run `kb-doctor paths` and take `<raw>` from its `raw` value.
   Take today's date and time from `date +%Y-%m-%d` and `date +%H:%M`, without asking.
2. Look the meeting up on the calendars, before asking the user anything.
   Read `${CLAUDE_PLUGIN_ROOT}/references/external-context.md` and follow "Finding one meeting", with the client, title or topic words and the time from $ARGUMENTS.
   Do this on every run, including when $ARGUMENTS names only a client.
3. With a matched event, take the title, the date and start time, and the attendees from it.
   Do not ask for the title or the attendees.
   Without a match, get the title from $ARGUMENTS or ask "Meeting title?", then ask "Attendees (comma-separated, or `skip` to fill in later)?", and wait for each.
4. Pick a short kebab-case slug of at most five words.
   The path is `<raw>/meetings/YYYY-MM-DD-<slug>.md` with the meeting's date, and if it exists, append `-2`, `-3` and so on.
5. Write the scaffold below.
   With `skip`, or an event that lists no attendees, write `attendees: []` and replace the bullets under `## 👥 Attendees` with `<!-- add as people join -->`.
   With a matched event, add `- Calendar event from <calendar name>, YYYY-MM-DD HH:MM.` under `## Sources`.
6. Run `code "<absolute path>"`, then print the absolute path, the event title and the attendee list in a few lines, so the user can correct either.
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
