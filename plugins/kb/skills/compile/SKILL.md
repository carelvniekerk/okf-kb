---
name: compile
description: >
  Run the full knowledge base compilation pipeline — transcribes handwritten notes, converts PDFs,
  detects new/modified/deleted sources, integrates each with type-dependent strategies
  (technical/discussion/experiment/meeting), updates INDEX.md, runs health checks, and commits.
when_to_use: When the user says "compile", "update wiki", "process new sources", or types /kb:compile.
allowed-tools: Read Write Edit Bash(kb-*) Bash(git *) Bash(grep *)
disable-model-invocation: true
---

# Compile

Run the full knowledge base compilation pipeline.
This is the living knowledge workflow — it classifies sources, discovers related articles, applies type-dependent update strategies, and handles source deletions.

## 1. Transcribe handwritten notes

Run `kb-ingest list-untranscribed` to find any untranscribed files in `raw/handwritten/`.
For each new file, open and read it using vision, transcribe the content to clean structured markdown (preserving headings, bullets, LaTeX for math, `<!-- unclear: ... -->` for ambiguous text), and save to `raw/transcriptions/<original-filename>.md`.
If any were transcribed, commit with `git add raw/transcriptions/ && git commit -m "transcribe: <N> handwritten notes"`.

## 2. Convert raw PDFs

Find any `.pdf` files directly in `raw/` (not in subdirectories) that do not yet have a corresponding `.md` file.
For each, run `kb-ingest extract-pdf <file>` to produce a markdown file alongside it.
Images go to `raw/images/<file-stem>/`.
If any were converted, commit with `git add raw/ && git commit -m "ingest: convert <N> PDFs to markdown"`.

## 3. Detect all changes

Compare against the **last compile**, not the working tree.
`/kb-ingest:ingest`, `/kb-capture:capture`, `/kb-ingest:transcribe` and `/kb-video:video` all commit the raw source and *then* offer to compile, so by the time compile runs the working tree is clean and a `HEAD` diff sees nothing.

```bash
LAST=$(git log -1 --format=%H --grep='^compile:')
git diff --name-only --diff-filter=AM "$LAST"..HEAD -- raw/   # new and modified
git diff --name-only --diff-filter=D  "$LAST"..HEAD -- raw/   # deleted
git status --porcelain -- raw/                                 # plus uncommitted edits
```

If no prior compile commit exists, treat every file in `raw/` as new (excluding `raw/handwritten/`).

**Skip any source whose frontmatter carries `compile: false`.**
It is an explicit opt-out; note each skip in the log entry (Step 8) as `⏭️ <path> — opted out via compile: false`.

Separate the results into three lists: **new sources**, **modified sources**, and **deleted sources**.

## 4. Handle deletions

For each deleted raw source:

1. Run `kb-provenance affected --json <deleted-file>` to find affected wiki articles.
2. For each affected article:
   a. Read the article.
   Look for `<!-- source: <deleted-file> -->` ... `<!-- /source -->` comment blocks.
   b. **If source boundary comments exist**: remove that entire content block.
   c. **If no boundary comments** (legacy article): read the article and the deleted source's last known content via `git show HEAD~1:<path>`.
   Use your judgment to identify and remove content that originated from the deleted source.
   d. Remove that source's entry from the `sources` array in frontmatter (match on `resource`).
   e. If the removed source was cited by `[^<id>]` footnotes, remove those references too — a footnote pointing at a deleted source is a broken citation.
   f. Update `date_updated` to today.
   g. Remove the deleted source from the `## Sources` section.
3. **If an article has zero remaining sources after removal**:
   - Check if other articles link to it (grep the wiki for its relative path).
   - If it has incoming links, keep it but add a blockquote at the top: `> ⚠️ This article's original sources have been removed. Content retained for cross-reference continuity.`
   - If it is an orphan with no incoming links, delete the file and remove its entry from `wiki/INDEX.md`.
4. After all deletions are processed, run `kb-health` to catch broken links.
Fix any that appear.

## 5. Integrate new and modified sources

For each new or modified source file:

### 5.0. Pre-process daily briefs (if applicable)

If the source path is under `raw/daily-briefs/` (or has `type: daily-brief` in frontmatter), apply this pre-processing before anything else.
Daily briefs are partially ephemeral — they contain personal/transient content alongside knowledge-worthy notes.

1. **Extract only the `## 📝 Notes` section** of the brief.
   Include any `_Update HH:MM:_` timestamped additions inside it.
2. **Ignore entirely** these sections — never compile their content into the wiki:
   - `## 🙂 Mood`
   - `## 📅 Today`
   - `## 🔜 Tomorrow — key items`
   - `## 🧭 Focus`
   - `## ✅ Todos — Today`
   - `## 🔁 Pushed to Tomorrow`
   - `## 🔁 Follow-ups`
   - `## 📧 Inbox Signal — last 2 days`
   - `## 📂 Raw Transcript`
   - Any `## 🔄 Session N` blocks (treat them the same way — only their notes sub-content is eligible).
3. **If the extracted Notes section is empty or trivial** (e.g. only whitespace, one short sentence with no identifiable topic), **skip the source entirely**.
   Note the skip in the compile log entry (Step 8) as `⏭️ raw/daily-briefs/YYYY-MM-DD.md — no knowledge-worthy notes`.
4. **Otherwise**, treat the extracted Notes content as the effective source content for steps 5a–5e below.
   When writing provenance markers in 5d, still use the full brief path: `<!-- source: raw/daily-briefs/YYYY-MM-DD.md -->`.
5. A single brief's Notes may contain multiple distinct topics.
   If so, process each topic as its own integration — do not force-merge unrelated notes into one article.

### 5.0b. Pre-process video sources (if applicable)

Sources under `raw/videos/<slug>-<id>.md` come from the `/kb-video:video` skill and are already a fully-structured article.
Treat them as a **promote**, not a re-synthesis:

- Keep the source's tags, type, and `source_type` as the basis for the wiki article's frontmatter.
- The Key Takeaways and Open Questions can usually carry over verbatim or with light editing.
- **Image paths must be rewritten.**
  The source uses `../images/<slug>-<id>/frame-XX.jpg` (relative to `raw/videos/`); a wiki article must use `../raw/images/<slug>-<id>/frame-XX.jpg` (relative to `wiki/`).
- Discovery (5b) and prompting (5c) still apply.

### 5a. Classify the source

Read the source fully.
Run `kb-provenance classify <file> --json` as a heuristic hint, then make your own judgment.
Classify as one of:

| Type | Description | Examples |
|---|---|---|
| `technical` | Documentation, tutorials, technical references, papers, tool guides | arXiv papers, API docs, installation guides |
| `discussion` | Design debates, consensus-building, architectural decisions | RFC discussions, design docs, pros/cons analyses |
| `experiment` | Benchmarks, ablation studies, A/B test outcomes, evaluation results | Experiment logs, benchmark tables, eval reports |
| `meeting` | Action items, decisions, status updates, meeting minutes | Standup notes, sprint reviews, 1:1 notes |

### 5b. Discover related articles

Search for existing related articles:
1. Run `kb-search "<key terms from source>" --json-output` to find semantically related articles.
2. Run `kb-provenance map --json` to check if this source already contributes to existing articles (critical for modified sources).
3. Read the top 3–5 search results to assess genuine relatedness.

### 5c. Prompt the user

**If related articles are found**, present the user with clear options:

> 📋 Source `raw/meeting-april-8.md` classified as **meeting**.
> Found related articles:
>
> 1. 📄 [Project X Meeting Log](wiki/meetings/project-x.md) — 85% related (same project)
> 2. 📄 [Architecture Decisions](wiki/research/architecture.md) — 40% related (overlapping topic)
>
> Options:
> - **(a)** Update **Project X Meeting Log**
> - **(b)** Update **Architecture Decisions**
> - **(c)** Create a **new article**

Wait for the user's response before proceeding.

**If no related articles are found**, proceed directly to create a new article.

**For modified sources** that already have wiki articles (found via `kb-provenance map`), default to updating those articles without prompting — but mention what you're doing.

### 5d. Apply type-dependent integration strategy

#### Creating a new article

Follow the standard article format from CLAUDE.md.
Additionally:
- Set `type`, `title` and a one-sentence `description` (the indexes are generated from `description`, so write it to stand alone).
- Set `source_type` to the classification from 5a.
- Add an entry to `sources` for each raw source: `id` (kebab-case, unique in the article), `resource` (repo-root-relative `raw/...` path), `title`, `author`, `last_modified`.
- Stamp `generated` with your own model id, an ISO 8601 UTC timestamp, `skill: compile@kb-<version>` (the `version` in this plugin's `.claude-plugin/plugin.json`), and `commit` once committed. A bundle carrying its own in-repo copy of this skill instead stamps `compile@<sha>`, from `git log -1 --format=%h -- .claude/skills/compile/` — either way the point is that a hallucination traces to the exact producer version that emitted it.
- Leave `status` at `stable` unless the article is genuinely provisional (`draft`) or superseded (`deprecated`).
- Add `stale_after` if the content is pinned to a moving target — library versions, build steps, a project's lifespan.
- **Never write `verified`.** Absent means unverified, which is the honest state. Only `/kb:verify` may add it.
- Set `date_updated` to today.
- Wrap the main content in source provenance markers:

  ```markdown
  <!-- source: raw/path/to/source.md -->
  ... content derived from this source ...
  <!-- /source -->
  ```

#### Updating an existing article — Meeting sources (`meeting`)

Meetings are **additive** — never overwrite previous meeting content.
- Find or create a chronological section (e.g., `## Meeting History` or `## Session Log`).
- Append new meeting information with a date subheading: `### YYYY-MM-DD — <meeting topic>`.
- Extract **action items** into a dedicated subsection.
Mark items from previous meetings as completed (✅) if the new meeting confirms completion.
- Extract **decisions** and add them to a running decisions list or table.
- Update `## 🎯 Key Takeaways` to reflect the latest state and most important decisions.
- Update `## 🔮 Open Questions` — resolve questions answered by new meeting, add new ones.
- Wrap new content in `<!-- source: raw/path -->` ... `<!-- /source -->` markers.

#### Updating an existing article — Discussion sources (`discussion`)

Discussions **evolve** — track how consensus changes.
- If the new source extends an existing discussion thread:
  - Add new points under existing headings where they fit.
  - If a position has been superseded, mark it with ~~strikethrough~~ or a `**[Superseded YYYY-MM-DD]**` label, and add the new position.
  - Track consensus evolution — if a decision was reached, make it prominent.
- If the new source opens a new thread within the same topic:
  - Add a new subsection for the new discussion thread.
- Update `## 🎯 Key Takeaways` to reflect current consensus.
- Update `## 🔮 Open Questions` — resolve settled questions, add newly raised ones.
- Wrap new content in source provenance markers.

#### Updating an existing article — Experiment sources (`experiment`)

Experiment results require **careful data management** — never silently overwrite results.
- **Same experiment, new data**: Append rows to existing results tables.
Add a note indicating when results were added (e.g., `*Updated YYYY-MM-DD*` below the table).
- **Same methodology, improved results**: Update the table but keep a "Previous results" collapsed section or footnote so the progression is visible.
- **Different methodology**: Create a new results table/section clearly labeled with the methodology.
Do not merge with existing tables.
- **Contradictory results**: Present both with clear labeling.
Add to Open Questions why results differ.
- Update `## 🎯 Key Takeaways` based on the latest and most reliable results.
- Update `## 🔮 Open Questions` — note resolved questions, add new ones prompted by results.
- Wrap new content in source provenance markers.

#### Updating an existing article — Technical sources (`technical`)

Technical content should always represent the **current state of knowledge**.
- **Version-specific information**: If the source mentions specific versions, use version-labeled subsections or admonitions:

  ```markdown
  > **v2.0** (YYYY-MM-DD): New feature X replaces deprecated feature Y.
  ```

  Keep version history where it aids understanding; remove stale version info that is no longer relevant.
- **General updates**: Overwrite stale information cleanly.
The article should read as a current, authoritative reference — not an archaeological record.
- **Conflicting information**: If new source contradicts existing content, the new source wins (it is more recent).
Replace the old content, do not leave both.
- **Additive information**: If new source adds to existing knowledge without contradicting it, integrate naturally into the existing structure.
- Update `## 🎯 Key Takeaways` if the update changes core insights.
- Update `## 🔮 Open Questions` as needed.
- Wrap new content in source provenance markers.

### 5e. Update metadata

After integrating each source:
- Add the source to `sources` in frontmatter if not already present (full mapping — `id`, `resource`, `title`, `author`, `last_modified`).
- Re-stamp `generated` — a substantive rewrite is a new generation event, so record the model and skill version that produced it.
- Set `date_updated` to today.
- Add the source to the `## Sources` section as a markdown link.
- Update `## Related Articles` if cross-references were discovered during integration.
- Add backlinks in both directions between any articles that reference each other.

## 6. Regenerate the indexes

Do **not** hand-edit any `INDEX.md`. They are generated from article frontmatter:

```bash
kb-index --stamp-compiled
```

This rewrites `wiki/INDEX.md` and every per-directory `INDEX.md`, recomputing the article count and unique source count. Hand-maintaining those counters is what let the old `sources-41` badge drift away from every real total.

`--stamp-compiled` moves the compile-date badge to today. **This skill is the only caller that may pass it.** Every other invocation — the pre-commit hook, `/kb:verify`, a manual run — leaves the badge as it stands, because the badge records when the wiki was last compiled, not when `kb-index` last ran. A bare `kb-index` preserves it.

The health badge is emitted as `unknown` by default and is only set to passing in step 7.

## 7. Run health check

Run `kb-health`.
- If it passes (exit 0): re-run `kb-index --stamp-compiled --health-passing` to stamp the passing badge. Keep `--stamp-compiled` on this re-run so the date is set explicitly rather than inherited from whatever step 6 happened to leave on disk.
- If it fails: fix the reported issues first, then re-run until clean. Never pass `--health-passing` without a genuine exit-0 run in this session.

## 8. Append to log

Add a detailed entry to `wiki/log.md`:

```markdown
## [YYYY-MM-DD] 📚 compile | Brief title

**Sources processed:**
- 🆕 `raw/new-source.md` (technical) → created [New Article](./path/article.md)
- 🔄 `raw/updated-source.md` (experiment) → updated [Existing Article](./path/article.md)
- 🗑️ `raw/removed-source.md` → pruned content from [Article](./path/article.md) (2 sources remaining)

**Decisions:** create vs update choices, classification rationale for non-obvious cases.
```

## 9. Commit

Run `git add -A && git commit -m "compile: <brief summary of what was integrated>"`.
