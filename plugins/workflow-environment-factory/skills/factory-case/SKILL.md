---
name: factory-case
description: Use Workflow Environment Factory when Codex is launched for a generated code or Issue-to-PR Case and must complete the task inside its fresh workspace.
---

# Factory Case

Use the Workflow Environment Factory MCP tools only for the active Run created by the local factory.

1. Read the Run and Case before acting. Treat the Case goal, allowed paths, allowed tools, and safety limits as the complete task boundary.
2. Work only in the fresh workspace named by the Run. Do not seek a known-correct revision, another Run, product data, or a production account. Repository tests visible inside the workspace may be used normally, but do not change validation files outside the Case's allowed paths.
3. For an Issue-to-PR Case, use `wef_get_issue` before editing, then use `wef_create_pr` and `wef_update_issue_status` for the local simulator. These tools never contact GitHub, Linear, or another external service.
4. Do not change the Case, validators, score, simulator database, or product data directly. A passing command or plausible screen is not proof of completion.
5. When finished, summarize the repository changes and simulator actions. Do not claim a score; the factory independently validates code, changed paths, and database state after Codex exits.

If the local service or a required tool is unavailable, report the limitation instead of inventing Issue, PR, Run, or score data.
