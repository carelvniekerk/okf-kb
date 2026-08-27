# okf-kb

Tooling and skills for agent-maintained [Open Knowledge Format][okf] knowledge
bases.

[okf]: https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf

## The idea

Notes rot because writing them and maintaining them are different jobs, and
only the first one is interesting. You collect a paper, a video, a meeting note,
a scribbled page — and then nobody goes back to reconcile the new thing against
the twenty things already there.

okf-kb splits those jobs between you and an agent, along a line that keeps both
honest:

```text
raw/                            wiki/
sources you collect      →      articles the agent maintains
never rewritten                 regenerated, cross-linked, indexed
```

**`raw/` is yours.** Papers, clippings, transcripts, voice notes. Whatever
lands here keeps its body verbatim — nothing rewrites what a source says.

**`wiki/` is the agent's.** An OKF v0.2 bundle of synthesised articles,
cross-linked, with generated indexes. You do not hand-edit it.

**Compilation moves the first into the second**, with provenance tracked per
source. Every claim traces back to the file it came from, which is what makes
the wiki safe to trust and safe to regenerate: delete a source and the agent
knows exactly which articles are now standing on nothing.

The knowledge base is a plain git repo of markdown. No database, no service,
no lock-in — if you stop using these tools tomorrow, you still have your notes.

## How you use it

Day to day the loop is short:

```bash
/kb-ingest:ingest 2402.12345         # a paper, a URL, a PDF → raw/
/kb-video:video <youtube-url>        # a talk → transcript + frames → raw/
/kb-capture:capture note             # something you said out loud → raw/
/kb-capture:capture meeting granola  # a Granola transcript + its calendar event → raw/

/kb:compile                          # integrate everything new into wiki/
```

`/kb:compile` is the pipeline that does the real work. It transcribes
handwritten notes, converts PDFs, detects which sources are new, modified or
deleted, classifies each one, finds the existing articles it relates to,
applies a type-appropriate update strategy, regenerates the indexes, runs the
health checks, and commits.

Then you *ask questions*, which is the point of having done any of it:

```bash
/kb:wiki-search what do we know about speculative decoding
```

Wiki first, web second — the skill exists to stop an agent googling something
you already wrote down.

Periodically:

```bash
/kb:health          # broken links, orphans, stale sources, missing Sources sections
/kb:verify <path>   # record that a human read an article against its sources
```

`/kb:verify` is the only path to a `human:` sign-off in an article's
provenance. Nothing automated can write one, because the whole meaning of that
entry is that a specific person checked a specific article and found it
faithful.

## Getting started

Install the tools:

```bash
uv tool install "okf-kb[ingest] @ git+ssh://git@github.com/carelvniekerk/okf-kb"
```

Install the skills:

```bash
claude plugin marketplace add carelvniekerk/okf-kb
claude plugin install kb@okf-kb
```

Then, in the directory you want the knowledge base to live in:

```bash
/kb:init            # an empty directory
/kb:adopt           # a directory that already holds markdown
```

`/kb:init` interviews you briefly, scaffolds the structure, writes `okf.toml`
and a `CLAUDE.md` describing the bundle to future agents, and leaves you with a
green `kb-health`. `/kb:adopt` does the harder thing: it surveys what is
already there, decides which files are sources and which are already
wiki-shaped, writes an `okf.toml` describing **the layout it found** rather
than imposing one, and backfills OKF frontmatter with provenance recovered from
git history. Neither rewrites the body of an existing file.

### Picking extras

Extras are opt-in so a core install stays light. Match them to the plugins you
install — a missing extra does not fail at install time, only at the moment the
skill that needs it runs:

| Plugins you want | Install |
|---|---|
| `kb`, `kb-capture` | `okf-kb` |
| …and `kb-ingest` | `okf-kb[ingest]` |
| …and `kb-video` | `okf-kb[video]` |
| …both | `okf-kb[all]` |

`kb-doctor` reports what is actually present and prints the command that adds
the rest:

```bash
kb-doctor                        # what is installed
kb-doctor --require kb-video     # exit non-zero if kb-video would fail
```

Adding an extra later means reinstalling, and `uv tool install --force`
*replaces* the environment — so the command has to name every extra you want to
keep, not just the new one. `kb-doctor`, and the errors the tools raise, always
compose it that way. Paste what they give you rather than writing your own.

## Plugins

| Plugin | Skills | Needs |
|---|---|---|
| `kb` | `init`, `adopt`, `compile`, `health`, `verify`, `wiki-search` | core install |
| `kb-ingest` | `ingest`, `transcribe` | `[ingest]` extra |
| `kb-video` | `video` | `[video]` extra + `ffmpeg` |
| `kb-capture` | `capture`, `meeting`, `update-brief` | core install + calendar/mail connectors; ships the Granola MCP |

`kb` is the only one you need. The rest are separate because their extras are
heavy — `[video]` pulls torch — and because not every knowledge base wants a
daily brief wired to a calendar.

`kb-capture` bundles the [Granola](https://granola.ai) MCP server in its own
`.mcp.json`, so enabling the plugin is all it takes to make
`/kb-capture:capture meeting granola` available — run `/mcp`, pick `granola`,
and authenticate once. Everything else in the plugin works without it, and a
Granola account that is not connected is reported as a skip rather than an
error. Transcript access is a paid Granola tier; on the free tier the import
falls back to the meeting summary.

Skills are addressed by the plugin that ships them: `/kb:compile`,
`/kb-video:video`, `/kb-capture:capture`.

## Commands

The skills drive these; you can also run them directly.

| Command | Purpose |
|---|---|
| `kb-index` | Regenerate every `INDEX.md` from article frontmatter |
| `kb-health` | Automated health checks; timestamped report to `output/` |
| `kb-search` | BM25 full-text search with tag and type filters |
| `kb-stats` | Article counts, word counts, link density, orphans |
| `kb-provenance` | Map, retract, classify and migrate source provenance |
| `kb-ingest` | Fetch arXiv papers, extract PDFs, convert HTML, localise images |
| `kb-export` | Marp slide decks, or the whole wiki flattened to one file |
| `kb-video` | Stage a YouTube video's captions, audio and frames |
| `kb-doctor` | Report which extras are installed, and what to run to add the rest |

Every command finds its bundle by walking up from the working directory looking
for `okf.toml`, the way `git` finds `.git`. They run from anywhere inside a
knowledge base, not only from its root.

## okf.toml

One file at the bundle root marks a directory as a knowledge base and describes
it: the title, the spec versions, the directory names, and the section taxonomy
the generated indexes use. Every key has a default matching the canonical
layout, so a conventional bundle needs almost nothing in it — but a folder that
calls its zones `notes/` and `articles/` keeps calling them that.

Adding a wiki section is an edit to this file, not a code change. See
[`okf.toml.example`](okf.toml.example), which documents every key.

## What's in this repo

Two halves of one product, versioned and released together:

- **`src/okf_kb/`** — the Python package behind the `kb-*` commands.
- **`plugins/`** — a Claude Code marketplace of four plugins, whose skills
  drive those commands.

This repo is *not itself* a knowledge base — there is no `wiki/` or `raw/`
here, only the tooling that creates them.

## Development

```bash
uv sync                  # core + [ingest] + dev
uv run tests
uvx ruff check . --fix && uvx ruff format .
uvx ty check
pre-commit run --all-files
```

`uv.lock` is not committed: both install paths resolve fresh, so a committed
lock would only ever describe one machine.

[`CLAUDE.md`](CLAUDE.md) documents the conventions that are not visible from
the code — how optional dependencies must be imported and reported, why
`config.py` and `frontmatter.py` are the only places that touch paths and
frontmatter, and which of the two files named `CLAUDE.md` you are editing.

## Licence

MIT, as declared by each plugin manifest.
