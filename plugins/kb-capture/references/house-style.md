# House style

These rules govern the prose a skill writes into a knowledge base: article bodies, frontmatter `title` and `description` values, log entries, notes, briefs and meeting records.
The Writing style section of the bundle's `CLAUDE.md` governs first and is the fuller version.
This file restates its core because a bundle scaffolded before those rules existed does not have them.
Every plugin that writes prose ships an identical copy, and a test keeps the copies in step.

## Rules

- British English, plain sentences, active voice.
  Use the passive only where the agent is genuinely irrelevant or unknown.
- No em dashes or en dashes as sentence punctuation.
  Use commas, full stops, colons or brackets, and hyphens for numeric ranges (2019-2024).
- In YAML frontmatter, never replace an em dash with a colon, because an unquoted `: ` does not parse.
  Reword, use a full stop, or leave the em dash.
- Sentence case for any heading you add.
  Headings that come from a template stay exactly as written, emoji and dashes included, because the skills find sections by those headings.
- No antithesis framing ("not just X, but Y"), colon-then-reveal ("The result: chaos"), rule-of-three padding, sentence fragments for emphasis or one-line paragraphs used as a drum beat.
- No filler hedges: "it's worth noting", "it's important to note", "that said", "at its core".
- None of these words: delve, leverage, harness, unlock, seamless, holistic, pivotal, crucial, underscore, foster, showcase, testament to, landscape, journey, empower, realm, tapestry, deep dive, game-changer, elevate, boasts.
  Use robust only as the statistical term.
- No vague authority ("studies show", "experts agree").
  Every claim in a knowledge base is traceable to a source, so name it.
- One name per thing.
  Do not vary the term for one concept within a document.
- One sentence per line in markdown bodies, for clean git diffs.

Quotations, code, equations and anything under a raw-transcript or raw-input heading stay exactly as the source has them.
Cleaning a user's own words may change their phrasing to meet these rules, never their meaning.
