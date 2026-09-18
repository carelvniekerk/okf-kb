---
name: wiki
description: >
  Internal knowledge base retrieval. Searches and traverses the wiki(s) in scope.
  Use FIRST, before answering from training data or reaching for the web, whenever the user asks a question,
  references something "we discussed" or "I wrote about", asks what is known about X,
  or when starting any research or compile task.
when_to_use: >
  Trigger phrases: "what do we know about", "have I covered", "is there an article on", "what's in the wiki",
  "check the wiki", "search the wiki", "look it up", "what did we say about", "find the article on",
  "before we research", "what do we already have on", "how does X relate to Y", "everything we have on", "/wiki".
allowed-tools: Read Bash(kb-doctor *) Bash(kb-search *) Bash(kb-graph *) Bash(kb-read *)
---

# Wiki

Search the knowledge bases in scope, follow their links where one article is not enough, and read what you find.
Every command here is read-only. Nothing in this skill can compile, reindex or edit a knowledge base.

## Procedure

0. **Establish scope.**
   Run `kb-doctor bundles --json-output`, unless you already ran it this session.
   Each entry names a bundle, its path, and its `source`: `walk-up` means the working directory is inside that bundle.
   If `bundles` is empty, say in one line that no knowledge base is in scope, and answer without the wiki.
   Do not treat this as an error, and do not suggest configuration unless the user asks.
   If the command exits non-zero, report its error verbatim. It names the file that declared a broken path.
1. **Search.**
   Run `kb-search "<terms>" --json-output`.
   Add `--kb <name>` when the user names a knowledge base. Add `--tag` or `--type` when the topic has a clear category.
   `--fields title` is a cheap first probe when you expect a well-named article.
   Each result carries `bundle`, `rel`, `title`, `description` and `score`.
2. **Stop early when one article answers it.**
   If the top hit scores well clear of the rest and its snippet answers the question, `kb-read` it and go to step 5.
   Most queries end here.
3. **Otherwise, traverse.**
   Do this when the hits are several and mediocre, or the question is "how does X relate to Y" or "everything we have on X".
   Run `kb-graph neighbours <top hits> --depth 1 --json-output` to get their links and backlinks.
   Run `kb-graph roots --json-output` to place the hits in each bundle's taxonomy.
   `kb-graph shortest-path <a> <b>` answers "how are these two connected"; it only works within one bundle.
   Links are followed both ways, so read each hop's direction: `a -> b` means `a` links to `b`, `a <- b` is a backlink.
4. **Read.**
   `kb-read <path>` each selected article, at most ten in total.
   Pass the `rel` from a result together with `--kb <bundle>` when the same path could exist in more than one bundle.
   Use `--section "## Heading"` when you only need part of a long article, and `--strip-frontmatter` when the metadata adds nothing.
   Stop expanding when a hop adds no new articles.
5. **Report.**
   Give file paths grouped by bundle, the relevant excerpts, and an explicit statement of whether coverage is sufficient or where the gaps are.

## Rules

- **Wiki first.** When `kb-doctor bundles` reports a `walk-up` bundle, you are working inside a knowledge base.
  Run this skill before `WebSearch`, `WebFetch` or any external research skill, always.
- **From another project, check before answering from memory.** When every bundle comes from a project file, the user config or `--kb`,
  run this skill before answering from training data. It does not have to precede a web search the user asked for.
- If the wiki has good coverage, summarise it and ask whether external research is still needed.
- If the wiki has partial coverage, say exactly what is missing so the follow-up search is targeted.
- If the wiki has no coverage, say so clearly. Do not invent or infer from training data.
- Run one `kb-*` command per Bash call. Chaining commands with `;`, `&&`, `echo` or `$?` falls outside this skill's permissions and is refused.
- Read articles with `kb-read`, not `Read`: `kb-read` needs no permission prompt for paths outside the project and refuses anything that is not a wiki article.
- Never compose an install or configuration command. If a `kb-*` command is missing, relay the error or run `kb-doctor` and relay what it prints.
