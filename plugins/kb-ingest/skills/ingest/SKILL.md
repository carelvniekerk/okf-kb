---
name: ingest
description: >
  Ingest a new source into the knowledge base — handles arXiv papers, local PDFs, web clippings,
  and manual notes already in raw/.
  Fetches content, localises images, commits, and offers to compile.
  YouTube videos are handled by /video instead.
when_to_use: When the user provides a source to ingest (arXiv ID, URL, PDF path, or raw/ file) and asks to add it to the knowledge base.
allowed-tools: Read Write Bash(kb-ingest *) Bash(git *) WebFetch
disable-model-invocation: true
argument-hint: <arXiv ID, URL, file path, or "raw/...">
---

# Ingest

Ingest a new source into the knowledge base. The source is: $ARGUMENTS

Determine the source type from the argument and follow the appropriate workflow:

## arXiv paper (ID like `2402.12345` or arXiv URL)

1. Run `kb-ingest arxiv <arxiv-id>` — this fetches the ar5iv HTML (or falls back to PDF), saves markdown to `raw/papers/<arxiv-id>.md`, and downloads figures to `raw/images/<arxiv-id>/`.
2. Check the output for warnings (e.g. very few section headings = incomplete conversion).
3. Commit: `git add raw/papers/ raw/images/ && git commit -m "ingest: arxiv <arxiv-id>"`.
4. Append to `wiki/log.md`: `## [YYYY-MM-DD] 📥 ingest | arXiv <arxiv-id> — <paper title>`
5. Ask whether to compile the new paper into the wiki now or defer.

## Local PDF (file path)

1. Run `kb-ingest extract-pdf <path>` to produce a markdown file.
2. If the PDF contains figures, run `kb-ingest download-images <output.md>` to fetch and localise any image references.
3. Commit: `git add raw/ && git commit -m "ingest: <filename>"`.
4. Append to `wiki/log.md`: `## [YYYY-MM-DD] 📥 ingest | <filename>`
5. Ask whether to compile now or defer.

## Web clipping (URL or file in `raw/clippings/`)

1. If a URL was given, fetch the page and save as markdown to `raw/clippings/<slug>.md`.
2. Run `kb-ingest download-images raw/clippings/<slug>.md` to localise images to `raw/images/<slug>/`.
3. Commit: `git add raw/clippings/ raw/images/ && git commit -m "ingest: clipping <slug>"`.
4. Append to `wiki/log.md`: `## [YYYY-MM-DD] 📥 ingest | <slug>`
5. Ask whether to compile now or defer.

## YouTube video (URL like `https://www.youtube.com/watch?v=...`)

Defer to the `/video` skill — it stages raw materials in `video_scratch/`, judges transcript quality, extracts key frames via ffmpeg, and writes a structured discussion article in `raw/videos/<slug>-<id>.md`.
Do not invoke `kb-ingest` for videos.

## Manual note (already in `raw/`)

1. Confirm the file exists and is readable.
2. Run `kb-ingest download-images <file>` if it contains external image URLs.
3. Commit any changes: `git add raw/ && git commit -m "ingest: <filename>"`.
4. Append to `wiki/log.md`: `## [YYYY-MM-DD] 📥 ingest | <filename>`
5. Ask whether to compile now or defer.

If the argument is unclear or missing, ask the user to specify the source.
