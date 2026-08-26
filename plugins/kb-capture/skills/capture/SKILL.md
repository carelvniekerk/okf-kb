---
name: capture
description: >
  Capture a voice note, daily brief, or meeting note — handles spoken content (via Claude Code's
  voice mode), pasted transcripts, and existing markdown notes files.
  Turns any of these into structured markdown and commits.
when_to_use: When the user says "capture", "voice note", "daily brief", "start my day", "morning brief", or "meeting note". Also when the user provides a voice transcript and wants it structured.
allowed-tools: Read Write Edit Bash(kb-search *) Bash(git *) mcp__claude_ai_Google_Calendar__list_events mcp__claude_ai_Gmail__search_threads mcp__claude_ai_Microsoft_365__outlook_calendar_search mcp__claude_ai_Microsoft_365__outlook_email_search
disable-model-invocation: true
argument-hint: "note | brief | meeting [path/to/notes.md]"
---

# Capture

Capture a voice note, daily brief, or meeting note. $ARGUMENTS is optional:
- `note` — free-form note
- `brief` — start-of-day daily brief (use `/update-brief` for mid-day updates)
- `meeting [path]` — meeting note, with optional path to an existing markdown file of raw notes taken during the meeting

This command handles spoken content (via Claude Code's voice mode), pasted transcripts (e.g. from the Claude mobile app), and — for meetings — a path to an existing markdown notes file.
It turns any of these into structured markdown.

## Ground rules (apply to all types)

- **Never fabricate content.**
Only restructure, reorder, and clean the user's words.
Do not invent facts, examples, claims, attendees, decisions, or supporting detail that is not in the input.
- If a section has no source material, **leave it empty or omit it** — do not pad.
- External data (calendar, Gmail) is allowed but must be **clearly attributed** as agent-fetched, never mixed into the user's own words.
- One sentence per line in body content (matches the repo's git-diff convention).
- Standard markdown links only, never Obsidian `[[wikilinks]]`.
- Use emojis in headers per CLAUDE.md conventions.
- Commit after saving, with the appropriate prefix (`note:`, `brief:`, or `meeting:`).

## 1. Determine capture type

If `$ARGUMENTS` begins with `note`, `brief`, or `meeting`, use that.
Otherwise ask: **"Note, daily brief, or meeting?"** and wait.

For `meeting`, if a path follows (`meeting /path/to/notes.md`), capture it as the provisional notes path for Section 3c below.

## 2. Gather the input (for `note` and `brief`)

Tell the user verbatim:

> Press your voice-mode shortcut and speak, or paste a transcript. Say **"done"** when finished.

Wait for the next substantive user message.
Treat it as the raw input.

Record the source: `voice` if the input came via voice mode (no obvious copy-paste artefacts), `pasted` if it looks like a transcript from another tool, `typed` if plainly typed.

For `meeting`, skip to Section 3c — it has a combined-input flow.

## 3a. If TYPE = note

### Step 1: Derive a slug and filename

- Read the input and pick a short kebab-case slug (≤ 4 words) that captures the topic.
- Filename: `raw/notes/YYYY-MM-DD-<slug>.md` (today's date).
- If a file with that exact path already exists, append `-2`, `-3`, etc.

### Step 2: Discover related wiki articles

Run `kb-search "<key terms from the note>" --json-output` and pick the top 2–4 genuinely related results.
Read one or two to confirm relatedness.
These become the `## Related Articles` section.

### Step 3: Structure the note

Follow the full article format from `CLAUDE.md`. The note must include:

```markdown
---
type: note
title: <Title derived from the content>
description: <one sentence — what is in this note and why someone would open it>
author: human:<id>   # the bundle's human id, per CLAUDE.md
date_added: YYYY-MM-DD
source_type: <technical | discussion | experiment — your call based on content>
tags: [tag1, tag2, tag3]
---

# <Title derived from the content>

<One-paragraph summary in the user's own words, cleaned up>

![Type](https://img.shields.io/badge/type-notes-blue) ![Added](https://img.shields.io/badge/added-YYYY--MM--DD-lightgrey)

## 🔗 Prerequisites

<Only include if the note clearly depends on other concepts. Otherwise omit.>

## 🎯 Key Takeaways

- <3–5 bullets drawn ONLY from what the user said. If the note is thin, fewer bullets is fine.>

## <Content sections>

<Main content organised with H2/H3 subheadings that make sense for the topic.>
<Preserve all substantive claims and examples from the input. Clean up filler, hedges, verbal tics.>

## 🔮 Open Questions

- <Questions the user explicitly raised in the recording. Do NOT invent your own here.>

## Related Articles

- [<Title>](../wiki/<path>.md) — one-line reason for relation

## Raw Transcript

<!-- source: raw/notes/YYYY-MM-DD-<slug>.md -->
<Verbatim input, minimally cleaned for readability (sentence breaks, obvious transcription errors). Preserve exact wording.>
<!-- /source -->

## Sources

- Captured <voice | pasted | typed> on YYYY-MM-DD.
```

### Step 4: Save, commit, offer to compile

- Write the file.
- `git add raw/notes/ && git commit -m "note: <title>"`
- Append to `wiki/log.md`: `## [YYYY-MM-DD] 📥 ingest | note: <title>`
- Ask: **"Compile this into the wiki now, or defer?"**

## 3c. If TYPE = meeting

### Step 1: Gather inputs

A meeting can be built from any combination of: an existing markdown notes file, a voice recap, or a pasted transcript.
At least one input is required.

1. **Notes file path:**
   - If `$ARGUMENTS` passed a path (`meeting /path/to/notes.md`), use it.
   Verify the file exists and is readable.
   - Otherwise ask: *"Path to a markdown notes file from the meeting? (`skip` for none.)"*
   Wait for the reply. Validate.
2. **Voice / paste recap:** ask: *"Want to add a voice or pasted recap in addition? (y / n)"*
   - If `y`: use the Section 2 voice/paste prompt.
   Wait for the transcript.
3. If neither a file nor a recap was provided, stop and tell the user the meeting needs at least one input.

Read the notes file fully if provided.
Treat it as unstructured input — it will not follow wiki conventions.

### Step 2: Gather metadata

Extract what you can from the inputs, then ask for anything missing:
- **Meeting title** — derive from content if obvious, otherwise ask.
- **Meeting date** — default today; ask only if the notes suggest a different date.
- **Attendees** — extract names mentioned in the notes or recap, then confirm with the user: *"I found attendees: [list]. Anything to add or correct?"*
Do not invent names.

### Step 3: Derive slug and filename

- Slug: short kebab-case from the meeting title (≤ 5 words).
- Filename: `raw/meetings/YYYY-MM-DD-<slug>.md` (using the meeting date, not today's date if different).
- Collision: append `-2`, `-3`, etc.

### Step 4: Discover related wiki articles

Run `kb-search "<meeting topic + key terms>" --json-output`.
Pick 2–4 genuinely related articles.
These become `## Related Articles`.

### Step 5: Structure the meeting note

Start from the `/meeting` scaffold — it is the canonical meeting-note outline.
Apply these modifications for the post-hoc capture case:

**Frontmatter:**
- `tags`: extend to `[meeting, <topic-tags>]` — add 1–3 topic tags derived from the content.
- `date_added` / `date_updated`: today.
- `meeting_date`: use just `YYYY-MM-DD` (no `HH:MM`) — post-hoc capture doesn't need the start time.
- `attendees`: populate from the names confirmed in Step 2.

**Body — replace each empty section with content drawn from the inputs:**
- After the title, add a one-paragraph context: what the meeting was about and why it happened.
- `## 👥 Attendees`: list `- <Name> — <role if mentioned>`.
- `## 🎯 Key Takeaways`: 3–5 bullets covering the most important outcomes.
- `## 📌 Decisions`: `- <decision> — <brief rationale if given>`.
Omit the section entirely if no decisions were reached.
- `## ✅ Action Items`: `- [ ] <action> — **<owner>** — <deadline if given>`.
Owner defaults to the person who volunteered or was assigned.
If unassigned, leave blank — do not guess.
- `## 💬 Discussion`: cleaned-up narrative.
Group by topic with H3 subheadings if the meeting covered multiple threads.
Preserve substantive content: arguments made, data cited, examples given.
- `## 🔮 Open Questions`: questions raised but not answered, and questions clearly implied by unresolved decisions (not speculative).
- `## Related Articles`: populate from the Step 4 `kb-search` results.

**Insert a `## Raw Input` section between `## Related Articles` and `## Sources`:**

```markdown
## Raw Input

<!-- source: raw/meetings/YYYY-MM-DD-<slug>.md -->

<If a notes file was provided:>

### Original notes (`<original filename>`)

<Verbatim content of the notes file.>

<If a voice/pasted recap was provided:>

### Recap transcript (<voice | pasted | typed>)

<Verbatim transcript, lightly cleaned.>

<!-- /source -->
```

**`## Sources` section:**
- `- <Original notes file path, if provided>`
- `- Recap captured <voice | pasted | typed> on YYYY-MM-DD, if provided.`

### Step 6: Save, commit, offer to compile

- Write the file.
- `git add raw/meetings/ && git commit -m "meeting: <title> (YYYY-MM-DD)"`
- Append to `wiki/log.md`: `## [YYYY-MM-DD] 📥 ingest | meeting: <title>`
- Ask: **"Compile this into the wiki now, or defer?"**

Do not delete or move the original notes file the user passed in.

## 3b. If TYPE = daily brief

A daily brief is a multi-step workflow. Do not skip steps.

### Step 1: Review the previous brief (context + carryover)

Find the most recent file in `raw/daily-briefs/` whose filename date is **earlier than today**.

If one exists:
1. Read it fully.
2. Collect every unchecked `- [ ]` item from these sections:
   - `## ✅ Todos — Today`
   - `## 🔁 Pushed to Tomorrow`
   - `## 🔁 Follow-ups`
3. If the list is non-empty, show it to the user:

   > **Yesterday's open items (<filename>):**
   >
   > **Todos** (<N>):
   > 1. <item>
   >
   > **Pushed to tomorrow** (<N>):
   > ...
   >
   > **Follow-ups** (<N>):
   > ...
   >
   > Which got done? Which to drop? Everything else carries forward.

4. Wait for the user's reply.
Parse their answer (can be "1, 3 done; 2 drop" or "all done" or similar).
5. **Update yesterday's file:**
   - Done items → change `- [ ]` to `- [x]`.
   - Dropped items → wrap in `~~strikethrough~~` and append `_(dropped YYYY-MM-DD)_`.
   - Everything else stays as-is; those are the **carryovers**.
6. Save yesterday's file.
Commit later with today's brief (single commit).

If no prior brief exists, skip this step entirely.

### Step 2: Gather today's input

Use the **Section 2** flow above (voice or pasted).
Wait for "done".

### Step 3: Fetch external context

**Read the `[capture]` table in `okf.toml` first.** Nothing about which accounts to
fetch is baked into this skill — it is configured per bundle. If the table is
absent or declares no calendars and no mailboxes, skip this step entirely and
build the brief from the user's own input alone; say so once, in one line, and
do not prompt for setup mid-capture.

The schema `/kb:init` writes:

```toml
[capture]
timezone = "Europe/Berlin"          # optional; used for day boundaries

[[capture.calendars]]
name = "Primary"                    # label used in failure notes
provider = "google"                 # google | microsoft
id = "you@example.com"              # google only; omit for microsoft
# event_type_filter = ["birthday"]  # optional, google only
# drop_subject_prefix = "Daily /"   # optional: recurring noise to exclude

[[capture.mailboxes]]
name = "Gmail"                      # tag shown against each inbox line
provider = "gmail"                  # gmail | outlook
# folder = "Inbox"                   # outlook only
```

**Calendars.** Fan out in parallel — one call per configured calendar — then merge
by start time and dedupe.

- `provider = "google"` → `mcp__claude_ai_Google_Calendar__list_events` with the
  entry's `id` as `calendarId`. Pass `eventTypeFilter` when the entry sets
  `event_type_filter`; otherwise use the default filter.
- `provider = "microsoft"` → `mcp__claude_ai_Microsoft_365__outlook_calendar_search`
  with `query: "*"`, `afterDateTime` / `beforeDateTime` set to the day's window,
  and `order: "oldest"`. Pass no `calendarId` — it defaults to the signed-in
  user's default calendar.
- Where an entry sets `drop_subject_prefix`, discard every event whose subject
  starts with it. Recurring standups are noise and must never appear in the
  brief, not even as "first meeting of the day" filler.

**Mailboxes.** Fan out across every configured mailbox for the last 2 days.

- `provider = "gmail"` → `mcp__claude_ai_Gmail__search_threads`, query
  `newer_than:2d -category:promotions -category:social`.
- `provider = "outlook"` → `mcp__claude_ai_Microsoft_365__outlook_email_search`
  with the entry's `folder` (default `"Inbox"`), `afterDateTime: "2 days ago"`,
  `order: "newest"`.

From the combined results pick up to 5 that look most signal-heavy — direct
senders, replies needed, named people, work-relevant. Mix mailboxes if warranted,
but do not force an even split. Summarise each in one line, tagged with the
entry's `name`, e.g. `[Gmail]` or `[Outlook]`.

In parallel, fetch:

1. **Calendar — today:** every configured calendar, today's window. Merge, sort by
   start time, apply the drop rules.
2. **Calendar — tomorrow:** the same fan-out for tomorrow.
   Filter to what is plausibly important: external meetings, first meeting of the
   day, multi-hour or multi-attendee blocks, birthdays of people the user knows
   personally, public holidays that affect the working day, anything flagged
   high-priority. Skip routine self-blocked focus time unless it's the only item.
3. **Inbox — top signal items from the last 2 days**, as above.

Fetch failures must never block the brief.
If one calendar fails, keep the others and note the miss in `## 📅 Today` as
`_(<name> calendar unavailable)_`.
If a mailbox fails, note `_(<name> unavailable)_` in the inbox section and
continue with whatever else returned.
A connector that is simply not authenticated this session is a skip, not an
error — note it the same way. Re-authenticating means running `/mcp` and
selecting the connector.

### Step 4: Parse the captured input

Extract from the user's recording:
- **Mood / energy** — any statement about how they're feeling, energy level, state of mind.
If nothing was said, **ask explicitly:** "Any mood or energy notes for today?" and wait.
- **Focus / intentions** — what they said they want to accomplish.
- **New todos** — anything actionable the user said they want to do.
- **New follow-ups** — items the user said to "track", "not forget", "remind me about", "chase X for Y" that aren't a today action.
- **Notes** — everything else: reflections, observations, context.

### Step 5: Interactive todo triage

Combine the **carryovers from Step 1** with the **new todos from Step 4**.
Now help the user prioritise:

1. Look at today's calendar from Step 3.
Roughly estimate available focus hours (wall-clock minus meetings minus a buffer).
2. For each todo, make a quick judgment on effort (small / medium / large) and priority (based on stated deadlines, carryover age, user's stated focus).
3. Present a proposed split:

   > Given your calendar (<N>h of meetings, ~<M>h free), here's my suggested split:
   >
   > **Today (<K> items):**
   > 1. [P1, small] <item>
   > 2. [P1, medium] <item>
   >
   > **Push to tomorrow (<J> items):**
   > - <item> — reason: <low priority / no bandwidth / waiting on X>
   >
   > Adjust anything?

4. Wait for the user to confirm or adjust.
Apply their changes.

**Be direct in this step.**
If the user gives you 12 todos and has 6 hours of meetings, say so.
If a carryover has slipped 3+ days, flag it and ask whether it should be dropped instead of pushed again.

### Step 6: Write the brief

Path: `raw/daily-briefs/YYYY-MM-DD.md`.

If `raw/daily-briefs/YYYY-MM-DD.md` already exists, stop and tell the user: **"Today's brief already exists — use `/update-brief` for mid-day additions."**
Do not overwrite.

Otherwise write the full template:

```markdown
---
type: daily-brief
date: YYYY-MM-DD
source: voice | pasted | typed
mood: <one-line mood summary>
carried_from: YYYY-MM-DD  # omit if no prior brief
---

# Daily Brief — YYYY-MM-DD

## 🙂 Mood

<User's mood / energy in their own cleaned-up words.>

## 📅 Today

- **HH:MM–HH:MM** <title> — <location or "virtual"> — <N attendees[, external]>
- **HH:MM–HH:MM** [<calendar name>] <title> — …
- 🎂 **<Name>'s birthday**
- 🎉 **<Holiday>**
- …

_(Merged from <the `name` of every calendar that returned>.)_

## 🔜 Tomorrow — key items

- **HH:MM** <title> — <why it matters>
- …

_(Merged from the same calendar set.)_

## 🧭 Focus

<What the user said they want to accomplish today.>

## ✅ Todos — Today

- [ ] <item> — <priority tag if useful>
- [ ] <item> ↩️ _(carried from YYYY-MM-DD)_
- …

## 🔁 Pushed to Tomorrow

- [ ] <item> — <reason>
- …

## 🔁 Follow-ups

- [ ] <item> — <context / when>
- …

## 📝 Notes

<Non-actionable content: reflections, observations, context. One sentence per line.>

## 📧 Inbox Signal — last 2 days

1. **[Gmail|Outlook] <Subject>** — <sender> — <one-line summary / why it matters>
2. …

_(Top 5 from <the `name` of every mailbox that returned>, last 48h, excluding promotions/social.)_

## 📂 Raw Transcript

<!-- source: voice|pasted|typed -->
<Verbatim input, lightly cleaned for readability.>
<!-- /source -->
```

For mid-day additions (mark off todos, add new items, log notes, evolve mood, refresh calendar/Gmail), use `/update-brief` — not this command.

### Step 7: Commit

```bash
git add raw/daily-briefs/ && git commit -m "brief: YYYY-MM-DD"
```

If Step 1 modified yesterday's file, the same commit should include it (the `git add` captures it).

Do **not** append to `wiki/log.md` for daily briefs — they are personal/ephemeral.
Do **not** offer to compile — daily briefs are not wiki material.

## Marking off todos between briefs

The user can also tick `- [x]` directly in Obsidian — GitHub-flavored checkboxes are clickable there.
No command needed for that.
The next `/capture brief` run will pick up the current state of checkboxes when reviewing yesterday's file (Step 1).
