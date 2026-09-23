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
allowed-tools: mcp__plugin_kb-query_okf-kb__bundles mcp__plugin_kb-query_okf-kb__search mcp__plugin_kb-query_okf-kb__neighbours mcp__plugin_kb-query_okf-kb__roots mcp__plugin_kb-query_okf-kb__shortest_path mcp__plugin_kb-query_okf-kb__read
---

# Wiki

Search the knowledge bases in scope, follow their links where one article is not enough, and read what you find.
The tools come from the `okf-kb` MCP server, which this plugin starts in Claude Code and the user registers in the Claude desktop app.
Every tool is read-only. Nothing in this skill can compile, reindex or edit a knowledge base.

## Procedure

0. **Establish scope.**
   Call `bundles`, unless you already did this conversation.
   Each entry names a bundle, its path, and its `source`: `walk-up` means the session is inside that bundle.
   If `bundles` is empty, say in one line that no knowledge base is in scope, and answer without the wiki.
   Do not treat this as an error, and do not suggest configuration unless the user asks.
   If the tools are not available at all, say in one line that the okf-kb MCP server is not connected, and stop.
   If a tool returns an error, report it verbatim. A scope error names the file that declared a broken path.
1. **Search.**
   Call `search` with the terms.
   Pass `kb` when the user names a knowledge base. Pass `tag` or `article_type` when the topic has a clear category.
   `titles_only` is a cheap first probe when you expect a well-named article.
   Each result carries `bundle`, `rel`, `title`, `description` and `score`.
2. **Stop early when one article answers it.**
   If the top hit scores well clear of the rest and its snippet answers the question, `read` it and go to step 5.
   Most queries end here.
3. **Otherwise, traverse.**
   Do this when the hits are several and mediocre, or the question is "how does X relate to Y" or "everything we have on X".
   Call `neighbours` with the top hits and `depth` 1 to get their links and backlinks.
   Call `roots` to place the hits in each bundle's taxonomy.
   `shortest_path` answers "how are these two connected"; it only works within one bundle.
   Links are followed both ways, so read each hop's direction: `forward` means the earlier article links to the later, `backward` is a backlink.
4. **Read.**
   `read` each selected article, at most ten in total.
   Pass the `rel` from a result together with its `bundle` as `kb` when the same path could exist in more than one bundle.
   Pass `section` (e.g. `"## Sources"`) when you only need part of a long article, and `strip_frontmatter` when the metadata adds nothing.
   Stop expanding when a hop adds no new articles.
5. **Report.**
   Give file paths grouped by bundle, the relevant excerpts, and an explicit statement of whether coverage is sufficient or where the gaps are.

## Rules

- **Wiki first.** When `bundles` reports a `walk-up` bundle, you are working inside a knowledge base.
  Run this skill before any web search, web fetch or external research skill, always.
- **From another project or the desktop app, check before answering from memory.** When every bundle comes from a project file, the user config or `kb`,
  run this skill before answering from training data. It does not have to precede a web search the user asked for.
- If the wiki has good coverage, summarise it and ask whether external research is still needed.
- If the wiki has partial coverage, say exactly what is missing so the follow-up search is targeted.
- If the wiki has no coverage, say so clearly. Do not invent or infer from training data.
- Read articles with `read`, not a general file reader: it needs no permission prompt for paths outside the project and refuses anything that is not a wiki article.
- Never compose an install or configuration command. Relay what a tool error says.
