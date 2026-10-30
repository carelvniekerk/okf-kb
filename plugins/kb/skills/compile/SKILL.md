---
name: compile
description: >
  Run the knowledge base compilation pipeline. Transcribes handwritten notes,
  converts PDFs, Office documents and e-books, detects new, modified and deleted
  sources since the last compile,
  integrates each into the wiki with a strategy chosen by source type, regenerates
  the indexes, runs the health check and commits. Use when the user says
  "compile", "update the wiki" or "process new sources".
disable-model-invocation: true
allowed-tools: Read Write Edit Bash(kb-*) Bash(git log *) Bash(git diff *) Bash(git status *) Bash(git show *) Bash(git add *) Bash(git rm *) Bash(git commit *) Bash(basename *) Bash(date *) Bash(rg *) mcp__savvy-progress__progress
---

# Compile

Integrate new, modified and deleted raw sources into the wiki, with provenance tracked per source.
The wiki is only as trustworthy as its link to the sources, so the rule that governs every step is: write only what a source supports.

## Contents

- Rules for everything you write
- 0. Resolve the bundle's paths
- 1. Transcribe handwritten notes
- 2. Convert raw documents
- 3. Detect changes
- 4. Handle deletions
- 5. Integrate new and modified sources
- 6. Regenerate the indexes
- 7. Run the health check
- 8. Append to the log
- 9. Commit
- Progress reporting

## Rules for everything you write

- Every claim in an article must come from one of its sources.
  Do not add facts, numbers, dates, names or examples from training data, even when you are confident of them.
  If background is needed to make an article readable, say in the text that it is background and not from the source, or leave it out.
- Report what the source says, not what you infer from it.
  Where you draw a connection between sources, write it as an inference ("Taken together, A and B suggest...") and put it under `## 🔮 Open Questions` when it is uncertain.
- Never write `verified`.
  Absent means unverified, which is the honest state, and only `/kb:verify` may add it.
- Never hand-edit an `INDEX.md`, because `kb-index` generates them.
- Prose follows `${CLAUDE_PLUGIN_ROOT}/references/house-style.md`.

## 0. Resolve the bundle's paths

Run `kb-doctor paths`.
Its `wiki`, `raw` and `log` values are what this skill calls `<wiki>`, `<raw>` and `<log>`, and they are not always `wiki/` and `raw/`.
Run every command below from the bundle root it prints.

## 1. Transcribe handwritten notes

Run `kb-ingest list-untranscribed`.
For each file it lists, read it with vision and write clean structured markdown to `<raw>/transcriptions/<stem>.md`, where `<stem>` is the source filename without its extension, because that is how `list-untranscribed` matches them.
Keep the original structure, describe diagrams in text, write maths in LaTeX and mark unreadable passages as `<!-- unclear: ... -->` rather than guessing.
Never modify or delete anything in `<raw>/handwritten/`.
If you transcribed anything, commit it: `git add <raw>/transcriptions/ && git commit -m "transcribe: <N> handwritten notes"`.

## 2. Convert raw documents

Run `kb-ingest list-unconverted --json-output`.
It groups the files in `<raw>` by what conversion still owes them, and it needs no extra, so it also works in a core-only install.
Compile works only from markdown, so the converted `.md` is the source and `sources.resource` points at it, never at the original.

- `missing` and `stale`: run `kb-ingest convert <file>` on each.
  It writes the markdown beside the original, records the original's hash in `converted_sha256` and saves embedded images to `<raw>/images/<stem>/`, linked from the markdown.
  Commit what it wrote: `git add <raw> && git commit -m "ingest: convert <N> documents to markdown"`.
- `unsupported`: formats no converter reads, such as `.doc` and `.ppt`.
  List them in the log entry and leave them alone.
- `conflicting`: another original, such as a PDF with the same name, already owns the markdown file.
  List them in the log entry and ask which original to keep.
  Never pass `--force` for these.
- `orphaned`: the markdown's original no longer exists.
  Ask whether to delete the markdown too.
  If the user agrees, run `git rm <md>` and commit it on its own: `git commit -m "ingest: remove <N> markdown files whose originals are gone"`.
  Do that before step 3, so step 4 prunes the wiki articles that cited it.
- `legacy`: markdown with no conversion record, which may be hand-written.
  Mention them once and offer `kb-ingest convert --force <file>`, which replaces the body and keeps the frontmatter.
  If the file's frontmatter cannot be read, `--force` discards it and warns, so say that when you offer it.
  Never reconvert them unasked.

`kb-ingest convert` needs the `[ingest]` extra, which the `kb` plugin does not.
If it reports the extra missing, skip the conversions, list the unconverted files in the log entry and relay the install command from the error verbatim.
Never compose an install command yourself.

## 3. Detect changes

Compare against the last compile, not the working tree.
Change detection considers only markdown files.
An original such as a `.pdf` or `.docx` is never integrated, and neither is anything under `<raw>/images/`.
The ingest, capture, transcribe and video skills commit or stage the raw source and then offer to compile, so a `HEAD` diff alone sees nothing.
`init:` commits count as a baseline too, so the first compile after `/kb:adopt` does not re-integrate everything the adoption just mapped.

```bash
LAST=$(git log -1 --format=%H -E --grep='^(compile|init):')
git diff --name-only --diff-filter=AM "$LAST"..HEAD -- '<raw>/*.md'   # new and modified
git diff --name-only --diff-filter=D  "$LAST"..HEAD -- '<raw>/*.md'   # deleted
git status --porcelain -- <raw>                                        # not yet committed
```

In a git pathspec `*` also matches `/`, so `'<raw>/*.md'` reaches every subfolder.
Ignore the files in the `git status` output that are not markdown.

If `LAST` is empty, there is no baseline: treat every markdown file in `<raw>` as new, except those under `<raw>/handwritten/` and `<raw>/images/`.

Uncommitted files need the user's word before they are compiled.
A live meeting note from `/kb-capture:meeting` stays uncommitted until the meeting ends, and a video article from `/kb-video:video` is written but not committed.
List the uncommitted files and ask which to include.

Skip any source whose frontmatter has `compile: false`, and note each skip in the log as `⏭️ <path>: opted out via compile: false`.
Separate the rest into new, modified and deleted sources.

## 4. Handle deletions

For each deleted source:

1. Run `kb-provenance affected --json <path>` to find the affected articles.
2. Recover the source's last content from the commit before the one that deleted it:

   ```bash
   DEL=$(git log -1 --format=%H --diff-filter=D -- <path>)
   git show "$DEL^:<path>"
   ```

3. In each affected article, remove the `<!-- source: <path> -->` ... `<!-- /source -->` blocks.
   Where an older article has no markers, compare it with the recovered content and remove what came from that source.
4. Remove the source's entry from `sources` (matched on `resource`), its `[^<id>]` footnotes and its line under `## Sources`, and set `date_updated` to today.
5. If an article has no sources left, search `<wiki>` for links to it.
   With incoming links, keep it and add `> ⚠️ This article's original sources have been removed. Content retained for cross-reference continuity.` at the top.
   Without them, delete the file. Step 6 drops it from the indexes.

Then run `kb-health` and fix the broken links it reports.

## 5. Integrate new and modified sources

For each source, in order:

1. Pre-process it if it is a daily brief or a video source, as `${CLAUDE_SKILL_DIR}/references/strategies.md` describes.
2. Read it fully, run `kb-provenance classify <file> --json` as a hint and classify it yourself as `technical`, `discussion`, `experiment` or `meeting`.
3. Find related articles: `kb-search "<key terms>" --json-output`, then `kb-provenance map --json` to see whether this source already feeds an article.
   Read the top three to five hits to judge real relatedness.
4. Decide where it goes.
   A modified source that already feeds articles updates those articles without asking, and you say which.
   Otherwise, if related articles exist, show them numbered with a one-line reason each, offer "update one of these" or "create a new article", and wait for the answer.
   With no related articles, create a new one.
5. Write the content with the strategy for its type from `${CLAUDE_SKILL_DIR}/references/strategies.md`.
   Read that file the first time you integrate a source in this run.
6. Update the metadata, as below.

### New articles

Follow the article format in the bundle's `CLAUDE.md`, and also:

- set `type`, `title` and a one-sentence `description` that reads on its own, because the indexes are generated from it;
- set `source_type` to the classification;
- add a `sources` entry per raw source with `id` (kebab-case, unique in the article), `resource` (the root-relative path), `title`, `author` and `last_modified`;
- stamp `generated` with your model id, an ISO 8601 UTC timestamp and `skill: compile@<version>`, then `commit` once committed;
- leave `status` at `stable` unless the article is genuinely `draft` or `deprecated`, and add `stale_after` when the content is pinned to a moving target such as a library version;
- wrap the content in `<!-- source: <path> -->` ... `<!-- /source -->` markers.

Find `<version>` once per run, so a bad article can be traced to the copy of this skill that wrote it.
An installed plugin lives in a cache directory named after the okf-kb commit it was installed from, and that directory is not a git repository:

```bash
basename "${CLAUDE_PLUGIN_ROOT}"
```

If that prints a hexadecimal hash, it is the version.
Otherwise this is a checkout loaded with `--plugin-dir`, and the last commit to touch the plugin is:

```bash
git -C "${CLAUDE_PLUGIN_ROOT}" log -1 --format=%h -- .
```

If neither gives a hash, write a bare `skill: compile` rather than inventing one.

### Metadata after every integration

- Add the source to `sources` if it is not there.
- Re-stamp `generated`, because a substantive rewrite is a new generation event.
- Set `date_updated` to today and add the source to `## Sources` as a markdown link.
- Update `## Related Articles` and add backlinks in both directions between articles that now reference each other.
- If an article landed in a `<wiki>` subdirectory with no `[directories]` entry in `okf.toml`, add one with a display title and place it in the best-fitting `[[groups]]` entry.
  An unclaimed directory renders under "📁 Unfiled", so this is about naming the section, not correctness.

## 6. Regenerate the indexes

```bash
kb-index --stamp-compiled
```

This rewrites every `INDEX.md` and moves the compile-date badge to today.
This skill is the only caller allowed to pass `--stamp-compiled`, because the badge records when the wiki was last compiled, not when `kb-index` last ran.

## 7. Run the health check

Run `kb-health`.
If it exits 0, run `kb-index --stamp-compiled --health-passing`, keeping `--stamp-compiled` so the date is set explicitly.
If it fails, fix what it reports and re-run until it exits 0.
Never pass `--health-passing` without an exit-0 run in this session.

## 8. Append to the log

Append to `<log>`:

```markdown
## [YYYY-MM-DD] 📚 compile | <brief title>

**Sources processed:**
- 🆕 `<raw>/new-source.md` (technical): created [New Article](./path/article.md)
- 🔄 `<raw>/updated-source.md` (experiment): updated [Existing Article](./path/article.md)
- 🗑️ `<raw>/removed-source.md`: pruned content from [Article](./path/article.md), 2 sources remaining

**Decisions:** create or update choices, and the reasoning behind any classification that was not obvious.
```

## 9. Commit

Stage the wiki, `okf.toml` and the raw files you compiled that were not yet committed, and nothing else:

```bash
git add <wiki> okf.toml <each uncommitted source the user included>
git commit -m "compile: <brief summary of what was integrated>"
```

Do not use `git add -A`, because the bundle may hold a live meeting note or other work in progress.

## Progress reporting

Report only the integration loop in step 5, and only when it has two or more sources.
Report to savvy-progress from the main session only, through `mcp__savvy-progress__progress`.
If the tool is deferred, load it with `ToolSearch select:mcp__savvy-progress__progress`, and skip reporting silently if it is absent.
Never call `mcp__savvy-progress__step` here, because only agents report steps.
This skill spawns no agents, so send no `tasks`, because their titles would match no `Agent` run.
Once step 3 has settled which sources to integrate, call it with `title: "Compile wiki"`, `total: <N>` and `phase: "delegate"`, where `<N>` counts the new and modified sources the user agreed to include.
Without a `phase` the bar stays on "Plan" and never shows the count.
Send `done: <n>` after each source's metadata is updated, and keep `title` identical across the calls.
End every path, an abort included, with `finished: true` and `phase: "close"`, so the bar does not stay up when the user stops the run.
