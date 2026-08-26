---
name: wiki-search
description: >
  Internal knowledge base lookup — searches wiki/INDEX.md and runs the kb-search BM25 full-text search tool.
  Use this skill FIRST, before any external search or web lookup, whenever the user asks a question, wants to know what has been researched before, references something "we discussed" or "I wrote about", asks "what do we know about X" or "have I covered X", or when starting any compile, ingest, or research task.
  The wiki-first rule is mandatory: never reach for web search before checking the local wiki.
  Also use this when compiling new sources, to surface related existing articles that should be cross-linked.
when_to_use: >
  Trigger phrases: "what do we know about", "have I covered", "is there an article on", "what's in the wiki",
  "check the wiki", "search the wiki", "look it up", "what did we say about", "find the article on",
  "before we research", "what do we already have on", "/wiki".
allowed-tools: Read Bash(kb-search *)
---

# Wiki Search (Internal Knowledge Base)

Search the local wiki for existing articles, concepts, and prior research before doing anything externally.
This skill is for **internal** retrieval only — use `research:external-research` for web and academic sources.

## Procedure

1. **Orient with the index.**
   Read `wiki/INDEX.md` to get the current structure and spot obviously relevant sections.
2. **Run BM25 search.**
   Run `kb-search "<query>"` for full-text search across all wiki articles.
   Add `--tag <tag>` or `--type <type>` to filter when the topic has a clear category.
   Use `--json-output` for structured output when chaining results into another tool.
3. **Read the matches.**
   Open the top-matching article files directly and read the sections most relevant to the query.
4. **Report.**
   Return file paths, relevant excerpts, and a gap assessment.

## Output

- File paths and relevant excerpts from matching wiki articles.
- An explicit statement of whether the wiki coverage is sufficient or has gaps requiring external research.
- Pointers to related articles the user did not ask about but that are clearly relevant.

## Rules

- Always run this skill before reaching for `WebSearch`, `WebFetch`, or the `research:external-research` skill.
- If the wiki has good coverage, summarise it and ask whether external research is still needed.
- If the wiki has partial coverage, note exactly what is missing so the follow-up search is targeted.
- If the wiki has no coverage, say so clearly — do not invent or infer from training data.
