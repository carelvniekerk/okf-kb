---
name: verify
description: >
  Record a human sign-off on a wiki article — read it back against its sources, confirm it is
  faithful, and append an OKF `verified` entry to its frontmatter.
  This is the only way a `human:` actor is ever written.
when_to_use: When the user says "verify", "sign off on", "review this article", or types /verify. Never invoke automatically.
allowed-tools: Read Edit Bash(kb-*) Bash(git *) Bash(date *)
disable-model-invocation: true
argument-hint: <wiki article path, or a directory to work through>
---

# Verify

Record a human sign-off on a wiki article. The article is: $ARGUMENTS

Under OKF v0.2 §5.2, `verified` records confirmation events and consumers derive a trust tier from it:

| Frontmatter state | Tier |
|---|---|
| no `verified` key | **unverified** |
| `verified` present, no `human:` actor | **machine-confirmed** |
| any `human:<id>` entry | **human-reviewed** |

Every article in this wiki is agent-written. Absent a `verified` key they all sit at **unverified**, which is the honest default — and it stays that way until a human actually reads one back against its sources.

## ⛔ The rule that matters

**Never write a `human:` actor on the user's behalf.**

Not because they asked you to verify a batch. Not because the article looks correct to you. Not because `kb-health` passes. A `human:<id>` entry is a claim that a specific person read a specific article against its specific sources and found it faithful. Only that person can make that claim, and only after actually doing it.

If you are unsure whether the user genuinely reviewed the content, ask. An unverified article is harmless; a falsely verified one silently poisons the trust signal this whole schema exists to carry.

## 1. Load the article and its sources

Read the article. Then read **every** path in its `sources[].resource`.

If a source no longer exists on disk, stop and report it — the article cannot be verified against a source that is gone. Run `kb-health` to confirm whether it is a known stale-source issue.

## 2. Present the comparison

Show the user, per source, what the article claims and where that claim comes from. Focus on:

- **Factual claims** — numbers, dates, names, version pins, quantitative results.
- **Attribution** — does a claim the article attributes to a source actually appear there?
- **Drift** — content that appears in the article but in none of its sources. Flag every instance. This is the most common failure and the main reason to verify at all.
- **Staleness** — anything the sources have since superseded.

Report honestly. If you find nothing wrong, say so plainly. If you find drift, list it and stop — the article should be corrected before it is signed off, not signed off with known defects.

## 3. Ask for explicit confirmation

Ask the user directly, naming the article:

> Have you read **<title>** against its <N> source(s) and confirmed it is faithful?

Accept only an unambiguous yes. "Looks fine", "sure", or silence are not sign-off. If they decline or hesitate, leave the article unverified and say so.

## 4. Append the entry

Only after explicit confirmation, add to the article's frontmatter:

```yaml
verified:
  - { by: human:<id>, at: 2026-08-16T21:50:00Z }
```

`<id>` identifies the person signing off, per the OKF actor convention (§7) — a short stable handle, not a display name. Use whatever this bundle's `CLAUDE.md` already uses in its examples; if it has none, ask the user which id to record and keep using it thereafter.

- Get the timestamp with `date -u +%Y-%m-%dT%H:%M:%SZ`.
- `verified` is a **list** — append to it, never overwrite. A second review is a second entry, and the history of who confirmed what and when is the point.
- Place it directly after `generated`, per the canonical key order the `okf-kb` package writes.
- Do not change `date_updated` — verification confirms content, it does not alter it.

## 5. Regenerate the index and log

The trust badge in the indexes is derived from `verified`, so refresh them:

```bash
kb-index
kb-health
```

Append to `wiki/log.md`:

```markdown
## [YYYY-MM-DD] ✅ verify | <Article title>

Human sign-off by `human:<id>` against <N> source(s). <Anything found and corrected first, or "no drift found".>
```

## 6. Commit

```bash
git add -A && git commit -m "verify: human sign-off on <article title>"
```

## Machine confirmation

`process:` actors are a different matter — they assert only that an automated check passed, not that content is faithful, so they may be written without asking. If `kb-health` passes cleanly you may record:

```yaml
verified:
  - { by: process:kb-health, at: <timestamp> }
```

This lifts an article from *unverified* to *machine-confirmed*. Be clear about what that does and does not mean: it says the links resolve and the schema is well-formed. It says nothing about whether the article is true.
