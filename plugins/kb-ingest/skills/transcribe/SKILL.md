---
name: transcribe
description: >
  Transcribe handwritten notes in raw/handwritten/ that have no transcription yet
  into clean structured markdown in raw/transcriptions/, without touching the
  originals. Use when the user says "transcribe my handwritten notes" or "process
  handwritten".
disable-model-invocation: true
allowed-tools: Read Write Bash(kb-ingest list-untranscribed) Bash(kb-doctor paths) Bash(git add *) Bash(git commit *)
---

# Transcribe

Transcribe every handwritten note in `<raw>/handwritten/` that has no transcription yet.
Never modify, move or delete anything in `<raw>/handwritten/`, because the originals are the source, and the folder is often a link to a note app's export directory outside the bundle.

## Workflow

1. Run `kb-doctor paths` and take `<raw>` from its `raw` value.
2. Run `kb-ingest list-untranscribed`.
   If it lists nothing, say that everything is transcribed and stop.
3. For each listed file:
   - read the image or PDF with vision;
   - transcribe it into structured markdown, keeping the original headings and bullets, describing diagrams in text and writing arrows as relationships;
   - write maths in LaTeX, `$inline$` and `$$display$$`;
   - mark anything you cannot read as `<!-- unclear: ... -->` rather than guessing;
   - save it as `<raw>/transcriptions/<stem>.md`, where `<stem>` is the original filename without its extension.
     `list-untranscribed` matches on the stem, so `note.png.md` would be transcribed again on every run.
4. Commit: `git add <raw>/transcriptions/ && git commit -m "transcribe: <N> handwritten notes"`.
5. Ask whether to compile the new transcriptions now or later.
