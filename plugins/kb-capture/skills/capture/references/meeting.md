# Capturing a meeting

The procedure for `/kb-capture:capture meeting`, for a meeting that has already happened.
A blank note to fill in live belongs to `/kb-capture:meeting`, which runs the same calendar lookup.

## Contents

- 1. Find the calendar event
- 2. Gather the inputs
- 3. Gather the metadata
- 4. Name the file
- 5. Find related articles
- 6. Structure the meeting note
- 7. Save, commit and offer to compile

## 1. Find the calendar event

Run this first, on every meeting capture, before asking the user for anything.
The user should not have to ask for it.
Read `${CLAUDE_PLUGIN_ROOT}/references/external-context.md` and follow "Finding one meeting", with the client or topic words and the day from the arguments, or from the request when it says "from yesterday" or "from just now".

With a matched event, take the scheduled start, the title, the full invitee list (with roles or organisations where given), the organiser and the location.
A failed or missing calendar never blocks the capture: note it in one line and carry on with step 2.

## 2. Gather the inputs

A meeting can be built from any combination of a markdown notes file and a spoken or pasted recap, and the calendar event from step 1 alone is enough for a skeleton note.
At least one of the three is required.

1. Notes file: use the path from the arguments, or ask "Path to a markdown notes file from the meeting? (`skip` for none)".
   Check that the file exists and read it fully.
   Treat it as unstructured input, since it will not follow the wiki's conventions.
2. Recap: ask "Add a spoken or pasted recap as well? (y / n)", and on a yes, gather it as the skill's step 2 describes.

If neither produced input and step 1 found no event, stop and say a meeting note needs at least one.

## 3. Gather the metadata

Take what you can from the event and the inputs, and ask only for the rest:

- the title, from the event, otherwise from the content if it is obvious, otherwise asked;
- the date, from the event, otherwise today, asked only if the notes suggest another day;
- the attendees: merge the event's invitees with the names found in the inputs, and confirm with "I found these attendees: <list>. Anything to add or correct?", because an invitation lists who was asked, not who came.

Never invent a name.

## 4. Name the file

Pick a short kebab-case slug of at most five words for the title.
The path is `<raw>/meetings/YYYY-MM-DD-<slug>.md` with the meeting's date, and if it exists, append `-2`, `-3` and so on.

## 5. Find related articles

Run `kb-search "<meeting topic and key terms>" --json-output` and pick two to four genuinely related articles for `## Related Articles`.

## 6. Structure the meeting note

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

- `meeting_date` is `YYYY-MM-DD`, or the event's `YYYY-MM-DD HH:MM` when step 1 matched one.
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

<!-- /source -->
```

`## Sources` lists each input that was used:

- `- <notes file path>`;
- `- Recap captured <voice | pasted | typed> on YYYY-MM-DD.`;
- `- Calendar event from <calendar name>, YYYY-MM-DD HH:MM.`, only when step 1 matched one.

## 7. Save, commit and offer to compile

1. Write the file.
2. `git add <the meeting note> && git commit -m "meeting: <title> (YYYY-MM-DD)"`.
3. Append to `<log>`: `## [YYYY-MM-DD] 📥 ingest | meeting: <title>`.
4. Ask: "Compile this into the wiki now, or later?"

Never delete or move the notes file the user passed in.
