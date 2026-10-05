# Tooling check

`/kb:init` and `/kb:adopt` run this check before they write anything.
The skills need the `okf-kb` package, and each optional plugin needs its extra.
Installing fewer extras than the enabled plugins need is the failure this check exists to prevent: it does not surface at install time, but weeks later, when the user first runs the skill whose extra is missing.

## 1. Find the enabled plugins

Run this from the directory being set up, so project-scoped settings count:

```bash
claude plugin list --json
```

Keep the entries whose `id` ends in `@okf-kb` and whose `enabled` is `true`.
Do not infer the set from the skills you can see: a skill with `disable-model-invocation: true` is not listed to you, and most of the optional plugins' skills are like that.
If the command fails, ask the user which of `kb-ingest`, `kb-video` and `kb-capture` they use.

| Plugin | Extra it needs |
| --- | --- |
| `kb`, `kb-query`, `kb-capture` | none, the core install |
| `kb-ingest` | `ingest` |
| `kb-video` | `video`, plus `ffmpeg` on the system |

## 2. Check what is installed

Pass one `--require` for each enabled plugin that needs an extra, and none for the others:

```bash
kb-doctor --require kb-ingest --require kb-video
```

`kb-doctor` exits non-zero when the core is broken or a required extra is missing, and prints the exact command that fixes it.
Relay that command verbatim.
It already accounts for how the package was installed and keeps the extras the user has, which a hand-written `uv tool install --force` would remove.

## 3. If `kb-doctor` is not on the PATH

Nothing is installed, so there is no tool to compute the command yet.
Give the user the one row matching their enabled plugins, and nothing broader, because `[video]` pulls in torch:

| Enabled optional plugins | Install |
| --- | --- |
| none | `uv tool install "okf-kb @ git+ssh://git@github.com/carelvniekerk/okf-kb"` |
| `kb-ingest` | `uv tool install "okf-kb[ingest] @ git+ssh://git@github.com/carelvniekerk/okf-kb"` |
| `kb-video` | `uv tool install "okf-kb[video] @ git+ssh://git@github.com/carelvniekerk/okf-kb"` |
| both | `uv tool install "okf-kb[all] @ git+ssh://git@github.com/carelvniekerk/okf-kb"` |

Then stop, and do not scaffold a bundle whose tools cannot run.

## 4. Decide

A missing core install blocks the skill.
A missing extra is a warning: carry on, and tell the user which skills stay broken until it is added.
`ffmpeg` comes from `brew install ffmpeg`, since no extra can install it, and `kb-doctor` lists it separately.
