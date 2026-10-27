---
name: ingest
description: >
  Add a source to the knowledge base's raw zone. Fetches arXiv papers, converts
  local documents (PDF, Word, PowerPoint, Excel, EPUB, Outlook messages) to
  markdown with their figures, clips web pages verbatim and localises images,
  then logs, commits and offers to compile. Use when the user gives an arXiv id,
  a URL, a document path or a file already in the raw zone and wants it added to
  the knowledge base. YouTube videos belong to /kb-video:video.
disable-model-invocation: true
allowed-tools: Read Edit Bash(kb-ingest *) Bash(kb-doctor) Bash(kb-doctor *) Bash(git add *) Bash(git commit *) Bash(date *)
argument-hint: <arXiv id, URL, document path, or a file in the raw zone>
---

# Ingest

Add a source to the knowledge base. The source is: $ARGUMENTS

A raw source is the record every compiled claim is later verified against, so store what the source says and never a summary of it.
Every step below goes through `kb-ingest`, which saves the content verbatim.
Do not use WebFetch to save a page: it returns a model's rendering of the page, not the page.

## Workflow

1. Run `kb-doctor paths`.
   Its `raw` and `log` values are what this skill calls `<raw>` and `<log>`.
   Run the commands below from the bundle root it prints.
2. Pick the row for the argument, run its command and read the output for warnings:

   | Source | Command | Lands in |
   | --- | --- | --- |
   | arXiv id or arxiv.org URL | `kb-ingest arxiv <id>` | `<raw>/papers/<id>.md`, figures in `<raw>/images/<id>/` |
   | Local document (PDF, Word, PowerPoint, Excel, EPUB, Outlook message) | `kb-ingest convert <path>` | Markdown beside the document, figures and images in `<raw>/images/<stem>/` |
   | Web page URL | `kb-ingest clip <url>` | `<raw>/clippings/<slug>.md`, images in `<raw>/images/<slug>/` |
   | A markdown file already in `<raw>` | `kb-ingest download-images <file>`, only if it links external images | In place |
   | YouTube URL | none: stop and point the user to `/kb-video:video` | |

   A document outside `<raw>` should be moved or copied into the bundle first, with the user's agreement, so the source lives there: `<raw>/papers/` for papers and `<raw>/documents/` for everything else.
   `convert` records the document's hash in the markdown, so running it again on an unchanged document says it is up to date.
   If it refuses because a markdown file with no conversion record is in the way, tell the user and offer `--force`, which replaces the body and keeps the frontmatter.
   If the file's frontmatter cannot be read, `--force` discards it and warns, so say that when you offer it.
   A legacy `.doc` or `.ppt` is not supported: ask the user to save it as `.docx` or `.pptx` first.
   An arXiv warning about few section headings means the conversion is likely incomplete: tell the user, and offer to delete the markdown and re-ingest from the PDF.
3. Commit what the command wrote: `git add <raw> && git commit -m "ingest: <short description>"`.
4. Append one line to `<log>` with the Edit tool, keeping the existing entries:
   `## [YYYY-MM-DD] 📥 ingest | <arXiv id: title, file name or page title>`
5. Ask whether to compile the new source now or later.

If the argument is missing or ambiguous, ask which source the user means.

## When `kb-ingest` reports a missing extra

Every `kb-ingest` command except `list-untranscribed` and `list-unconverted` needs the `[ingest]` extra.
It is imported lazily, so the command starts and fails at the step that needs it, with a message that begins:

```
kb-ingest needs the okf-kb [ingest] extra, which is not installed …
```

Relay the install command in that message verbatim.
It is chosen for how the package was installed and keeps every extra the user already has, because `uv tool install --force` replaces the environment and a narrower command would remove `[video]`.
Never suggest `uv add pymupdf` or `pip install requests`: those install into the current project, not into the environment `kb-ingest` runs from.
Then stop, without committing or logging a half-finished ingest.
