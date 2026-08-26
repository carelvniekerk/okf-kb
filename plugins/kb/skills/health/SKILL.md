---
name: health
description: >
  Run a full wiki health check — automated broken-link and image checks, followed by LLM-level
  analysis of stale content, missing articles, and structural improvements.
  Does not auto-fix; reports findings grouped by severity and waits for instruction.
when_to_use: When the user says "health check", "lint the wiki", "audit the wiki", or types /kb:health.
allowed-tools: Read Bash(kb-health)
disable-model-invocation: true
---

# Health Check

Run a full wiki health check.

**Step 1 — automated checks:**
Run `kb-health` to perform all mechanical checks (broken links, broken image references, missing image subdirectories, articles without Sources sections, stale source links, orphan articles).
This writes a timestamped report to `output/health-<YYYY-MM-DD-HHMM>.md`.
Read and summarise the report.

**Step 2 — LLM-level checks:**
After the automated report, also check:
- Concepts referenced in article text but never defined as their own wiki article (candidates for new articles).
- Potential contradictions or inconsistent claims across articles.
- Stale content: source files in `raw/` that appear to have been updated but whose corresponding wiki articles have not changed.

**Step 3 — report:**
Summarise all findings in the conversation, grouping by severity:
- **Blocking**: broken links or images (content is broken)
- **Important**: missing Sources sections, stale content
- **Suggestions**: missing articles for concepts, structural improvements

Propose concrete next steps for each issue.
Do not auto-fix — present findings and wait for instruction.
