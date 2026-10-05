---
name: adopt
description: >
  Take over an existing folder of markdown as an Open Knowledge Format knowledge
  base. Surveys what is there, separates sources from articles, writes okf.toml
  describing the layout it found, backfills OKF frontmatter with provenance
  recovered from git history, and gets kb-health green without rewriting any
  file's body. Use for "adopt this folder", "turn my notes into a KB" or "make
  this an OKF bundle". An empty directory belongs to /kb:init.
disable-model-invocation: true
allowed-tools: Read Write Edit Bash(kb-*) Bash(claude plugin list *) Bash(git log *) Bash(git status *) Bash(git diff *) Bash(git show *) Bash(git add *) Bash(git commit *) Bash(mkdir *) Bash(ls *) Bash(find *) Bash(rg *) Bash(date *)
---

# Adopt an existing folder

Turn a directory that already holds markdown into an OKF v0.2 bundle without destroying what is there.
Adopt describes the layout it finds and does not impose one: `[paths]` in `okf.toml` exists so that a folder calling its zones `notes/` and `articles/` keeps those names.

Never rewrite the body of an existing file, in any step.
You may add or normalise frontmatter, and you may move a file once the user has agreed to that move, but you may not change what a file says.
Moves are deliberately not pre-approved, so each one reaches the user as a permission prompt.

## Contents

- 0. Guard rails
- 1. Check the tooling
- 2. Survey
- 3. Propose the mapping
- 4. Write okf.toml and the log
- 5. Backfill frontmatter
- 6. Generate and verify
- 7. Write CLAUDE.md and settings
- 8. Commit and hand over

## 0. Guard rails

If `okf.toml` already exists, this is a bundle: stop and offer `/kb:health`.
If the directory holds no markdown at all, stop and offer `/kb:init`.

## 1. Check the tooling

Follow `${CLAUDE_PLUGIN_ROOT}/references/tooling.md` exactly.
Keep the list of enabled optional plugins for step 7.

## 2. Survey

Build a picture before proposing anything:

```bash
find . -name "*.md" -not -path "./.git/*" | head -100
find . -name "*.md" -not -path "./.git/*" | wc -l
find . -maxdepth 2 -type d -not -path "./.git*"
rg -l "^---" --glob "*.md" | wc -l
git log --oneline | wc -l
```

Then read a representative sample, enough to answer four questions.
How much already has frontmatter?
Which files are sources (a fetched paper, a clipping, a transcript) and which are synthesis drawing on several of them?
Is there a hand-maintained `README.md` or `INDEX.md`? If so, read it, because it is the best draft of `[directories]` and `[[groups]]`.
How deep is the git history? History is what lets step 5 recover real provenance instead of stamping today.

## 3. Propose the mapping

Present a concrete plan and get agreement before moving a single file:

- which directory becomes the raw zone and which the wiki zone, keeping the existing names;
- any file you propose to move, and why, keeping that list as short as honestly possible (if sources and articles are already apart, move nothing);
- the starting taxonomy, drawn from the existing index or directory names;
- every file you could not classify, listed rather than swept into one side.

Where sources and articles are intermixed in one directory, propose a split and let the user confirm each ambiguous file.
A misclassification either freezes an article as an immutable source or lets a source be rewritten as an article.

## 4. Write okf.toml and the log

Describe the agreed layout:

```toml
[bundle]
title = "…"
okf_version = "0.2"
kb_format = "1.0"

[paths]                 # only for names that differ from wiki, raw and output
wiki = "articles"
raw = "notes"

[directories]
"…" = "…"

[[groups]]
title = "…"
directories = ["…"]
```

Omit `[paths]` entirely when the folder already uses `wiki/` and `raw/`.
Then run `kb-doctor paths` and use the `wiki`, `raw`, `output` and `log` values it prints for every path from here on.
This skill calls them `<wiki>`, `<raw>`, `<output>` and `<log>`.

Create `<output>` and add it to `.gitignore` if it is missing.
Create `<log>` now, with this entry and nothing else, because the root index links to the log and a missing log fails the broken-link check:

```markdown
# Operations Log

## [YYYY-MM-DD] 🏗️ init | Existing notes adopted as an OKF bundle

Adopted <N> files: <M> sources, <K> articles. Frontmatter backfilled for <K>; provenance recovered from git for <J>, absent for <K-J>. <Anything unresolved.>
```

Fill in the counts in step 8, once they are known.

## 5. Backfill frontmatter

Every non-reserved `.md` under `<wiki>` needs parseable frontmatter with a non-empty `type` to meet OKF §11.
Find out how much is missing first:

```bash
kb-provenance migrate
```

It lists articles that declare no provenance, with any `## Sources` links in their bodies, and modifies nothing.
Write the frontmatter the bundle template's `CLAUDE.md` describes, and take care with two fields.

`generated`: recover it from git rather than stamping now.
The creation commit's author trailer gives the producing model, its date gives `at`, and its subject prefix names the skill.
Where history cannot say, because the file predates the repository or its commit has no trailer, leave `by` out.
An absent field is honest, and a fabricated one poisons the trust signal.

`sources`: convert the links in a `## Sources` section into the provenance array.
Where there is no such section and the origin is not recoverable, leave `sources` out and report it in the handover.
`kb-health` still requires a `## Sources` section in every article, so add one that states the absence instead of faking a citation:

```markdown
## Sources

_No source recorded. Adopted from existing notes._
```

This is the only body addition adopt makes, and it is an addition, not a rewrite.

Never write `verified`.
Every adopted article is unverified until a human reads it against its sources.
Where the user already wrote a title or summary, use it verbatim in `title` and `description`.
Anything you compose follows `${CLAUDE_PLUGIN_ROOT}/references/house-style.md`.

## 6. Generate and verify

```bash
kb-index
kb-health
```

Work the report until it is clean.
Expect broken links: adopted folders often have relative links that assumed another root, and `[[wikilinks]]` that the conventions do not use.
Fix links, and never delete content to make a check pass.
Once `kb-health` exits 0, run `kb-index --health-passing`.
Never claim passing health without that run in this session, and never pass `--stamp-compiled`.

## 7. Write CLAUDE.md and settings

Write the bundle's `CLAUDE.md` and `.claude/settings.json` from `${CLAUDE_SKILL_DIR}/../init/templates/`, with the placeholders `/kb:init` fills, and with the layout you adopted in place of `wiki/` and `raw/`.

If a `CLAUDE.md` exists, do not overwrite it.
Show the user what the template would add and merge only what they accept, because their instructions may encode conventions you have not seen.

If a `.claude/settings.json` exists, merge the template's permissions and `enabledPlugins` into it.
Replace `Skill(kb:wiki-search)` with `Skill(kb-query:wiki)`, since the old skill no longer exists, and make sure `Bash(kb-graph:*)`, `Bash(kb-read:*)` and `"kb-query@okf-kb": true` are present.
Parse the merged file before moving on.

Offer the two `.vscode/` files from the same templates, and merge rather than replace where one exists, keeping every setting and task the user already had.
While in a tasks file, fix two kinds of stale task, rewriting them rather than only reporting them, because a broken task fails silently until someone runs it:

- a tool run through a project environment the bundle no longer has, such as `uv run kb-health` where `kb-health` is now a uv tool;
- an unprefixed skill name from an old `.claude/skills/` copy.
  Compile, health, verify, init and adopt ship in `kb`, wiki in `kb-query`, capture, meeting and update-brief in `kb-capture`, ingest and transcribe in `kb-ingest`, and video in `kb-video`.
  So `/capture` becomes `/kb-capture:capture`, and the retired `/kb:wiki-search` and `/wiki-search` become `/kb-query:wiki`.

Also replace emoji written as `\uXXXX` escapes with the literal characters, so the labels stay readable in the source.

## 8. Commit and hand over

Fill in the counts in the `<log>` entry from step 4.
Stage the files this skill created or changed, by name or by directory (`okf.toml`, `<wiki>`, `.gitignore`, `CLAUDE.md`, `.claude/`, `.vscode/`, and any file the user agreed to move).
Then commit as `init: adopt existing notes as an OKF bundle`.
Do not use `git add -A`, because the folder may hold unrelated work in progress.

Tell the user, briefly:

- what was classified as source and as article, and anything you were unsure of;
- which articles have no recoverable provenance;
- that every article is unverified, and `/kb:verify` is the only way that changes;
- that `/kb:compile` integrates sources not yet reflected in the wiki, and treats the adoption commit as its starting point.
