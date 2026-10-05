---
name: verify
description: >
  Record a human sign-off on a wiki article. Reads the article back against every
  source it cites, reports drift and unsupported claims, and only after the user's
  explicit confirmation appends an OKF verified entry with their human id. Use
  when the user says "verify", "sign off on" or "review this article against its
  sources".
disable-model-invocation: true
allowed-tools: Read Edit Bash(kb-doctor paths) Bash(kb-index) Bash(kb-index *) Bash(kb-health) Bash(kb-health *) Bash(git add *) Bash(git commit *) Bash(date *)
argument-hint: <wiki article path, or a directory to work through one article at a time>
---

# Verify

Record a human sign-off on a wiki article. The article is: $ARGUMENTS

Under OKF v0.2 §5.2, `verified` records confirmation events, and consumers derive a trust tier from it:

| Frontmatter | Tier |
| --- | --- |
| no `verified` key | unverified |
| `verified` present, no `human:` actor | machine-confirmed |
| any `human:<id>` entry | human-reviewed |

Every article in the wiki is agent-written, so each one stays unverified until a human reads it back against its sources.

## The rule that matters

Never write a `human:` actor on the user's behalf.
A `human:<id>` entry claims that a named person read this article against its sources and found it faithful, and only that person can make the claim.
A batch request, an article that looks right to you, or a passing `kb-health` does not change this.
An unverified article is harmless, and a falsely verified one silently corrupts the trust signal the schema exists to carry.
When unsure whether the user really reviewed the content, ask.

## Contents

- 1. Load the article and its sources
- 2. Present the comparison
- 3. Ask for explicit confirmation
- 4. Append the entry
- 5. Regenerate, log and commit
- Machine confirmation

## 1. Load the article and its sources

Run `kb-doctor paths`, then read the article and every path in its `sources[].resource`.
If a source is missing from disk, stop and report it, because an article cannot be verified against a source that is gone.
For a directory, work through it one article at a time, with a separate confirmation for each.

## 2. Present the comparison

Show the user, per source, what the article claims and where each claim comes from.
Lead with the problems:

- drift, meaning content that appears in none of the sources, which is the most common failure and the main reason to verify;
- attribution, meaning a claim credited to a source that does not contain it;
- factual detail: numbers, dates, names, versions and quantitative results;
- staleness, meaning anything a newer source has superseded.

Mark each problem as definite (absent from every source after reading them in full) or possible (a paraphrase you could not match with confidence).
If you find nothing, say so plainly.
If you find drift, list it and stop, because the article should be corrected before sign-off, not signed off with known defects.

## 3. Ask for explicit confirmation

Ask, naming the article:

> Have you read **<title>** against its <N> source(s) and confirmed it is faithful?

Accept only an unambiguous yes.
"Looks fine", "sure" and silence are not sign-off.
If the user declines or hesitates, leave the article unverified and say so.

## 4. Append the entry

Only after an explicit yes, add to the article's frontmatter:

```yaml
verified:
  - { by: human:<id>, at: 2026-08-16T21:50:00Z }
```

`<id>` is the short stable handle from the OKF actor convention (§7), such as `human:carel`.
Use the one the bundle's `CLAUDE.md` uses in its examples, and if it has none, ask which id to record.

- Take the timestamp from `date -u +%Y-%m-%dT%H:%M:%SZ`.
- `verified` is a list: append, never overwrite, because the history of who confirmed what and when is the point.
- Place it directly after `generated`, the canonical key order the `okf-kb` package writes.
- Leave `date_updated` alone, since verification confirms content without changing it.

## 5. Regenerate, log and commit

The trust badge in the indexes derives from `verified`, so regenerate them:

```bash
kb-index
kb-health
```

If `kb-health` exits 0, run `kb-index --health-passing`, so the badge is not left at `unknown`.

Append to `<log>`:

```markdown
## [YYYY-MM-DD] ✅ verify | <Article title>

Human sign-off by `human:<id>` against <N> source(s). <What was found and corrected first, or "No drift found.">
```

Stage the wiki zone only, so unrelated work in progress stays out of the commit:

```bash
git add <wiki>
git commit -m "verify: human sign-off on <article title>"
```

## Machine confirmation

A `process:` actor asserts only that an automated check passed, so it may be written without asking.
After a clean `kb-health` run you may record:

```yaml
verified:
  - { by: process:kb-health, at: <timestamp> }
```

This lifts an article to machine-confirmed.
Tell the user what that means: the links resolve and the schema is well-formed, and nothing more about whether the article is true.
