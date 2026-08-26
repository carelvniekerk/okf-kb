# okf-kb

Tooling and skills for agent-maintained [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf) knowledge bases.

A knowledge base here is two zones: `raw/`, human-curated source material whose
bodies are never rewritten, and `wiki/`, an OKF v0.2 bundle the agent owns
entirely. Compilation integrates the first into the second with provenance
tracked per source, so any claim traces back to the file it came from.

This repo ships both halves: a Python package providing the `kb-*` commands, and
a Claude Code plugin marketplace providing the skills that drive them.

## Install

The tools:

```bash
uv tool install "okf-kb[ingest] @ git+ssh://git@github.com/carelvniekerk/okf-kb"
```

Extras are opt-in so a core install stays light. `[ingest]` adds PDF/HTML
fetching; `[video]` adds `yt-dlp` and `mlx-whisper`; `[all]` is both.

The skills:

```bash
claude plugin marketplace add carelvniekerk/okf-kb
claude plugin install kb@okf-kb
```

Then run `/kb:init` in an empty directory, or `/kb:adopt` in one that already
holds markdown.

## Plugins

| Plugin | Skills | Needs |
|---|---|---|
| `kb` | `init`, `adopt`, `compile`, `health`, `verify`, `wiki-search` | core install |
| `kb-ingest` | `ingest`, `transcribe` | `[ingest]` extra |
| `kb-video` | `video` | `[video]` extra + `ffmpeg` |
| `kb-capture` | `capture`, `meeting`, `update-brief` | core install + calendar/mail connectors |

`kb` is the only one you need. The rest are separate because their extras are
heavy — `[video]` pulls torch — and because not every knowledge base wants a
daily brief wired to a calendar.

## Commands

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

Every command finds its bundle by walking up from the working directory looking
for `okf.toml`, the way `git` finds `.git`. They run from anywhere inside a
knowledge base, not only from its root.

## okf.toml

One file at the bundle root marks it as a knowledge base and describes it:
the title, the spec versions, the directory names, and the section taxonomy the
generated indexes use. Every key has a default matching the canonical layout, so
a conventional bundle needs almost nothing in it — but a folder that calls its
zones `notes/` and `articles/` keeps calling them that.

Adding a wiki section is an edit to this file, not a code change.

## Development

```bash
uv sync          # core + [ingest] + dev
uv run tests
pre-commit run --all-files
```

`uv.lock` is not committed: both install paths resolve fresh, so a committed
lock would only ever describe one machine.
