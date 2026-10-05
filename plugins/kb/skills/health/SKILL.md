---
name: health
description: >
  Run a full wiki health check. Runs the automated link, image and provenance
  checks, then reviews the wiki for undefined concepts, contradictions between
  articles and stale content, and reports the findings by severity without fixing
  anything. Use when the user says "health check", "lint the wiki" or "audit the
  wiki".
disable-model-invocation: true
allowed-tools: Read Bash(kb-health) Bash(kb-health *) Bash(kb-doctor paths) Bash(kb-search *) Bash(kb-graph *) Bash(kb-stats) Bash(kb-stats *) Bash(kb-provenance map *) Bash(git log *) Bash(rg *)
---

# Health check

Report the wiki's health and wait for instructions.
This skill fixes nothing, so the user decides what changes.

## Workflow

1. Run `kb-doctor paths`, then `kb-health`.
   `kb-health` checks broken links and images, missing image directories, articles without a Sources section, stale source links and orphans, and writes a report to `<output>/health-<YYYY-MM-DD-HHMM>.md`.
   Read the report.
2. Review what the automated checks cannot see:
   - concepts the articles use but no article defines, using `kb-search` to confirm the absence;
   - claims that contradict each other across articles;
   - stale content: a source changed after the articles built from it.
     Compare `git log -1 --format=%cs -- <source>` with each article's `date_updated`, using `kb-provenance map --json` to pair them.
   - structure: oversized sections, orphans and weakly linked clusters, from `kb-stats` and `kb-graph`.
3. Report, as below.

## Report

Put the most serious finding first, even when there are few.
Group findings by severity:

- **Blocking**: broken links or images, where content is broken now.
- **Important**: missing Sources sections, stale content, contradictions.
- **Suggestions**: missing articles for concepts, structural improvements.

Give each finding its file path and one concrete next step.
Tag findings from step 2 by confidence: a contradiction you confirmed by reading both passages is stated plainly, and one inferred from summaries or search snippets is tagged [Likely] or [Guessing].
If a check found nothing, say so in one line, because a clean result is a finding too.
If `kb-health` exited non-zero for a reason other than the issues it lists, report that first.
