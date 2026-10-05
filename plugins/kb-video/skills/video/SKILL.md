---
name: video
description: >
  Turn a YouTube video into a knowledge base source. Stages the video's metadata,
  captions, audio and frames, judges the transcript and falls back to MLX Whisper
  when the captions are poor, then writes a structured article to raw/videos/ with
  selected frames and keeps the verbatim transcript beside it. Does not commit,
  because /kb:compile integrates it. Use when the user gives a YouTube URL or says
  "ingest this video" or "transcribe this video".
disable-model-invocation: true
allowed-tools: Read Write Edit Bash(kb-video *) Bash(kb-doctor paths) Bash(mkdir *) Bash(mv video_scratch/*)
argument-hint: <youtube-url> [--force-whisper]
---

# Video

Turn a YouTube video into a source for the knowledge base.
`kb-video` only stages raw materials, and every editorial decision is yours.

The output is two files in `<raw>/videos/`: the article `<slug>-<id>.md`, and `<slug>-<id>.transcript.md`, the verbatim transcript.
The transcript is the record the article and every wiki claim built on it are checked against, so it is never deleted with the scratch directory.

## Contents

- 1. Fetch raw materials
- 2. Judge the transcript
- 3. Keep the transcript
- 4. Pick key frames
- 5. Write the article
- 6. Clean up and report
- Failure modes

## 1. Fetch raw materials

Run `kb-doctor paths` and take `<raw>` from its `raw` value.
Run every command in this skill from the bundle root it prints, because `kb-video` stages into `video_scratch/` under the working directory.
Note whether the user passed `--force-whisper`, then run:

```bash
kb-video fetch "<url>"
```

It stages `metadata.json`, `transcript.md` (captions, deduplicated, or a placeholder when none exist), `audio.wav` and a low-resolution `video.mp4` into `video_scratch/<id>/`, and prints `id:`, `slug:` and `scratch:` lines.
Record those three values, because every later step needs them.
Read `metadata.json` and `transcript.md`.

## 2. Judge the transcript

With `--force-whisper`, skip the judgement and run Whisper.
Otherwise read the whole transcript and reject the captions if any of these holds:

| Symptom | Why it matters |
| --- | --- |
| Words from the title or description are misspelt or replaced (*Pydantic* as *pi-dantic*) | Auto-captions mangle technical terms |
| Long stretches without punctuation | Auto-captions, which hide the argument's structure |
| Phrases repeated two or three times in adjacent paragraphs | A karaoke artefact the deduplication missed |
| The placeholder `_(no usable captions; ...)_` | No captions were available |
| The transcript is short for the video's duration | Captions covered only part of it |

When in doubt, run Whisper: it costs one to three minutes, and a bad transcript makes a useless article.
For a video over an hour, tell the user first that transcription may take ten minutes or more.

```bash
kb-video whisper <id>
```

This rewrites `video_scratch/<id>/transcript.md`.
Read it again, and note the `transcription_method` in its leading comment.

## 3. Keep the transcript

Move the final transcript into the raw zone:

```bash
mkdir -p <raw>/videos
mv video_scratch/<id>/transcript.md <raw>/videos/<slug>-<id>.transcript.md
```

Then add frontmatter at the top of the moved file, above its leading comment, and change nothing else in it:

```yaml
---
type: transcript
title: <video title> (transcript)
source_url: <full url>
transcription_method: youtube_captions | whisper:<model>
date_added: <today, YYYY-MM-DD>
compile: false
---
```

`compile: false` keeps `/kb:compile` from integrating the transcript on its own.
It reads the transcript when it promotes the article.

## 4. Pick key frames

Pick three to eight timestamps where a frame shows something words cannot: code at a key moment, an architecture diagram, a results table or plot, a whiteboard or annotated slide, or a before-and-after comparison.
Skip talking heads.

```bash
kb-video frames <id> 02:34 05:12 08:45
```

Frames land in `video_scratch/<id>/frames/frame-<HHhMMmSSs>.jpg`.
Look at each one, and discard any that is blank, mid-transition or uninformative.
Move only the frames the article will use:

```bash
mkdir -p <raw>/images/<slug>-<id>/
mv video_scratch/<id>/frames/frame-<HHhMMmSSs>.jpg <raw>/images/<slug>-<id>/
```

## 5. Write the article

Create `<raw>/videos/<slug>-<id>.md`: a structured discussion organised by concept, not a transcript or a line-by-line paraphrase.
Every claim must come from the transcript or a frame you looked at.
Where you add context the video does not give, say so in the text, or leave it out.

```markdown
---
type: tutorial | tool-guide | concept | discussion | notes | other
title: <video title>
description: <one sentence on what the video covers and what a reader gains>
author: <your model id; the article is agent-written>
date_added: <today, YYYY-MM-DD>
source_type: technical | discussion | experiment | meeting
tags: [tag1, tag2, tag3]
video:
  url: <full url>
  video_id: <id>
  channel: <channel name>
  duration: <HH:MM:SS>
  uploaded: <YYYY-MM-DD>
  transcription_method: youtube_captions | whisper:<model>
  transcript: <raw>/videos/<slug>-<id>.transcript.md
---

# <Video title>

<Two to four sentences: who made it, what it covers and why it matters.>

![source](https://img.shields.io/badge/source-youtube-red) ![type](https://img.shields.io/badge/type-<source_type>-blue) ![duration](https://img.shields.io/badge/duration-<duration_badge>-lightgrey) ![transcription](https://img.shields.io/badge/transcription-<method>-purple)

## 🔗 Prerequisites

- <Topic>: what background helps and why

## 🎯 Key Takeaways

- <Three to five bullets with the core insights.>

## <Concept section>

<Explain the idea, its motivation and its mechanics.>

![<Caption saying what the frame shows>](../images/<slug>-<id>/frame-XXhYYmZZs.jpg)

## 🔮 Open Questions

- <Questions the video leaves open, and links to topics already in the wiki that you know of.>

## Sources

- [<Video title>](<url>), YouTube, <channel>, <upload date>
- [Transcript](./<slug>-<id>.transcript.md), <transcription method>
```

- Prose follows `${CLAUDE_PLUGIN_ROOT}/references/house-style.md`.
- Write code shown on screen in fenced blocks and formulas in LaTeX.
- Give every embedded frame a caption, never `![](...)`.
- Wrap the body in `<!-- source: <raw>/videos/<slug>-<id>.md -->` and `<!-- /source -->`.
- Pick three to six lowercase, hyphenated tags that name concepts, not surface keywords.
- `source_type`: `technical` for tutorials, lectures and explainers (the default), `discussion` for panels and interviews, `experiment` for benchmark walkthroughs, `meeting` for recorded meetings.
- Match length to substance: about 400 words for a five-minute tip, 1,500 to 2,500 for a 30-minute paper walkthrough.

## 6. Clean up and report

Once the article and transcript are in place, remove the scratch directory, whose audio and video run to hundreds of megabytes:

```bash
kb-video cleanup <id>
```

Use `kb-video cleanup` rather than deleting it by hand.
Do not commit, because `/kb:compile` integrates the article and commits it.

Tell the user the article and transcript paths, the transcription method and why, how many frames you kept and what they show, a one-paragraph summary, and that `/kb:compile` integrates it.

## Failure modes

- An age-gated, region-locked or private video makes `kb-video fetch` raise `IngestionError`: report it and stop.
- `needs the okf-kb [video] extra` means `yt-dlp`, `mlx-whisper` or `python-slugify` is missing.
  The error carries the exact install command, chosen to keep the user's other extras, so relay it verbatim.
  Never suggest `uv add mlx-whisper` or `pip install yt-dlp`, which install into the current project instead of the environment `kb-video` runs from.
- `ffmpeg not found`: tell the user to run `brew install ffmpeg`, since no extra can supply it.
