---
name: video
description: >
  Ingest a YouTube video — fetch raw materials, judge transcript quality (running MLX Whisper if
  auto-captions are unusable), extract key frames via ffmpeg, and write a structured discussion
  article in raw/videos/.
  Does not commit — /compile integrates the article into the wiki.
when_to_use: When the user provides a YouTube URL or says "ingest this video" or "transcribe this video".
allowed-tools: Read Write Bash(kb-video *) Bash(mkdir *) Bash(mv *)
disable-model-invocation: true
argument-hint: <youtube-url> [--force-whisper]
---

# Video

Ingest a YouTube video into the knowledge base.
The Python tool (`kb-video`) only stages raw materials — you make every editorial decision.

## Step 1 — Fetch raw materials

Detect whether the user passed `--force-whisper`. Then run:

```bash
kb-video fetch "<url>"
```

This stages into `video_scratch/<id>/`:
- `metadata.json` — title, channel, description, chapters, slug
- `transcript.md` — captions parsed and karaoke-deduplicated (or a placeholder if no captions exist)
- `audio.wav` — 16 kHz mono, ready for Whisper
- `video.mp4` — low-res video, ready for ffmpeg frame extraction

The command prints `id:`, `slug:`, and `scratch:` lines — record those, you need them for every following step.
Then **read `video_scratch/<id>/metadata.json` and `video_scratch/<id>/transcript.md`** to orient yourself.

## Step 2 — Judge transcript quality (be strict)

If the user passed `--force-whisper`, skip the check and go straight to running Whisper.

Otherwise, **read the full transcript carefully**.
Reject the captions (and run Whisper) if **any** of these are true:

| Symptom | Why it matters |
|---|---|
| Words from the title or description appear misspelled or replaced (e.g. *Pydantic* → *pi-dantic*) | Auto-captions mangle technical jargon |
| Long stretches with no punctuation, run-on sentences | Indicates auto-captions; Claude can't reason about structure |
| Entire phrases repeated 2–3× in adjacent paragraphs | Karaoke artifact slipped past the dedup |
| The placeholder `_(no usable captions; ...)_` appears | No captions were retrievable at all |
| Transcript is suspiciously short for the video duration | Captions covered only part of the video |

Be strict.
The cost of running Whisper is 1–3 minutes; the cost of a bad transcript is a useless article.
If you're on the fence, run Whisper.

To re-transcribe:

```bash
kb-video whisper <id>
```

This rewrites `video_scratch/<id>/transcript.md`.
**Re-read it** afterwards.
Note the new `transcription_method` from the file's leading comment.

## Step 3 — Pick key frames

Skim the (now-final) transcript and pick **3–8 timestamps** where a frame would meaningfully accompany the article.
Look for moments where the video shows something words can't capture cleanly:
- Code on screen at a key reveal
- Architecture diagrams or system sketches
- Result tables or benchmark plots
- Whiteboard explanations or annotated slides
- Side-by-side comparisons (before/after)

Skip pure talking-head segments — they add nothing.

Convert each timestamp to `MM:SS` or `HH:MM:SS` form. Then extract:

```bash
kb-video frames <id> 02:34 05:12 08:45 ...
```

Frames land in `video_scratch/<id>/frames/frame-<HHhMMmSSs>.jpg`.
**Read each one** — you can see images.
Discard any that are blank, mid-transition, or low-information.

For each frame you intend to use in the article, move it to the document's image directory:

```bash
mkdir -p raw/images/<slug>-<id>/
mv video_scratch/<id>/frames/frame-<HHhMMmSSs>.jpg raw/images/<slug>-<id>/
```

Only frames that will be referenced in the final article belong in `raw/images/`.
Everything else stays in scratch and gets deleted by cleanup.

## Step 4 — Write the article

Create `raw/videos/<slug>-<id>.md`.
This is **a structured discussion**, not a transcript.
Synthesise — don't paraphrase line-by-line.

### Required structure

```markdown
---
type: tutorial | tool-guide | concept | discussion | notes | other
title: <video title>
description: <one sentence — what the video covers and what a reader gains>
author: <your own model id, e.g. claude-sonnet-5 — this article is agent-written>
date_added: <today YYYY-MM-DD>
source_type: technical | discussion | experiment | meeting
tags: [tag1, tag2, tag3]
video:
  url: <full url>
  video_id: <id>
  channel: <channel name>
  duration: <HH:MM:SS>
  uploaded: <YYYY-MM-DD>
  transcription_method: youtube_captions | whisper:<model>
---

# <Video Title>

<One-paragraph intro: who from, what it covers, why it matters. 2–4 sentences.>

![source](https://img.shields.io/badge/source-youtube-red) ![type](https://img.shields.io/badge/type-<source_type>-blue) ![duration](https://img.shields.io/badge/duration-<duration_badge>-lightgrey) ![transcription](https://img.shields.io/badge/transcription-<method>-purple)

## 🔗 Prerequisites

- <Topic A> — what background helps and why
- <Topic B> — what background helps and why

## 🎯 Key Takeaways

- 3–5 bullets capturing the core insights.

## <Concept-organized section 1>

<Discussion. Explain the idea, the motivation, the mechanics.>

![Caption explaining what the frame shows](../images/<slug>-<id>/frame-XXhYYmZZs.jpg)

## <Concept-organized section 2>

...

## 🔮 Open Questions

- Questions the video itself leaves open
- Connections / contradictions with topics already in the wiki (if you know of any)
- "What if?" extensions worth exploring

## Sources

- [<Video Title>](<url>) — YouTube, <channel>, <upload date>
```

### Writing guidelines

- **Synthesise, don't transcribe.**
Organise by *concept*, not by chronology.
- **Be self-contained.**
A reader should grasp the substance from the article alone.
- **Reproduce code and equations.**
If the speaker showed code, write it out in a fenced block.
If they wrote a formula, use LaTeX.
- **Embed frames where they reinforce a point.**
Each image needs a real caption — never `![](...)`.
- **Use source provenance markers.**
Wrap the body in `<!-- source: raw/videos/<slug>-<id>.md -->` and `<!-- /source -->`.
- **Tag thoughtfully.**
Pick 3–6 lowercase, hyphenated tags that match *concepts*, not surface keywords.
- **`source_type`**: `technical` for tutorials/lectures/explainers (default), `discussion` for panels/interviews, `experiment` for benchmark walkthroughs, `meeting` for recorded meetings.

### Length

Match the video's substance.
A 5-min tip → ~400 words is fine.
A 30-min paper walkthrough → ~1500–2500 words.
Don't pad. Don't truncate.

## Step 5 — Cleanup

Once the article is written and reviewed, remove scratch:

```bash
kb-video cleanup <id>
```

This deletes `video_scratch/<id>/` (audio.wav and video.mp4 are tens to hundreds of MB — don't leave them around).

## Step 6 — Report back

Tell the user:
- Path to the final article
- Transcription method used + a one-line rationale
- How many frames were kept and one-line on what they show
- One-paragraph summary of what the article covers
- Reminder that `/compile` will integrate it into the wiki

## Failure modes

- **Age-gated/region-locked/private video** → `kb-video fetch` raises `IngestionError`. Surface and stop.
- **`mlx-whisper not installed`** → tell the user `uv add mlx-whisper` (Mac only).
- **`ffmpeg not found`** → tell the user `brew install ffmpeg`.
- **Very long video (>1h)** with Whisper → warn the user transcription may take 10+ minutes.

## What NOT to do

- Don't dump the transcript into the article. Synthesise.
- Don't put frames in `raw/images/` unless you're referencing them in the article.
- Don't commit — the user runs `/compile` next.
- Don't skip the quality judgement.
- Don't manually delete `video_scratch/<id>/` — use `kb-video cleanup`.
