# CLAUDE.md — okf-kb

Instructions for working **on** okf-kb.

> **This repo is not a knowledge base.** It is the tooling that builds and
> maintains them. There is no `wiki/`, no `raw/`, and no `okf.toml` here — only
> `okf.toml.example`. If you are looking for a bundle to compile, you are in
> the wrong directory.

## What this is

Two halves of one product, shipped from one repo:

| Half | Lives in | Installed by |
|---|---|---|
| The `kb-*` commands | `src/okf_kb/` | `uv tool install "okf-kb[…] @ git+…"` |
| The skills that drive them | `plugins/` | `claude plugin install kb@okf-kb` |

They are versioned together and released together because they are a matched
pair: a skill that calls a flag the package does not have is broken, and so is
a package whose new subcommand no skill ever invokes. **A change to one is
usually a change to both** — when you add a command or a flag, find the skill
that should use it before calling the work done.

The domain is the [Open Knowledge Format][okf] v0.2. A knowledge base is two
zones: `raw/`, human-curated source material whose bodies are never rewritten,
and `wiki/`, an OKF bundle the agent owns entirely. Compilation integrates the
first into the second with provenance tracked per source.

[okf]: https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf

## Layout

```
src/okf_kb/            # the Python package — one module per kb-* command
├── config.py          # bundle discovery + okf.toml. Everything goes through here
├── frontmatter.py     # the ONLY place YAML frontmatter is read or written
├── okf.py             # OKF v0.2 schema construction
├── links.py           # the ONLY markdown link scanner
├── graph.py           # kb-graph: the link graph, backlinks, traversal
├── read.py            # kb-read: print one article from any bundle in scope
├── mcp_server.py      # kb-mcp: search, graph and read as MCP tools
├── gitmeta.py         # git archaeology, for provenance backfill
├── extras.py          # optional-dependency handling. See "Extras" below
├── doctor.py          # kb-doctor, and kb-doctor bundles
├── index_gen.py       # kb-index
├── health.py          # kb-health
├── search.py          # kb-search
├── stats.py           # kb-stats
├── provenance.py      # kb-provenance
├── export.py          # kb-export
├── ingest.py          # kb-ingest        [ingest] extra
└── video/             # kb-video         [video] extra
    ├── cli.py         #   argparse entry point
    ├── pipeline.py    #   per-command handlers
    ├── youtube.py     #   yt-dlp wrappers
    └── transcribe.py  #   captions, and MLX Whisper fallback

plugins/               # the Claude Code marketplace — one directory per plugin
├── kb/                # init, adopt, compile, health, verify
│   └── skills/init/templates/   # what /kb:init scaffolds INTO a bundle
├── kb-query/          # wiki (read-only), via the kb-mcp server in .mcp.json
├── kb-ingest/         # ingest, transcribe            needs [ingest]
├── kb-video/          # video                         needs [video] + ffmpeg
└── kb-capture/        # capture, meeting, update-brief

.claude-plugin/marketplace.json   # lists the five plugins
okf.toml.example                  # every key, documented, with its default
tests/                            # pytest, one file per module
```

### Two files named CLAUDE.md

`plugins/kb/skills/init/templates/CLAUDE.md` is **not** this file. It is a
template with `{{PLACEHOLDER}}` slots that `/kb:init` copies into a *user's*
knowledge base to tell an agent how to work in **that** bundle. This file
governs work on the tooling.

Editing the wrong one is the easiest mistake to make in this repo. Check which
path you are in before you write.

## Commands

```bash
uv sync                      # core + dev, which carries [ingest] and [video]
uv run tests                 # pytest, via the `tests` script in pyproject
uvx ruff check . --fix
uvx ruff format .
uvx ty check
pre-commit run --all-files
```

`uv.lock` is gitignored on purpose. Both install paths — `uv tool install` from
git, and a consumer's `uv sync` — resolve fresh, so a committed lock would only
ever describe one machine. The `uv-lock` pre-commit hook still runs; it fails
the commit when `pyproject.toml` stops resolving, which for a package other
repos install from git is the failure worth catching early.

## Extras

Heavy, platform-sensitive dependencies are opt-in:

| Extra | Brings | Needed by |
|---|---|---|
| — | core only | `kb`, `kb-capture` |
| `[ingest]` | `pymupdf`, `requests`, `beautifulsoup4`, `markdownify` | `kb-ingest` |
| `[video]` | `yt-dlp`, `mlx-whisper`, `python-slugify` — **and `ffmpeg`** | `kb-video` |
| `[all]` | both | |

The `dev` group pulls both, so a source checkout runs every `kb-*` command
without a second install step. `[ingest]` has to be there because its tests do
real fetching and rewriting and would silently skip otherwise; `[video]` is
there despite the torch download, because the alternative is `kb-video` failing
the first time a contributor reaches for it. Note that `[video]` still needs
`ffmpeg` from Homebrew, which no `uv sync` will install for you.

### The rules

**1. Import optional dependencies lazily, inside the function that uses them,
wrapped in the guard.** Never at module scope — a core-only install must import
and run every module, and fail only at the subcommand whose extra is missing.

```python
def extract_pdf(...) -> None:
    with extras.required("ingest"):
        import fitz  # noqa: PLC0415
```

The guard turns `ModuleNotFoundError: No module named 'fitz'` — which names
neither the extra nor the environment it is missing from — into a message
naming both, plus the command that fixes it. A bare lazy import is a bug even
though it "works".

**2. Never hand-write an install command.** Always route through
`extras.install_command()`, or relay what an error already printed.

Two things make a hand-written command wrong. First, `uv tool install --force`
**replaces** the tool environment, so telling someone with `[ingest]` to
reinstall with `[video]` silently uninstalls their PDF tooling —
`install_command()` unions the request with `extras.installed_extras()` so the
fix is always additive. Second, the right command depends on how the package
was installed: a uv tool, a source checkout (`uv sync --group all`), or a plain
venv. `install_command()` detects which.

The same rule binds the skills: **relay the error's command verbatim, never
compose one.** Never suggest `uv add mlx-whisper` or `pip install yt-dlp` —
those install into the current project, not into the environment `kb-video`
runs from.

**3. `--help` is not a probe.** Because the imports are lazy,
`kb-ingest extract-pdf --help` succeeds whether or not `[ingest]` exists. Use
`kb-doctor`, which probes for real:

```bash
kb-doctor                                    # what is installed
kb-doctor --require kb-video                 # exit non-zero if kb-video would fail
kb-doctor --json-output                      # machine-readable
```

`--require` accepts plugin names as well as extra names, because skills know
plugin names.

**4. Adding an extra means touching four places**: `pyproject.toml`,
`extras.EXTRA_MODULES` (import names, not distribution names — an import error
reports the former), `extras.EXTRA_BINARIES` if it needs one, and
`doctor.PLUGIN_EXTRAS` if a plugin depends on it. A test asserts the first two
agree; nothing enforces the rest.

## Package conventions

**`config.py` owns every path.** Tools find their bundle by walking up from the
working directory for `okf.toml`, the way `git` finds `.git` — that is what
lets a command run from anywhere inside a bundle rather than only from its
root. Paths from `config.load()` are absolute. **Never do relative-path
arithmetic downstream, and never hardcode `wiki/` or `raw/`**: a bundle that
calls its zones `notes/` and `articles/` keeps calling them that.

**`frontmatter.py` owns every read and write of YAML frontmatter.** Do not
hand-roll a regex. The regex parsers it replaced could not represent nested
structures, which OKF v0.2 requires.

**Only read-only commands accept `--kb`.** `kb-search`, `kb-graph`, `kb-read`
and `kb-doctor bundles` resolve their scope through `config.resolve_roots`,
which can reach a bundle the user is not standing in. Every command that writes
(`kb-index`, `kb-health`, `kb-provenance`, `kb-ingest`, `kb-video`,
`kb-export`) keeps walk-up discovery through `config.load()`, so nothing can
compile, reindex or report into a bundle from outside it. Do not add `--kb` to
a writing command, and do not add a writing tool to `mcp_server.py`, which
takes `kb` on every tool.

**`kb-mcp` wraps the CLI's functions, never its processes.** Each tool calls
the payload function its command calls (`graph.neighbours_payload`,
`read.read_article`, `doctor.scope_report`), so the JSON an agent gets is the
same on both paths. A new read-only command that the `wiki` skill should use
needs a tool here, a line in the skill's `allowed-tools` under the
`mcp__plugin_kb-query_okf-kb__` prefix Claude Code derives, and a mention in
the skill body; `tests/test_mcp_server.py` fails until all three agree.

**Only `config.resolve_roots` reads the pointer files.** The user config
(`$XDG_CONFIG_HOME/okf-kb/config.toml`) and a project's `.okf-kb.toml` are read
there, through the helpers it calls, and nowhere else. `load()` and
`find_root()` must never consult them. The
project file is not called `okf.toml` for the same reason: that name marks a
directory as a knowledge base to every writing tool.

**`links.py` owns every markdown link parse.** `targets()` keeps any internal
target, which the broken-link check needs; `internal_targets()` keeps only
`.md` targets, which link counts and the graph need. The image and
`## Sources` checks in `health.py` keep their own narrower patterns; anything
new that follows links between articles goes through `links.py`.

**Configuration is a config change, not a code change.** Adding a wiki section
is an edit to `okf.toml`. If you find yourself adding a section name to a
Python file, you are solving it in the wrong layer.

**CLI style:** typer for everything except `kb-video`, which predates the rest
and uses argparse. Boolean flags carry `# noqa: FBT002` — see `search.py`. A
typer app that can raise `MissingExtraError` needs a `main()` wrapper that
catches it, or typer prints a traceback over the useful message; that is why
`kb-ingest`'s entry point is `okf_kb.ingest:main`, not `:app`.

## Skill conventions

**Address every skill by the plugin that ships it** — `/kb-capture:capture`,
not `/kb:capture`; `/kb-video:video`, not `/video`. This applies in skill
bodies, in the scaffolded templates, and in Python docstrings and help text.

**A skill must degrade, not crash, when an optional plugin is absent.** The
`init` templates use `{{PLACEHOLDER}}` blocks that expand to *nothing* for a
plugin the user does not have — never to a row pointing at a skill they cannot
run. Placeholders inside a JSON array or object (`{{CAPTURE_TASKS}}`,
`{{FOAM_TASK}}`, `{{EXTRA_PLUGINS}}`) expand to a **leading comma then the
entries**, so the empty case leaves valid JSON. Check the result parses.

**Keep the enabled plugins and the installed extras describing one set.**
`/kb:init` picks its install command from which plugins are enabled, and writes
those same plugins into the bundle's `.claude/settings.json`. A plugin enabled
without its extra is a skill that fails the first time it is reached for; an
extra installed for a plugin nobody enabled is dead weight.

**Never claim a health check that did not run.** `kb-index` emits an `unknown`
badge by default and only writes `✓ passing` when passed `--health-passing`,
which requires an actual exit-0 `kb-health` run in the same session.
`--stamp-compiled` belongs to `/kb:compile` alone.

## Testing

`tests/` holds one file per module. Tests carry a module docstring saying what
the file is really pinning down, and a `# ruff: noqa:` line for the test-only
rules — copy the header from `tests/test_config.py`.

Test the contract, not the implementation. `test_extras.py` asserts on message
*content* because the message is the feature: the sharpest test in the file is
that a fix suggested to a user who has `[ingest]` still contains `[ingest]`.

## Conventions inherited from the global config

Google-style docstrings with `Args`/`Returns`/`Raises`, double quotes, `|`
unions, `TypeAlias` for aliases, specific exceptions. Commit messages are
`<type>: <description>`. Ruff runs `select = ["ALL"]` from
`~/.config/ruff/ruff.toml`, so expect to justify a `noqa` rather than sprinkle
them.

## Manual testing

`scratch/` is gitignored for exactly this: scaffold a throwaway bundle there
and run the skills against it end to end. Several real bugs in `/kb:adopt`
(commit `fa775c6`) were only found that way — the skills are prose, so nothing
type-checks them, and reading one is not the same as running it.
