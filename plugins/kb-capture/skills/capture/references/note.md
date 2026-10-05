# Capturing a note

The procedure for `/kb-capture:capture note`, after the input has been gathered.

## 1. Name the file

Pick a short kebab-case slug of at most four words for the topic.
The path is `<raw>/notes/YYYY-MM-DD-<slug>.md` with today's date, and if it exists, append `-2`, `-3` and so on.

## 2. Find related articles

Run `kb-search "<key terms from the note>" --json-output`, pick the two to four genuinely related results and read one or two to confirm.
They become `## Related Articles`.

## 3. Structure the note

```markdown
---
type: note
title: <title derived from the content>
description: <one sentence on what is in this note and why someone would open it>
author: human:<id>   # the bundle's human id, from its CLAUDE.md
date_added: YYYY-MM-DD
source_type: technical | discussion | experiment
tags: [tag1, tag2, tag3]
---

# <Title derived from the content>

<One-paragraph summary in the user's own words, cleaned up.>

![Type](https://img.shields.io/badge/type-notes-blue) ![Added](https://img.shields.io/badge/added-YYYY--MM--DD-lightgrey)

## 🔗 Prerequisites

<Only if the note clearly depends on other concepts. Otherwise omit the section.>

## 🎯 Key Takeaways

- <Up to five bullets drawn only from what the user said. A thin note gets fewer.>

## <Content sections>

<Headings that suit the topic. Keep every substantive claim and example, and drop filler, hedges and verbal tics.>

## 🔮 Open Questions

- <Only questions the user raised. Do not add your own.>

## Related Articles

- [<Title>](<path relative to this note>): <one-line reason>

## Raw Transcript

<!-- source: <raw>/notes/YYYY-MM-DD-<slug>.md -->
<The input verbatim, with only sentence breaks and obvious transcription errors fixed.>
<!-- /source -->

## Sources

- Captured <voice | pasted | typed> on YYYY-MM-DD.
```

Choose `source_type` from the content.

## 4. Save, commit and offer to compile

1. Write the file.
2. `git add <the note> && git commit -m "note: <title>"`.
3. Append to `<log>`: `## [YYYY-MM-DD] 📥 ingest | note: <title>`.
4. Ask: "Compile this into the wiki now, or later?"
