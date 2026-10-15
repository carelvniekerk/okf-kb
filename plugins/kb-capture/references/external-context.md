# Calendars and mailboxes

How the kb-capture skills fetch calendar events and mail.
`/kb-capture:capture brief` and `/kb-capture:update-brief` use all of it, and `/kb-capture:meeting` and `/kb-capture:capture meeting` use the calendar part to find a meeting's event.
Which accounts to read is configured per bundle in the `[capture]` table of `okf.toml`, and nothing about them is built into the skills.

## Contents

- The configuration
- Calendars
- Finding one meeting
- Rendering events
- Mailboxes
- Failures

## The configuration

Read `[capture]` from `okf.toml` before fetching anything.
If the table is absent, or declares no calendars and no mailboxes, skip the fetch entirely, say so once in one line and carry on with the user's own input.
Do not start a setup conversation in the middle of a capture.

```toml
[capture]
timezone = "Europe/Berlin"          # optional; used for day boundaries

[[capture.calendars]]
name = "Primary"                    # label shown in the brief and in failure notes
provider = "google"                 # google | microsoft
id = "you@example.com"              # google only; omit for microsoft
# event_type_filter = ["birthday"]  # optional, google only
# drop_subject_prefix = ["Daily /"] # optional: recurring noise to exclude

[[capture.mailboxes]]
name = "Gmail"                      # tag shown against each inbox line
provider = "gmail"                  # gmail | outlook
# folder = "Inbox"                  # outlook only
```

## Calendars

Fan out with one call per configured calendar, in parallel, then merge by start time and remove duplicates.

- `provider = "google"`: `mcp__claude_ai_Google_Calendar__list_events` with the entry's `id` as `calendarId`.
  Pass `eventTypeFilter` when the entry sets `event_type_filter`, and otherwise use the default.
- `provider = "microsoft"`: `mcp__claude_ai_Microsoft_365__outlook_calendar_search` with `query: "*"`, `afterDateTime` and `beforeDateTime` bracketing the day, and `order: "oldest"`.
  Pass no `calendarId`, so it reads the signed-in user's default calendar.

Where an entry sets `drop_subject_prefix`, discard every event whose subject starts with one of its values.
It takes a list of strings, and a bare string counts as a one-element list.
Recurring standups are noise: they never appear in a brief, not even as the first meeting of the day, and a refresh that brings them back is a regression.

## Finding one meeting

`/kb-capture:meeting` and `/kb-capture:capture meeting` look the meeting up on the calendars before they ask the user anything.
The user should never have to ask for the lookup, so run it whenever the request names a client, a topic or a time, such as "a meeting for client X from yesterday" or "from just now".

1. Work out the window from the request, in the `timezone` from `[capture]` or the machine's:
   "just now", "now" or no time given means events that started in the last three hours or are still running,
   "yesterday", a weekday or a date means that whole day.
2. Query the Google and Microsoft 365 calendar connectors in parallel for the window, using the call shapes under Calendars.
   Use the calendars `[capture]` declares.
   If it declares none, or no `[capture]` table exists, still try both connectors against their default calendar (`calendarId: "primary"` for Google, no `calendarId` for Microsoft 365), because the user asked for the lookup explicitly.
3. Merge the results, drop duplicates, and keep the events whose title, organiser or attendee names or email domains contain the client or topic words from the request.
   Filter locally, because the connectors are called with a wide query.
   With no client or topic words, keep every event in the window.
4. With one match, adopt it without asking.
   With several, list them numbered (`HH:MM: <title> (<n> attendees)`) and ask which.
   With none, say so in one line and fall back to asking the user for the title and attendees.
5. From the adopted event take the subject as the title, the start and end time, the full invitee list with each person's name, the organiser, and the location.
   Never invent a name that the event does not list.

A connector that fails or is not authenticated counts as a skip under Failures, and the other calendar still decides the match.

## Rendering events

- A timed event: `- **HH:MM-HH:MM** <title> · <location or "virtual"> · <N attendees[, external]>`.
- Prefix events from any calendar other than the first configured one with `[<calendar name>]`.
- A birthday: `- 🎂 **<Name>'s birthday**`. A public holiday: `- 🎉 **<Holiday>**`.
- End the section with `_(Merged from <the name of every calendar that returned>.)_`.

For tomorrow, keep only what plausibly matters: external meetings, the first meeting of the day, blocks of several hours or several attendees, birthdays of people the user knows personally, public holidays that affect the working day and anything flagged high priority.
Skip routine self-blocked focus time unless it is the only item.

## Mailboxes

Fan out across every configured mailbox for the last two days.

- `provider = "gmail"`: `mcp__claude_ai_Gmail__search_threads` with the query `newer_than:2d -category:promotions -category:social`.
- `provider = "outlook"`: `mcp__claude_ai_Microsoft_365__outlook_email_search` with the entry's `folder` (default `"Inbox"`), `afterDateTime: "2 days ago"` and `order: "newest"`.

From the combined results pick up to five signal-heavy threads: direct senders, replies needed, named people, work matters.
Mix mailboxes where warranted, without forcing an even split.
Write each as one line tagged with the mailbox's `name`:

```markdown
1. **[<mailbox name>] <Subject>** · <sender> · <one-line summary, or why it matters>
```

End the section with `_(Top 5 from <the name of every mailbox that returned>, last 48h, excluding promotions and social.)_`.

## Failures

A fetch failure never blocks a capture.
If one calendar fails, keep the others and note `_(<name> calendar unavailable)_` in the section.
If a mailbox fails, note `_(<name> unavailable)_` in the inbox section and carry on with the rest.
A connector that is not authenticated in this session counts as a skip, noted the same way.
The user re-authenticates by running `/mcp` and selecting the connector.
