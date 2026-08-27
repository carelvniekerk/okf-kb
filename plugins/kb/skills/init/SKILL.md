---
name: init
description: >
  Scaffold a new Open Knowledge Format knowledge base in the current directory.
  Checks the kb-* tooling is installed, interviews the user about what this bundle
  is for, then writes okf.toml, CLAUDE.md, .claude/settings.json, the directory
  skeleton, .gitignore and the pre-commit hooks, and generates the first indexes.
  Use when the user says "set up a knowledge base", "init a KB", "start a new
  notebook", "/kb:init", or points at an empty directory and asks for a wiki.
  For a directory that already holds markdown worth keeping, use /kb:adopt instead.
allowed-tools: Read Write Edit Bash(kb-*) Bash(git *) Bash(uv tool *) Bash(mkdir *) Bash(ls *) Bash(test *) Bash(command *) Bash(date *)
---

# Initialise a knowledge base

Scaffold a new OKF v0.2 bundle in the current directory.

The goal is a working knowledge base in one pass: tooling verified, structure on
disk, and `kb-health` green. Interview only where the answer genuinely changes
what you write — every key in `okf.toml` has a default, so a conventional bundle
needs almost nothing from the user.

## 0. Refuse to overwrite

Check for `okf.toml` in the current directory.
If it exists, this is already a bundle: stop, say so, and offer `/kb:health`
instead. Never overwrite an existing `okf.toml`.

Then look at what is here. If the directory already contains markdown the user
would not want ignored — notes, papers, an existing wiki — stop and recommend
`/kb:adopt`, which is built to take those over. `init` is for a blank start.

## 1. Check the tooling

The skills are useless without the package, and each optional plugin is useless
without its extra. Both are settled here, before anything is scaffolded.

**First, list which of the four plugins are enabled in this session** —
`kb`, `kb-ingest`, `kb-video`, `kb-capture`. This drives the install, so
establish it before running anything. Each maps to an extra:

| Plugin enabled | Extra it needs |
|---|---|
| `kb` | none — core |
| `kb-capture` | none — core |
| `kb-ingest` | `ingest` |
| `kb-video` | `video`, plus `ffmpeg` on the system |

Then check what is installed:

```bash
kb-doctor
```

`kb-doctor` reports the core commands and every extra, and prints the exact
install command for whatever is missing. It exits non-zero only on a broken
core install, so pass `--require` for each optional plugin that is enabled to
make its extra count too:

```bash
kb-doctor --require kb-ingest --require kb-video
```

**If `kb-doctor` is not on the PATH at all**, nothing is installed. Give the
user the command matching the plugins they have enabled — never a fixed one:

| Plugins enabled | Install |
|---|---|
| `kb` and/or `kb-capture` only | `uv tool install "okf-kb @ git+ssh://git@github.com/carelvniekerk/okf-kb"` |
| …plus `kb-ingest` | `uv tool install "okf-kb[ingest] @ git+ssh://git@github.com/carelvniekerk/okf-kb"` |
| …plus `kb-video` | `uv tool install "okf-kb[video] @ git+ssh://git@github.com/carelvniekerk/okf-kb"` |
| …both | `uv tool install "okf-kb[all] @ git+ssh://git@github.com/carelvniekerk/okf-kb"` |

Installing a *narrower* set than the enabled plugins need is the failure this
step exists to prevent: the missing extra does not surface at install time, it
surfaces weeks later when the user first runs `/kb-video:video`.

**If the core is missing, stop** — do not scaffold a bundle whose tools cannot
run. A missing *extra* is a warning, not a blocker: scaffold anyway, and say
which skills stay broken until it is added. Take the fix straight from
`kb-doctor`'s output rather than composing one; it already accounts for how the
package was installed and for the extras the user has, which a reinstall with
`--force` would otherwise remove.

`kb-video` also needs `ffmpeg`, which no extra can install — `kb-doctor` lists
it separately with `brew install ffmpeg`.

## 2. Interview

Ask only what you cannot infer. Keep it to one round of questions.

**Always ask:**

1. **What is this knowledge base for?** One sentence. It becomes the bundle
   title and shapes the starting taxonomy.
2. **What id should identify you** in provenance and sign-offs? The OKF actor
   convention (§7) wants a short stable handle — `human:carel`, not a display
   name. Offer the git user name lowercased as a default:
   `git config user.name`.

**Ask only if the answer is not obvious:**

3. **Directory names.** Default to `wiki/`, `raw/`, `output/`. Only ask if the
   user has signalled they want something else — this is the main reason
   `[paths]` exists, but almost nobody needs it.
4. **Starting sections.** Propose three to six from their answer to (1) and let
   them correct it. Do not march through a taxonomy design session; sections are
   cheap to add later, and an unclaimed directory still renders under
   "📁 Unfiled" rather than vanishing.

**If the `kb-capture` plugin is enabled**, also ask whether they want the daily
brief wired to their calendars and mail. If yes, collect one entry per calendar
(label, `google` or `microsoft`, and the calendar id for Google) and per mailbox
(label, `gmail` or `outlook`). If they would rather do it later, leave the
`[capture]` block commented — the skill degrades to input-only and says so once.

The calendars serve double duty: `/kb-capture:capture meeting granola` matches a
Granola transcript against the same entries to recover the invitee list and
start time. Say so when asking, so the answer is not weighed against the brief
alone. Do **not** ask for a Granola folder id here — `[capture.granola]` is
optional, it needs an id only `list_meeting_folders` can supply, and an omitted
table just means every accessible meeting is in scope.

Never invent a calendar id, an email address, or an employer. If the user does
not supply one, leave it out.

## 3. Write the scaffold

Templates live beside this skill in `templates/`. Copy each into place and
substitute the placeholders:

| Placeholder | Filled with |
|---|---|
| `{{TITLE}}` | The bundle title from question (1) |
| `{{DESCRIPTION}}` | One line on what this bundle covers, also from question (1). It is rendered under the root index badges, so write it to be read on its own. |
| `{{SLUG}}` | The directory name, for the layout diagram |
| `{{HUMAN_ID}}` | The actor id from question (2) |
| `{{INGEST_SKILLS}}` / `{{INGEST_TOOLS}}` | Rows for `/kb-ingest:ingest`, `/kb-ingest:transcribe` and `kb-ingest` — only if the `kb-ingest` plugin is enabled |
| `{{VIDEO_SKILLS}}` / `{{VIDEO_TOOLS}}` | Rows for `/kb-video:video` and `kb-video` — only if `kb-video` is enabled |
| `{{CAPTURE_SKILLS}}` | Rows for `/kb-capture:capture`, `/kb-capture:meeting`, `/kb-capture:update-brief` — only if `kb-capture` is enabled |
| `{{CAPTURE_TASKS}}` | The Capture and Meeting VS Code tasks — only if `kb-capture` is enabled |
| `{{FOAM_TASK}}` | The graph-view task — only if the user uses the Foam extension |
| `{{EXTRA_PLUGINS}}` | One `"<plugin>@okf-kb": true` entry per enabled optional plugin |
| `{{INSTALL_COMMAND}}` | The install command whose extras match those plugins, from step 1 |

A block for a plugin that is not enabled is replaced with nothing, not left as a
placeholder and not left as a row pointing at a skill the user does not have.

`{{CAPTURE_TASKS}}`, `{{FOAM_TASK}}` and `{{EXTRA_PLUGINS}}` sit *inside* JSON
structures, so each expands to a **leading comma then the entries**, and to the
empty string when unused. Getting that wrong yields a trailing comma and a file
VS Code or Claude Code refuses to load — check the result parses before moving
on.

`{{EXTRA_PLUGINS}}`, for a user with `kb-ingest` and `kb-video` enabled:

```json
,
        "kb-ingest@okf-kb": true,
        "kb-video@okf-kb": true
```

Write an entry for every optional plugin enabled in this session, and nothing
for the ones that are not. The scaffolded `settings.json` is what turns those
plugins on for anyone who clones the bundle, so a plugin left out here is a
skill that silently does not exist for them — and one put in without its extra
installed is a skill that fails the first time they reach for it. Keep this
list and the install command from step 1 describing the same set.

`{{CAPTURE_TASKS}}`:

```json
,
        {
            "label": "🎙️ Capture",
            "type": "shell",
            "command": "claude-private /kb-capture:capture",
            "group": { "kind": "build", "isDefault": false },
            "presentation": { "reveal": "always", "focus": false, "panel": "shared" }
        },
        {
            "label": "👥 Meeting",
            "type": "shell",
            "command": "claude-private /kb-capture:meeting",
            "group": { "kind": "build", "isDefault": false },
            "presentation": { "reveal": "always", "focus": false, "panel": "shared" }
        }
```

`{{FOAM_TASK}}`:

```json
,
        {
            "label": "🕸️ Graph",
            "type": "vscode-command",
            "command": "foam-vscode.show-graph",
            "presentation": { "reveal": "never", "focus": false, "panel": "shared" }
        }
```

| Template | Destination | Notes |
|---|---|---|
| `templates/okf.toml` | `./okf.toml` | Title, versions, `[directories]`, `[[groups]]`, optional `[capture]` |
| `templates/CLAUDE.md` | `./CLAUDE.md` | The bundle's agent instructions |
| `templates/settings.json` | `./.claude/settings.json` | Plugin + marketplace + tool permissions |
| `templates/gitignore` | `./.gitignore` | Note the missing dot on the source name |
| `templates/pre-commit-config.yaml` | `./.pre-commit-config.yaml` | Only if the user wants hooks |
| `templates/vscode-settings.json` | `./.vscode/settings.json` | Folder icons, excludes, markdown/spell settings |
| `templates/vscode-tasks.json` | `./.vscode/tasks.json` | Health, Compile, Reindex, Stats, plus conditional tasks |

The two `.vscode/` files are editor conveniences, not part of the bundle. Ask
once whether the user wants them and skip both if not — do not write editor
config for someone who did not ask for it. If they use VS Code, they are worth
having: the tasks put Health and Compile on ⇧⌘B, and the folder-icon
associations make `raw/` and `wiki/` visually distinct in the tree.

The icon associations name folders a bundle may not have (`handwritten/`,
`daily-briefs/`, `video_scratch/`). That is deliberate and harmless — an
association for a folder that does not exist simply never matches — so the file
needs no per-plugin conditioning. Only the *tasks* do, since a task invoking a
skill the user does not have would fail when run.

If the user does not use the Foam extension, drop `{{FOAM_TASK}}`; its
`foam.files.exclude` setting is inert without the extension and can stay.

Copy both files as **text**, and keep every emoji literal. A JSON serialiser
that escapes non-ASCII rewrites `"🩺 Health"` as `"\ud83e\ude7a Health"` — VS
Code still renders the icon, but the file becomes unreadable and nobody editing
it later can tell one task from another. In a tasks file the emoji *is* the
interface, so never round-trip these through a JSON dump.

Then create the directory skeleton:

```bash
mkdir -p raw/notes raw/papers raw/images output wiki
```

Add a wiki subdirectory per section agreed in the interview, and record each in
`okf.toml` under `[directories]` and `[[groups]]`. **A section that exists on
disk but is missing from `okf.toml` renders as unfiled** — writing both is the
whole point of doing it here rather than later.

Seed `wiki/log.md` with the init entry:

```markdown
# Operations Log

## [YYYY-MM-DD] 🏗️ init | Knowledge base initialised

Scaffolded by `/kb:init`. <N> sections: <list>. Tooling: okf-kb <version>, extras <…>.
```

Get the date with `date +%Y-%m-%d`.

Do **not** hand-write `wiki/INDEX.md`. It is generated in the next step.

## 4. Generate and verify

```bash
kb-index
kb-health
```

`kb-index` writes the root index and one per article-bearing directory. An empty
wiki generates just the root — that is correct, not a failure.

If `kb-health` exits 0, re-run `kb-index --health-passing` so the badge reflects
a real check. **Never pass `--health-passing` without an exit-0 run in this
session.** Do not pass `--stamp-compiled`; nothing has been compiled yet, and
that flag belongs to `/kb:compile` alone.

Fix anything `kb-health` reports before handing over. A bundle that is born
failing its own health check teaches the user to ignore it.

## 5. Git

If the directory is not a git repo, offer `git init`. Do not initialise one
without asking — the user may be adding this inside an existing repo.

If they accept and asked for hooks, install them:

```bash
pre-commit install --install-hooks
```

Commit the scaffold as `init: scaffold the knowledge base`.

## 6. Hand over

Tell the user, briefly:

- Where the bundle root is, and that every `kb-*` command now works from
  anywhere inside it.
- Which plugins are active and which extras are missing, if any.
- That `raw/` is theirs and `wiki/` is yours.
- The next step: drop a source into `raw/` and run `/kb:compile`.

Keep it to a few lines. They asked for a knowledge base, not a tour.
