---
name: transcribe
description: >
  Transcribe any untranscribed handwritten notes in raw/handwritten/ into clean structured markdown.
  Saves transcriptions to raw/transcriptions/.
  Never modifies or deletes files in raw/handwritten/ (it is a symlinked external directory).
when_to_use: When the user says "transcribe handwritten notes", "process handwritten", or types /kb-ingest:transcribe.
allowed-tools: Read Write Bash(kb-ingest list-untranscribed) Bash(git *)
disable-model-invocation: true
---

# Transcribe

Transcribe any untranscribed handwritten notes in `raw/handwritten/`.

**Critical: Never modify or delete any files in `raw/handwritten/`. It is a symlinked external directory.**

## 1. Identify untranscribed files

Run `kb-ingest list-untranscribed` to identify files in `raw/handwritten/` that do not yet have a transcription in `raw/transcriptions/`.
If there are none, report that everything is already transcribed and stop.

## 2. Transcribe each file

For each untranscribed file:
a. Open and read the image/PDF using vision.
b. Transcribe the handwritten content into clean, structured markdown.
c. Preserve the original structure: headings, bullet points, diagrams described as text, arrows as relationships.
d. For mathematical notation, use LaTeX syntax: `$inline$` and `$$display$$`.
e. If the handwriting is ambiguous, include a `<!-- unclear: ... -->` comment rather than guessing.
f. Save the transcription to `raw/transcriptions/<original-filename>.md`.

## 3. Commit

```bash
git add raw/transcriptions/ && git commit -m "transcribe: <N> handwritten notes"
```

## 4. Offer to compile

Ask whether to compile the new transcriptions into the wiki now or defer.
