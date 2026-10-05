---
name: wiki
description: >
  Search the user's own knowledge bases (OKF wikis) and read what they say, before
  answering from training data or searching the web. Use when the user asks what
  they know, wrote, read or discussed about a topic, whether an article exists on
  it, or how two topics in their notes relate, and before starting research or a
  compile on a topic.
when_to_use: >
  Trigger phrases: "what do we know about", "have I covered", "is there an article on",
  "what's in the wiki", "check the wiki", "search my notes", "what did we say about",
  "find the article on", "before we research", "what do we already have on",
  "how does X relate to Y", "everything we have on".
allowed-tools: mcp__plugin_kb-query_okf-kb__bundles mcp__plugin_kb-query_okf-kb__search mcp__plugin_kb-query_okf-kb__neighbours mcp__plugin_kb-query_okf-kb__roots mcp__plugin_kb-query_okf-kb__shortest_path mcp__plugin_kb-query_okf-kb__read
---

# Wiki

Search the knowledge bases in scope, follow their links where one article is not enough, and read what you find.
The tools come from the `okf-kb` MCP server, whose instructions give the short form of this procedure and apply here too.
This skill adds when to use each tool's parameters.
Every tool is read-only, so nothing here can compile, reindex or edit a knowledge base.

## Procedure

1. Establish scope.
   Call `bundles`, unless you already did in this conversation.
   Each entry names a bundle, its path and its `source`, where `walk-up` means the session is inside that bundle.
   An empty list is a state, not an error: say in one line that no knowledge base is in scope, answer without it and do not suggest configuration unless asked.
   If the tools are not available at all, say in one line that the okf-kb MCP server is not connected, and stop.
2. Search.
   Call `search` with the terms.
   Pass `kb` when the user names a knowledge base, and `tag` or `article_type` when the topic has a clear category.
   `titles_only` is a cheap first probe when you expect a well-named article.
   Each result carries `bundle`, `rel`, `title`, `description` and `score`.
3. Stop early when one article answers it.
   If the top hit scores well clear of the rest and its description answers the question, `read` it and go to step 6.
   Most queries end here.
4. Otherwise, traverse.
   Do this when the hits are several and mediocre, or the question asks how X relates to Y or for everything on X.
   Call `neighbours` on the top hits with `depth` 1 for their links and backlinks, and `roots` to place them in each bundle's taxonomy.
   `shortest_path` answers how two articles are connected, within one bundle.
   Read each hop's direction: `forward` means the earlier article links to the later, and `backward` is a backlink.
   Stop expanding when a hop adds no new articles.
5. Read.
   `read` each selected article, at most ten in total.
   Pass the result's `rel` with its `bundle` as `kb` when the same path could exist in more than one bundle.
   Pass `section` (for example `"## Sources"`) when you need part of a long article, and `strip_frontmatter` when the metadata adds nothing.
   Use `read` rather than a general file reader, because it needs no permission prompt outside the project and refuses anything that is not a wiki article.
6. Report.
   Give file paths grouped by bundle and the relevant excerpts, then say whether coverage is sufficient or exactly what is missing.

## Rules

- Inside a knowledge base (a `walk-up` bundle), run this before any web search, web fetch or external research skill.
- From another project or the desktop app, run this before answering from training data.
  It need not precede a web search the user asked for.
- With good coverage, summarise it and ask whether external research is still needed.
  With partial coverage, name what is missing so the follow-up search is targeted.
- With no coverage, say so.
  Never fill the gap from training data and present it as the wiki's.
- Report a tool error verbatim, because it is written for the user.
  A scope error names the file that declared a broken path.
  Never compose an install or configuration command.
