---
name: adopt
description: >
  Take over an existing folder of markdown as an Open Knowledge Format knowledge
  base. Surveys what is already there, decides which files are sources and which
  are already wiki-like, writes okf.toml describing the layout it *found* rather
  than imposing one, backfills OKF frontmatter with provenance recovered from git
  history, and gets kb-health green. Use when the user says "adopt this folder",
  "turn my notes into a KB", "make this an OKF bundle", "/kb:adopt", or points at
  a directory of existing markdown. For an empty directory, use /kb:init instead.
allowed-tools: Read Write Edit Bash(kb-*) Bash(git *) Bash(uv tool *) Bash(mkdir *) Bash(ls *) Bash(find *) Bash(test *) Bash(command *) Bash(date *) Bash(rg *) Bash(mv *)
---

# Adopt an existing folder

Turn a directory that already holds markdown into an OKF v0.2 bundle, without
destroying what is there.

The governing rule: **adopt describes what it finds, it does not impose a
layout.** `[paths]` in `okf.toml` is configurable precisely so a folder that
calls its zones `notes/` and `articles/` keeps calling them that. Renaming
someone's directories to match a convention is the failure mode this skill
exists to avoid.

## 0. Guard rails

If `okf.toml` already exists, this is a bundle. Stop and offer `/kb:health`.

If the directory holds no markdown at all, this is a blank start. Stop and offer
`/kb:init`.

**Never rewrite the body of any existing file in this step or any other.** You
may add or normalise frontmatter. You may move a file, with the user's
agreement. You may not edit what it says.

## 1. Check the tooling

Same check as `/kb:init` — the skills are useless without the package:

```bash
command -v kb-health && kb-health --help >/dev/null 2>&1 && echo "core ok"
```

If missing, stop and tell the user to install it:

```bash
uv tool install "okf-kb[ingest] @ git+ssh://git@github.com/carelvniekerk/okf-kb"
```

Probe the extras against the enabled plugins (`[ingest]` for `kb-ingest`,
`[video]` plus `ffmpeg` for `kb-video`) and report what is missing. A missing
extra is a warning, not a blocker.

## 2. Survey

Build a picture before proposing anything.

```bash
find . -name "*.md" -not -path "./.git/*" | head -100
find . -name "*.md" -not -path "./.git/*" | wc -l
find . -maxdepth 2 -type d -not -path "./.git*"
```

Then look at a representative sample — enough to answer:

- **What already has frontmatter?** `rg -l "^---" --glob "*.md"` against the
  total tells you how much backfill is coming.
- **Which files are sources and which are synthesis?** A fetched paper, a
  clipping, a meeting transcript is a source. A written-up explanation that
  draws on several of them is an article. The distinction drives everything
  else, so sample properly rather than guessing from directory names.
- **Is there an existing index?** A hand-maintained `README.md` or `INDEX.md`
  often encodes the taxonomy the user already thinks in. Read it — it is the
  best available draft of `[directories]` and `[[groups]]`.
- **Is it a git repo, and how deep is the history?** `git log --oneline | wc -l`.
  History is what lets you recover real provenance instead of stamping today.

## 3. Propose the mapping

Present a concrete plan and get agreement before moving a single file. Show:

- Which directory becomes `raw/` (sources) and which becomes `wiki/` (articles),
  **using their existing names** wherever they already exist.
- Any files you propose to move, and why. Keep this list as short as honestly
  possible. If sources and articles are already separated, move nothing.
- The starting taxonomy, drawn from their existing index or directory names.
- Anything you could not classify, listed explicitly rather than silently
  swept into one side.

If sources and articles are genuinely intermixed in one directory, say so
plainly and propose a split — but let the user confirm each ambiguous file
rather than batch-classifying by guess. Getting this wrong means an article gets
treated as an immutable source, or a source gets rewritten as an article.

## 4. Write okf.toml

Describe the agreed layout:

```toml
[bundle]
title = "…"
okf_version = "0.2"
kb_format = "1.0"

[paths]                 # only where the names differ from the defaults
wiki = "articles"
raw = "notes"

[directories]
"…" = "…"

[[groups]]
title = "…"
directories = ["…"]
```

Omit `[paths]` entirely when the folder already uses `wiki/` and `raw/`. Every
key has a default, and a shorter file is a clearer one.

Create `output/` and add it to `.gitignore` if it is not there.

## 5. Backfill frontmatter

This is the substantive work. Every non-reserved `.md` under the wiki zone needs
parseable frontmatter with a non-empty `type` to pass OKF §11.

Start by finding out how much is missing:

```bash
kb-provenance migrate
```

That reports articles declaring no provenance, listing any `## Sources` links
found in the body as a starting point. It modifies nothing.

For each article, write the frontmatter described in the bundle's `CLAUDE.md`.
Two fields deserve care:

- **`generated`** — recover it from git rather than stamping now. The creation
  commit's author trailer gives the producing model, its date gives `at`, and
  its subject prefix names the skill. `kb-provenance` uses the same machinery.
  Where history genuinely cannot say — a file that predates the repo, or was
  committed with no trailer — **leave `by` out** rather than guessing. An absent
  field is honest; a fabricated one poisons the trust signal.
- **`sources`** — where the body has a `## Sources` section, convert its links
  into the provenance array. Where it has none and the article's origin is not
  recoverable, leave the `sources` key out and say so in the handover. Do not
  invent provenance to satisfy a schema.

  Such an article still needs a `## Sources` section in its body, because
  `kb-health` requires one of every article and an adopted bundle would
  otherwise never reach green. Write the absence explicitly rather than faking a
  citation:

  ```markdown
  ## Sources

  _No source recorded — adopted from existing notes._
  ```

  That is honest, it passes the check, and it marks the article as thin for
  whoever reads it next.

**Never write `verified`.** Every adopted article is unverified until a human
reads it back against its sources. That is the correct state for a body of
writing you have just met.

Prefer existing curation over generated text: if a file already has a title or
summary the user wrote, use it verbatim rather than composing a new one.

## 6. Generate and verify

**Create `<wiki>/log.md` first**, before generating anything. The root index
always links to the operations log, so an index generated without it fails the
broken-link check — and a bundle that is born failing its own health check
teaches the user to ignore it. Seed it with the adoption entry from step 8; you
will not need to touch it again.

```bash
kb-index
kb-health
```

Work the health report until it is clean. Expect broken links — an adopted
folder often has relative links that assumed a different root, and `[[wikilinks]]`
that the OKF conventions do not use. Fix links; do not delete content to make a
check pass.

If `kb-health` exits 0, re-run `kb-index --health-passing`. Never claim passing
health without an exit-0 run in this session, and do not pass `--stamp-compiled`
— nothing has been compiled.

## 7. Write CLAUDE.md and settings

Write the bundle's `CLAUDE.md` and `.claude/settings.json` from the templates in
`../init/templates/`, substituting the same placeholders `/kb:init` uses, with
the layout you actually adopted rather than the default one.

If a `CLAUDE.md` already exists, **do not overwrite it.** Show the user what the
template would add, and merge only what they accept. Their existing instructions
may encode conventions you have not seen.

The same applies to `.vscode/settings.json` and `.vscode/tasks.json`, which
`/kb:init` also writes from `../init/templates/`. Offer them, and where a file is
already present **merge rather than replace** — an adopted folder's editor config
usually carries settings that have nothing to do with this bundle. Add the
folder-icon associations and the Health / Compile / Reindex / Stats tasks
alongside what is there; do not drop anything the user already had.

Watch for tasks that predate the adoption and no longer work — one invoking a
tool through a project environment this bundle no longer has, or a bare
`/compile` where the skills are now namespaced `/kb:compile`. Point those out
rather than silently leaving them broken.

## 8. Log, commit, hand over

Append to `wiki/log.md` (creating it if absent):

```markdown
## [YYYY-MM-DD] 🏗️ init | Existing notes adopted as an OKF bundle

Adopted <N> files: <M> sources, <K> articles. Frontmatter backfilled for <K>;
provenance recovered from git for <J>, absent for <K-J>. <Anything unresolved.>
```

Commit as `init: adopt existing notes as an OKF bundle`.

Then tell the user, briefly:

- What was classified as source versus article, and anything you were unsure of.
- Which articles have no recoverable provenance, so they know what is thin.
- That every article is unverified, and `/kb:verify` is the only way that changes.
- The next step: `/kb:compile` to integrate anything in `raw/` that is not yet
  reflected in the wiki.
