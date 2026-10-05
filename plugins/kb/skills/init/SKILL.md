---
name: init
description: >
  Scaffold a new Open Knowledge Format knowledge base in an empty directory.
  Checks the kb-* tooling against the enabled plugins, asks what the bundle is for,
  writes okf.toml, CLAUDE.md, .claude/settings.json, the directory skeleton,
  .gitignore and optional pre-commit and VS Code files, then generates the first
  indexes and gets kb-health green. Use for "set up a knowledge base", "init a KB"
  or "start a new notebook" in an empty directory. A directory that already holds
  markdown worth keeping belongs to /kb:adopt.
disable-model-invocation: true
allowed-tools: Read Write Edit Bash(kb-*) Bash(claude plugin list *) Bash(git init) Bash(git config *) Bash(git status *) Bash(git add *) Bash(git commit *) Bash(pre-commit install *) Bash(mkdir *) Bash(ls *) Bash(date *)
---

# Initialise a knowledge base

Scaffold a new OKF v0.2 bundle in the current directory, in one pass: tooling verified, structure on disk and `kb-health` green.
Every key in `okf.toml` has a default, so interview only where the answer changes what you write.

## Contents

- 0. Refuse to overwrite
- 1. Check the tooling
- 2. Interview
- 3. Write the scaffold
- 4. Generate and verify
- 5. Git
- 6. Hand over
- Gotchas

## 0. Refuse to overwrite

If `okf.toml` exists in the current directory, this is already a bundle.
Stop, say so and offer `/kb:health`, because overwriting `okf.toml` loses the bundle's taxonomy.

If the directory already holds markdown the user would want kept (notes, papers, an existing wiki), stop and recommend `/kb:adopt`, which takes those over without imposing a layout.

## 1. Check the tooling

Follow `${CLAUDE_PLUGIN_ROOT}/references/tooling.md` exactly.
It establishes which okf-kb plugins are enabled, which extras they need and what to tell the user when something is missing.
Keep the list of enabled optional plugins: steps 3 and 6 use it.

## 2. Interview

Ask in one round, and only what you cannot infer.

Always ask:

1. What is this knowledge base for?
   One sentence. It becomes the bundle title and shapes the starting sections.
2. Which id should identify the user in provenance and sign-offs?
   The OKF actor convention (§7) wants a short stable handle such as `human:carel`, not a display name.
   Offer the lowercased output of `git config user.name` as the default.

Ask only when the answer is not obvious:

3. Directory names.
   Default to `wiki`, `raw` and `output`, and ask only if the user has signalled they want others.
   The rest of this skill calls the chosen names `<wiki>`, `<raw>` and `<output>`.
4. Starting sections.
   Propose three to six from the answer to (1) and let the user correct them.
   Sections are cheap to add later, and a directory no group claims still renders under "📁 Unfiled".
5. Editor files.
   Ask once whether they want the VS Code settings and tasks, and whether they use the Foam extension.

If `kb-capture` is enabled, also ask whether to wire the daily brief to their calendars and mail.
For a yes, collect one entry per calendar (label, `google` or `microsoft`, and the calendar id for Google) and one per mailbox (label, `gmail` or `outlook`).
Say that the same calendars let `/kb-capture:capture meeting granola` recover a meeting's invitee list, so the answer is not weighed against the brief alone.
Do not ask for a Granola folder id: the table is optional and the id comes only from Granola's `list_meeting_folders`.
If they would rather wait, leave the `[capture]` block commented out.

Never invent a calendar id, an email address or an employer.
Leave out anything the user did not supply.

## 3. Write the scaffold

Templates live in `${CLAUDE_SKILL_DIR}/templates/`.
Copy each into place as text and fill its placeholders.

| Template | Destination | When |
| --- | --- | --- |
| `okf.toml` | `./okf.toml` | Always |
| `CLAUDE.md` | `./CLAUDE.md` | Always |
| `settings.json` | `./.claude/settings.json` | Always |
| `gitignore` | `./.gitignore` | Always (the source name has no dot) |
| `pre-commit-config.yaml` | `./.pre-commit-config.yaml` | If the user wants hooks |
| `vscode-settings.json` | `./.vscode/settings.json` | If the user wants editor files |
| `vscode-tasks.json` | `./.vscode/tasks.json` | If the user wants editor files |

| Placeholder | Filled with |
| --- | --- |
| `{{TITLE}}` | The bundle title, from question 1 |
| `{{DESCRIPTION}}` | One line on what the bundle covers. It renders under the root index badges, so it must read on its own |
| `{{SLUG}}` | The directory name, for the layout diagram |
| `{{HUMAN_ID}}` | The actor id from question 2 |
| `{{INGEST_SKILLS}}`, `{{INGEST_TOOLS}}` | `fragments/ingest-skills.md` and `fragments/ingest-tools.md`, if `kb-ingest` is enabled |
| `{{VIDEO_SKILLS}}`, `{{VIDEO_TOOLS}}` | `fragments/video-skills.md` and `fragments/video-tools.md`, if `kb-video` is enabled |
| `{{CAPTURE_SKILLS}}` | `fragments/capture-skills.md`, if `kb-capture` is enabled |
| `{{CAPTURE_TASKS}}` | `fragments/capture-tasks.json`, if `kb-capture` is enabled |
| `{{FOAM_TASK}}` | `fragments/foam-task.json`, if the user uses Foam |
| `{{EXTRA_PLUGINS}}` | One `"<plugin>@okf-kb": true` entry per enabled optional plugin, as below |
| `{{INSTALL_COMMAND}}` | The install command whose extras match the enabled plugins, from step 1 |

A placeholder for a plugin that is not enabled becomes the empty string.
It never stays as a placeholder, and never becomes a row pointing at a skill the user does not have.

`{{CAPTURE_TASKS}}`, `{{FOAM_TASK}}` and `{{EXTRA_PLUGINS}}` sit inside JSON, so each expands to a leading comma and then its entries.
The fragments already start with that comma.
For a user with `kb-ingest` and `kb-video` enabled, `{{EXTRA_PLUGINS}}` is:

```json
,
        "kb-ingest@okf-kb": true,
        "kb-video@okf-kb": true
```

Never list `kb` or `kb-query` there, because the template enables both and a second entry is a duplicate key.
The scaffolded `settings.json` is what enables these plugins for anyone who clones the bundle, so it must describe the same set as the install command.
After writing each JSON file, parse it (for example with `python3 -m json.tool`) before moving on, because VS Code and Claude Code refuse a file with a trailing comma.

Copy the emoji in the VS Code files literally.
A JSON serialiser rewrites `"🩺 Health"` as `"🩺 Health"`, which still renders but leaves a file nobody can maintain.

Create the skeleton with the names agreed in step 2:

```bash
mkdir -p <raw>/notes <raw>/papers <raw>/images <output> <wiki>
```

Add one `<wiki>` subdirectory per agreed section, and record each in `okf.toml` under `[directories]` and `[[groups]]`.
Set `[paths]` only for a name that differs from the default.
A section on disk but missing from `okf.toml` renders as unfiled.

Seed `<wiki>/log.md`, taking the date from `date +%Y-%m-%d`:

```markdown
# Operations Log

## [YYYY-MM-DD] 🏗️ init | Knowledge base initialised

Scaffolded by `/kb:init`. <N> sections: <list>. Tooling: okf-kb, extras <list or none>.
```

Do not write any `INDEX.md` by hand, because step 4 generates them.

## 4. Generate and verify

```bash
kb-index
kb-health
```

An empty wiki generates only the root index, which is correct.
Fix anything `kb-health` reports before handing over, because a bundle born failing its own check teaches the user to ignore it.
Once `kb-health` exits 0, run `kb-index --health-passing`.
Never pass `--health-passing` without that exit-0 run in this session, and never pass `--stamp-compiled`, which belongs to `/kb:compile`.

## 5. Git

If the directory is not a git repository, offer `git init`, and wait for the answer, because the user may be adding the bundle inside an existing repository.
If they asked for hooks, run `pre-commit install --install-hooks`.
Then stage the files this skill wrote, by name, and commit them as `init: scaffold the knowledge base`.

## 6. Hand over

In a few lines, tell the user:

- where the bundle root is, and that every `kb-*` command works from anywhere inside it;
- which plugins are active and which extras are missing;
- that `<raw>` is theirs and `<wiki>` belongs to the agent;
- the next step: put a source in `<raw>` and run `/kb:compile`.

## Gotchas

- The editor files name folders a bundle may not have (`handwritten/`, `daily-briefs/`, `video_scratch/`).
  That is harmless, since an association for a missing folder never matches, so only the tasks are conditional.
- `{{INSTALL_COMMAND}}` must come from `kb-doctor` or the table in the tooling reference, never from memory, because a narrower command run with `--force` removes extras the user has.
