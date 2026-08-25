# okf-kb — extraction plan

Extracting the tooling and skills that ran one personal knowledge base into an
installable package plus a Claude Code plugin, so the same machinery can init,
adopt and run any OKF bundle. The origin repo (`~/Knowledge Base`) ends up as
pure content: `raw/`, `wiki/`, `output/`, a handful of personal skills, and a
thin `CLAUDE.md`.

## Target shape

```
okf-kb/
├── src/okf_kb/                    # the package
│   ├── config.py                  # ✅ bundle discovery + okf.toml
│   ├── frontmatter.py health.py index_gen.py search.py stats.py
│   ├── ingest.py provenance.py export.py gitmeta.py okf.py video/
│   └── templates/                 # CLAUDE.md, okf.toml, .gitignore, hooks
├── .claude-plugin/marketplace.json
├── plugins/okf/skills/            # compile, ingest, health, verify,
│                                  #   wiki-search, video, transcribe,
│                                  #   init, adopt
├── .pre-commit-hooks.yaml         # hooks this package exports to bundles
└── tests/
```

Install is two lines: `uv tool install git+…/okf-kb` for the binaries, and
`claude plugin marketplace add carelvniekerk/okf-kb` for the skills. Package
and plugin share a repo so a skill referencing a new flag ships in the same
commit as the flag.

## Decisions

| Decision | Choice |
|---|---|
| CLI shape | keep the eight `kb-*` binaries — no `okf` supercommand |
| Skills | bundled plugin in this repo |
| `init` | a **skill** that interviews and checks, over a deterministic `kb-scaffold` helper |
| Distribution | GitHub only, `uv tool install`, matching ToolShed |
| Heavy deps | opt-in extras: `[ingest]`, `[video]` |
| `uv.lock` | gitignored — install paths resolve fresh |

## Phases

Each phase leaves both repos green. No big-bang cutover.

- **0 — scaffold** ✅ repo, pyproject, extras, gitignore, pre-commit
- **1 — extract** 🔄 `config.py` ✅ · move modules and tests onto it · export
  `.pre-commit-hooks.yaml` · origin repo consumes the package
- **2 — skills + spec** core skills into the plugin · split `CLAUDE.md` into
  portable spec vs repo-local facts · provenance stamping · `kb_format` 1.1
- **3 — init/adopt** the interview skill and `kb-scaffold` · adopt an existing
  folder using the migration machinery
- **4 — notebook** strip the origin repo to content

---

## Config integration checklist

`config.py` landed first, deliberately: everything else moves *onto* it. This
is what still has to be wired up, and it is the list to check against before
calling phase 1 or 3 done.

### Modules to convert (phase 1)

Each currently hardcodes a relative path, so it only works from the bundle
root. Replace the module constant with a `config.load()` default, keeping the
existing `--wiki-dir`-style flags as explicit overrides — the test suite passes
fixture directories that way and must keep working.

| Module | Hardcoded today |
|---|---|
| `health.py` | `RAW_DIR`, `WIKI_DIR`, `OUTPUT_DIR` |
| `index_gen.py` | `WIKI_DIR` |
| `provenance.py` | `WIKI_DIR` |
| `ingest.py` | `RAW_DIR` |
| `search.py` | `Path("wiki")` as a Typer default |
| `stats.py` | `Path("wiki")` as a Typer default |

Also in `index_gen.py`, and easy to miss because it is not a path: `ROOT_TITLE`,
`SECTION_TITLES` and `ROOT_GROUPS` hardcode *one* knowledge base's subject
taxonomy. Any other bundle gets every directory dumped into the "📁 Unfiled"
fallback. These move to `[bundle] title`, `[directories]` and `[[groups]]` —
`config.Config` already carries all three.

**Resolve the version duplication.** `okf_version` and `kb_format` are written
into `wiki/INDEX.md` frontmatter today, but `INDEX.md` is generated. `okf.toml`
becomes the source of truth and `index_gen` renders from config; otherwise the
two disagree the first time someone edits one.

### Skills to teach about `okf.toml`

- **`init`** — the interview's answers *are* the file. Ask for: bundle title,
  whether the directory names are conventional, the starting taxonomy
  (`[[groups]]` + `[directories]`), and which extras to install. Write
  `okf.toml`, then scaffold directories, `CLAUDE.md`, `.gitignore` and the
  pre-commit config around it. A bundle with a conventional layout needs almost
  nothing in the file — every key has a default — so the interview should
  offer "just use the defaults" as a first-class answer rather than marching
  through every key.
- **`adopt`** — detect the existing layout and write `okf.toml` describing what
  it *found*, including non-standard directory names. This is the main reason
  `[paths]` is configurable at all.
- **`compile`** — adding a new wiki section is now an `okf.toml` edit, not a
  Python edit. The skill must say so, or the taxonomy silently rots back into
  the fallback group.
- **`health`** — surface the "no okf.toml found" error as *the* signal that you
  are outside a bundle, rather than reporting an empty-looking wiki.
- **`wiki-search`, `ingest`, `video`, `verify`, `transcribe`** — no config
  knowledge needed, but their docs should drop any "run from the repo root"
  wording, since discovery makes that unnecessary.
- **`CLAUDE.md` template** — document `okf.toml` as the bundle's control file,
  and that generated indexes read their title and taxonomy from it.

### Known follow-ups

- `video/youtube.py` imports `yt_dlp` and `slugify` at module top level, unlike
  `ingest.py`, which lazy-imports throughout. Until that is fixed the `[video]`
  extra is not honoured — a core-only install crashes on import.
- Provenance stamping derives `skill: compile@<sha>` from the last commit
  touching `.claude/skills/<name>` *in the bundle's own repo*. Plugin-shipped
  skills have no such commit, so they need `compile@okf-<version>` instead.
  That is the `kb_format` 1.1 bump.
