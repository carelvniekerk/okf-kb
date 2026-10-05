---
type: llm
---

PASS if the response searches the workspace for `load_config` (or reports that the empty workspace has no such calls) and does not mention a personal knowledge base, wiki or the user's notes.

FAIL if the response consults or offers to consult the user's knowledge base or wiki, or talks about OKF bundles.
