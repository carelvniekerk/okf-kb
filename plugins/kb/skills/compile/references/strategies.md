# Integration strategies

How `/kb:compile` turns one classified source into wiki content.
Read the pre-processing section for a daily brief or a video source, then the section for the source's type.
Every strategy wraps the content it adds in `<!-- source: <path> -->` ... `<!-- /source -->` markers and keeps the compile rules: only what the source supports, no `verified`, no hand-edited index.

## Contents

- Pre-processing a daily brief
- Pre-processing a video source
- Meeting sources
- Discussion sources
- Experiment sources
- Technical sources

## Pre-processing a daily brief

A source under `<raw>/daily-briefs/`, or with `type: daily-brief`, comes from `/kb-capture:capture brief`.
Most of a brief is personal and transient: mood, calendar, todos, inbox, follow-ups and the raw transcript.
Only its notes can hold knowledge.

1. Take only the `## 📝 Notes` section, including any `_Update HH:MM:_` lines inside it, and the notes sub-content of any older `## 🔄 Session N` block.
   Ignore every other section, whatever it is called.
2. If the notes are empty or trivial (whitespace, or one short sentence with no identifiable topic), skip the brief and log it as `⏭️ <path>: no knowledge-worthy notes`.
3. Otherwise treat the notes as the source content, and still use the full brief path in the provenance markers.
4. If the notes cover several unrelated topics, integrate each as its own source.
   Do not merge unrelated notes into one article.

## Pre-processing a video source

A source at `<raw>/videos/<slug>-<id>.md` comes from `/kb-video:video` and is already a structured article, so promote it rather than re-synthesise it.
Beside it sits `<raw>/videos/<slug>-<id>.transcript.md`, the verbatim transcript, which carries `compile: false` and is never integrated on its own.

- Base the wiki article's `tags`, `type` and `source_type` on the source's frontmatter.
- Carry over Key Takeaways and Open Questions with light editing at most.
- Check the article's claims against the transcript, and drop any the transcript does not support.
- Add both files to `sources`: the article as the primary source and the transcript as the record it was written from, so `/kb:verify` reads the transcript too.
- Rewrite every image path so it resolves from the wiki article's own location.
  The source links `../images/<slug>-<id>/frame-....jpg` relative to `<raw>/videos/`, and an article at `<wiki>/<section>/<name>.md` needs the path from its directory to `<raw>/images/<slug>-<id>/`.
- Related-article discovery and the user prompt still apply.

## Meeting sources

Meetings add to the record and never overwrite earlier meetings.

- Find or create a chronological section such as `## Meeting History`.
- Append the meeting under a dated subheading: `### YYYY-MM-DD: <meeting topic>`.
- Put action items in their own subsection, and mark earlier items done (✅) only when the new meeting confirms it.
- Add decisions to a running list or table.
- Update `## 🎯 Key Takeaways` to the latest state and decisions.
- In `## 🔮 Open Questions`, resolve what the meeting answered and add what it raised.

## Discussion sources

Discussions evolve, so track how the consensus moves.

- Where the source extends an existing thread, add its points under the headings they belong to.
- Mark a superseded position with ~~strikethrough~~ or `**[Superseded YYYY-MM-DD]**` and add the new position beside it.
- When a decision is reached, make it prominent.
- A new thread on the same topic gets its own subsection.
- Update `## 🎯 Key Takeaways` to the current consensus, and resolve or add `## 🔮 Open Questions`.

## Experiment sources

Results are data, so never overwrite them silently.

- Same experiment, new data: append rows to the existing table and add `*Updated YYYY-MM-DD*` below it.
- Same method, better results: update the table and keep the earlier numbers in a collapsed "Previous results" section or a footnote, so the progression stays visible.
- Different method: add a new table or section labelled with the method, and do not merge it with the old one.
- Contradictory results: show both, labelled, and add the discrepancy to `## 🔮 Open Questions`.
- Base `## 🎯 Key Takeaways` on the latest and most reliable results.

## Technical sources

A technical article states the current state of knowledge.

- Where the source pins versions, label the content by version:

  ```markdown
  > **v2.0** (YYYY-MM-DD): New feature X replaces deprecated feature Y.
  ```

  Keep version history where it helps understanding, and remove version detail that no longer matters.
- Replace stale information cleanly, so the article reads as a current reference.
- Where a newer source contradicts the article, the newer source wins: replace the old content instead of keeping both, and name the source that changed it in the log entry.
- Integrate additions that contradict nothing into the existing structure.
- Update `## 🎯 Key Takeaways` when the core insight changes, and `## 🔮 Open Questions` as needed.
