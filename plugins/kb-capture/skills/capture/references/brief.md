# Capturing the daily brief

The procedure for `/kb-capture:capture brief`, the start-of-day brief.
Mid-day changes belong to `/kb-capture:update-brief`.
Do not skip steps.

## Contents

- 1. Refuse a second brief
- 2. Review the previous brief
- 3. Gather today's input
- 4. Fetch calendars and mail
- 5. Parse the input
- 6. Triage the todos
- 7. Write the brief
- 8. Commit

## 1. Refuse a second brief

If `<raw>/daily-briefs/YYYY-MM-DD.md` exists for today, stop and say: "Today's brief already exists. Use `/kb-capture:update-brief` for mid-day additions."
Never overwrite it.

## 2. Review the previous brief

Find the most recent file in `<raw>/daily-briefs/` dated before today, and skip this step if there is none.

1. Read it fully.
2. Collect every unchecked `- [ ]` item under `## ✅ Todos — Today`, `## 🔁 Pushed to Tomorrow` and `## 🔁 Follow-ups`.
3. If there are any, show them numbered by section, and ask which got done and which to drop, saying that everything else carries forward.
4. Wait for the reply, which may be terse ("1, 3 done; 2 drop" or "all done").
5. Update that file: done items become `- [x]`, and dropped items are wrapped in `~~strikethrough~~` with `_(dropped YYYY-MM-DD)_` appended.
   The rest are the carryovers.
6. Save it, to be committed with today's brief.

## 3. Gather today's input

Gather spoken or pasted input as the skill's step 2 describes, and wait for "done".

## 4. Fetch calendars and mail

Read `${CLAUDE_PLUGIN_ROOT}/references/external-context.md` and fetch, in parallel:

1. today's events from every configured calendar;
2. tomorrow's events, filtered to what matters;
3. the top inbox threads from the last two days.

Follow its rules for configuration, drop rules, rendering and failures.

## 5. Parse the input

Extract:

- mood and energy, and if the user said nothing about it, ask "Any mood or energy notes for today?" and wait;
- focus, meaning what they want to achieve today;
- new todos, meaning anything actionable for today;
- new follow-ups, meaning things to track, chase or be reminded of that are not today's action;
- notes, meaning everything else: reflections, observations and context.

## 6. Triage the todos

Combine the carryovers with the new todos, then:

1. estimate today's free focus hours from the calendar (working hours, minus meetings, minus a buffer);
2. judge each todo's effort (small, medium, large) and priority (stated deadlines, carryover age, the user's focus);
3. propose a split:

   > Given your calendar (<N>h of meetings, about <M>h free), here's my suggested split:
   >
   > **Today (<K> items):**
   > 1. [P1, small] <item>
   >
   > **Push to tomorrow (<J> items):**
   > - <item>: <low priority, no time, or waiting on X>
   >
   > Adjust anything?

4. wait for the user to confirm or adjust, and apply their changes.

Be direct here.
If there are 12 todos and six hours of meetings, say so.
If a carryover has slipped three or more days, flag it and ask whether to drop it rather than push it again.

## 7. Write the brief

Write `<raw>/daily-briefs/YYYY-MM-DD.md`.
Keep every heading exactly as shown, because `/kb-capture:update-brief`, the next brief's review and `/kb:compile` find sections by these headings.

```markdown
---
type: daily-brief
date: YYYY-MM-DD
source: voice | pasted | typed
mood: <one-line mood summary>
carried_from: YYYY-MM-DD  # omit if there was no earlier brief
---

# Daily brief: YYYY-MM-DD

## 🙂 Mood

<The user's mood and energy in their own words, cleaned up.>

## 📅 Today

<Today's events, rendered as the external-context reference describes.>

## 🔜 Tomorrow — key items

- **HH:MM** <title>: <why it matters>

_(Merged from the same calendar set.)_

## 🧭 Focus

<What the user wants to achieve today.>

## ✅ Todos — Today

- [ ] <item>, <priority tag if useful>
- [ ] <item> ↩️ _(carried from YYYY-MM-DD)_

## 🔁 Pushed to Tomorrow

- [ ] <item>: <reason>

## 🔁 Follow-ups

- [ ] <item>: <context or when>

## 📝 Notes

<Non-actionable content: reflections, observations, context. One sentence per line.>

## 📧 Inbox Signal — last 2 days

<Up to five threads, rendered as the external-context reference describes.>

## 📂 Raw Transcript

<!-- source: voice|pasted|typed -->
<The input verbatim, lightly cleaned for readability.>
<!-- /source -->
```

## 8. Commit

Stage today's brief, and the previous brief if step 2 changed it, then commit:

```bash
git add <raw>/daily-briefs/<today>.md <raw>/daily-briefs/<previous>.md
git commit -m "brief: YYYY-MM-DD"
```

Do not append to `<log>` and do not offer to compile, because a brief is personal and mostly transient.
`/kb:compile` later picks up only its `## 📝 Notes`, when the user runs it.

The user can also tick `- [x]` directly in Obsidian or any editor that renders checkboxes, and the next brief's review picks up whatever state the checkboxes are in.
