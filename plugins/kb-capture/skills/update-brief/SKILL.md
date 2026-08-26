---
name: update-brief
description: >
  Update today's daily brief in place — refreshes calendar and Gmail sections, and optionally
  patches in new spoken or pasted content (done tasks, new todos, notes, mood).
  Use mid-day. For starting a fresh day, use /capture brief.
when_to_use: When the user types /update-brief or asks to update, refresh, or add to today's daily brief.
allowed-tools: Read Write Edit Bash(git *) mcp__claude_ai_Google_Calendar__list_events mcp__claude_ai_Gmail__search_threads mcp__claude_ai_Microsoft_365__outlook_calendar_search mcp__claude_ai_Microsoft_365__outlook_email_search
disable-model-invocation: true
---

# Update Brief

Update today's daily brief in place: refresh calendar + Gmail, and optionally patch in new spoken/pasted content (done tasks, new todos, notes, mood).

Use this mid-day.
For starting a fresh day, use `/capture brief`.

## Ground rules

- **Never fabricate content.**
Same rule as `/capture`: only restructure and clean the user's words.
External data (calendar, Gmail) is agent-fetched and clearly attributed.
- Edit the existing file **in place** — do not append session blocks.
`/update-brief` is the single way to add mid-day content.
- One sentence per line in body content.
- Commit after saving with `brief: update YYYY-MM-DD`.

## 1. Precondition check

Look for `raw/daily-briefs/YYYY-MM-DD.md` for today's date.

- If it does **not** exist, stop and tell the user: **"No brief for today yet — run `/capture brief` first."**
Do not create a new brief from this command.

Read the existing file fully before doing anything else.

## 2. Ask what kind of update

Prompt:

> **Refresh only, or add new content?**
> - `refresh` — just update calendar + Gmail sections
> - `add` — refresh, plus capture new notes / todos / mood

Wait for the answer.

## 3. Always: refresh calendar + Gmail

Use the **calendar set** configured in `okf.toml`'s `[[capture.calendars]]` — the same set `/kb:capture` reads. Fan out one call per entry (`list_events` for `provider = "google"`, `outlook_calendar_search` for `provider = "microsoft"`), merge by start time, dedupe.
Use the same rendering rules (prefix non-primary timed events with `[<calendar name>]`, render birthdays as `🎂 **<Name>'s birthday**`, holidays as `🎉 **<Holiday>**`).

In parallel:
1. **Calendar — today:** fan-out fetch for today's window.
2. **Calendar — tomorrow important:** fan-out fetch for tomorrow, then filter to external meetings, first meeting of the day, multi-hour / multi-attendee blocks, birthdays of people the user knows personally, German holidays that affect the working day, high-priority items.
   Skip routine self-blocked focus time unless it's the only item.
3. **Gmail — top 5 from last 2 days:** `mcp__claude_ai_Gmail__search_threads` with `newer_than:2d -category:promotions -category:social`.
4. **Every other configured mailbox — same window:** one call per `[[capture.mailboxes]]` entry, as `/kb:capture` describes. Tag each line with the entry's `name`, matching `/kb:capture`.
   Pick 5 signal-heavy threads.

If a single calendar fails, keep the others and note the miss in the rendered section.
If Gmail fails, leave the inbox section untouched and note `_(refresh failed: <reason>)_` at the end.
Continue.

**Overwrite** these sections in place, preserving the surrounding structure and headings:
- `## 📅 Today`
- `## 🔜 Tomorrow — key items`
- `## 📧 Inbox Signal — last 2 days`

If `mode == refresh`, skip to **Step 6 (commit)**.

## 4. Gather new input (only if `mode == add`)

Tell the user:

> Press your voice-mode shortcut and speak, or paste a transcript. Say **"done"** when finished.

Wait for the next substantive message.
Note the capture source (`voice | pasted | typed`) and the current time as `HH:MM` (24h local).

## 5. Parse and patch the brief

Extract from the input and apply each change to the existing file:

### 5a. Done mentions → mark todos `[x]`

Identify phrases like "finished X", "done with Y", "sent the email", "wrapped up Z".

For each done mention:
1. Scan current `[ ]` items in **`## ✅ Todos — Today`** (and also `## 🔁 Pushed to Tomorrow` / `## 🔁 Follow-ups` if the mention seems to reference them).
2. Pick the best-matching item.
**If confidence is high, just flip to `[x]`** and note it in your later summary.
3. **If confidence is low or multiple items match plausibly, ask:**
   > "You mentioned `<phrase>`. I think that's either:
   > 1. <item A>
   > 2. <item B>
   >
   > Which one? Or neither?"

   Wait for the answer before marking.
4. If nothing matches at all, ask the user if they want it added as a retroactively-completed item.

### 5b. New todos → append

Append new todos to `## ✅ Todos — Today` as `- [ ] <item>`.

**Always do a bandwidth check before finalising.**
Look at how many `[ ]` items remain in the Today list after this update, and remaining calendar bandwidth for the rest of the day.

If the load looks unrealistic, **push back**:

> "Adding those makes it <N> open todos for the rest of the day, and you have ~<M>h of focus time left. Want to push any to tomorrow? Current lowest-priority looks like: <item>."

Wait for the user's call.
Apply their changes: move pushed items to `## 🔁 Pushed to Tomorrow` with a short reason.

Always push back when overcommitment is plausible — don't stay silent.

### 5c. New follow-ups → append

Items the user said to "track", "chase", "remind me about" that aren't today's action → append to `## 🔁 Follow-ups` as `- [ ] <item> — <context>`.

### 5d. Mood update → append timestamped

If the user mentioned how they're feeling, **append** to `## 🙂 Mood` as a sub-bullet:

```markdown
- **HH:MM** — <cleaned one-line mood note>
```

Do **not** overwrite the morning's mood.
The section becomes a running log of how the day evolved.
If the user did not mention mood at all, leave the section alone.

### 5e. Other content → append to notes

Everything else (reflections, observations, context) → append to `## 📝 Notes` as new sentences (one per line), with a light timestamp marker if the notes are substantial:

```markdown
_Update HH:MM:_ <content>
```

### 5f. Transcript → append with timestamp

Append to `## 📂 Raw Transcript` under a new subheading:

```markdown
### HH:MM update

<!-- source: voice|pasted|typed -->
<Verbatim input, lightly cleaned.>
<!-- /source -->
```

## 6. Commit

```bash
git add raw/daily-briefs/ && git commit -m "brief: update YYYY-MM-DD"
```

Summarise what changed in 2–4 lines back to the user: which todos got marked, which were added, whether any got pushed, whether calendar/Gmail changed meaningfully.
Keep it terse.
