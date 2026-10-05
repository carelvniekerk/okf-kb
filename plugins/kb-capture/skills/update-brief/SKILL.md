---
name: update-brief
description: >
  Update today's daily brief in place during the day. Refreshes the calendar and
  inbox sections from the accounts configured in okf.toml, and optionally patches
  in new spoken or pasted content: finished tasks, new todos, follow-ups, notes and
  mood. Use when the user asks to update, refresh or add to today's brief. Starting
  a new day belongs to /kb-capture:capture brief.
disable-model-invocation: true
allowed-tools: Read Edit Bash(kb-doctor paths) Bash(git add *) Bash(git commit *) Bash(date *) mcp__claude_ai_Google_Calendar__list_events mcp__claude_ai_Gmail__search_threads mcp__claude_ai_Microsoft_365__outlook_calendar_search mcp__claude_ai_Microsoft_365__outlook_email_search
argument-hint: "[refresh | add]"
---

# Update brief

Update today's daily brief in place: refresh its calendar and inbox sections, and optionally add new content.
This is the only way to add to a brief during the day, so edit the existing sections and never append session blocks.

## Contents

- Ground rules
- 1. Find today's brief
- 2. Choose the mode
- 3. Refresh calendars and mail
- 4. Gather new input
- 5. Patch the brief
- 6. Commit and report

## Ground rules

- Never fabricate: restructure and clean the user's words, and add nothing they did not say.
- Calendar and mail data is fetched by the agent and stays in its own sections, apart from the user's words.
- Notes, follow-up context and mood lines you write follow `${CLAUDE_PLUGIN_ROOT}/references/house-style.md`, and the raw transcript stays verbatim.
- Keep every existing heading exactly as it is, because the next brief and `/kb:compile` find sections by heading.
- One sentence per line in body content.

## 1. Find today's brief

Run `kb-doctor paths` and take `<raw>` from its `raw` value, and today's date from `date +%Y-%m-%d`.
If `<raw>/daily-briefs/YYYY-MM-DD.md` does not exist, stop and say: "No brief for today yet. Run `/kb-capture:capture brief` first."
Never create a brief from this skill.
Read the file fully before changing anything.

## 2. Choose the mode

If $ARGUMENTS is `refresh` or `add`, use it.
Otherwise ask, and wait:

> **Refresh only, or add new content?**
> - `refresh`: update the calendar and inbox sections
> - `add`: refresh, and capture new notes, todos and mood

## 3. Refresh calendars and mail

Read `${CLAUDE_PLUGIN_ROOT}/references/external-context.md`, and follow it for the configuration, the calendar and mailbox fan-out, the drop rules, rendering and failures.
If `[capture]` configures no calendars and no mailboxes, say so in one line, leave those sections as they are and go on.

Fetch in parallel today's events, tomorrow's filtered events and the top inbox threads from the last two days.
Overwrite only these sections, keeping their headings and everything around them:

- `## 📅 Today`
- `## 🔜 Tomorrow — key items`
- `## 📧 Inbox Signal — last 2 days`

If every source for a section failed, leave that section as it was and add `_(refresh failed: <reason>)_` at its end.
In `refresh` mode, go to step 6.

## 4. Gather new input

Tell the user:

> Press your voice-mode shortcut and speak, or paste a transcript. Say **"done"** when finished.

Treat the next substantive message as the input, and note its source (`voice`, `pasted` or `typed`) and the time from `date +%H:%M`.

## 5. Patch the brief

### Finished tasks

For each mention such as "finished X", "sent the email" or "wrapped up Z", find the best-matching `[ ]` item under `## ✅ Todos — Today`, or under `## 🔁 Pushed to Tomorrow` and `## 🔁 Follow-ups` if the mention points there.
When the match is clear, flip it to `[x]`.
When it is unclear or several items fit, ask which one and wait:

> You mentioned `<phrase>`. I think that's either:
> 1. <item A>
> 2. <item B>
>
> Which one, or neither?

If nothing matches, ask whether to add it as a completed item.

### New todos

Append them to `## ✅ Todos — Today` as `- [ ] <item>`.
Then check the load: count the open items and the focus time left in today's calendar.
When the day looks overcommitted, say so before finishing:

> Adding those makes <N> open todos with about <M>h of focus time left. Push any to tomorrow? The lowest priority looks like <item>.

Wait for the answer, and move pushed items to `## 🔁 Pushed to Tomorrow` with a short reason.

### Follow-ups

Append things to track, chase or be reminded of that are not today's action to `## 🔁 Follow-ups` as `- [ ] <item>: <context>`.

### Mood

If the user mentioned how they feel, append a line to `## 🙂 Mood` and keep the morning's entry, so the section records how the day went:

```markdown
- **HH:MM**: <cleaned one-line mood note>
```

If they did not mention mood, leave the section alone.

### Notes

Append everything else (reflections, observations, context) to `## 📝 Notes`, one sentence per line, starting with `_Update HH:MM:_` when the addition is substantial.

### Transcript

Append the input to `## 📂 Raw Transcript` under a new subheading:

```markdown
### HH:MM update

<!-- source: voice|pasted|typed -->
<The input verbatim, lightly cleaned.>
<!-- /source -->
```

## 6. Commit and report

```bash
git add <raw>/daily-briefs/YYYY-MM-DD.md
git commit -m "brief: update YYYY-MM-DD"
```

Report in two to four lines: which todos were marked done, which were added or pushed, and whether the calendar or inbox changed meaningfully.
