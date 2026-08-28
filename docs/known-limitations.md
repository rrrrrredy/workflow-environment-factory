# Known limitations

## Platform and Agent

- The 0.1 preview supports Windows 11 and Codex only.
- Docker Desktop with Linux containers is required for production Case generation and scoring.
- The UI and service are local; there is no cloud sync, remote team access, or permission model.
- Codex uses the user's active installation and configuration. Other installed plugins or user rules can influence a Run. Use a dedicated acceptance profile for controlled comparisons.

## Case generation

- A code vertical needs a real failing baseline commit and a descendant known-correct commit. The factory does not invent a correct answer.
- Variant generation is deliberately limited to one confirmed string variable, two confirmed replacement values, and confirmed repository-relative text files.
- Binary files, AST transformations, database migrations, multi-repository tasks, merge-conflict tasks, and arbitrary LLM-generated variants are not supported.
- Passing the known negative/positive gate proves discrimination for those states only. It does not prove realism or general model quality.
- Container references must include a digest; the product does not select or trust an image for the user.

## Issue-to-PR simulation

- The simulator implements the minimum local Issue read, PR create/list, and status update state needed by the golden workflow.
- It is GitHub/Linear-style, not a clone of either service. It has no production authentication, webhooks, review comments, CI checks, branch protection, or permission graph.
- The four-step recorder retains structured actions, not a video or full browser transcript.
- Database/API state is the primary verifier. Screenshots are presentation evidence only.

## Runs and scoring

- Every Score represents one attempt. Repeatability and statistical evaluation are not inferred.
- The product records Codex JSONL output, not hidden reasoning.
- Token and monetary-cost extraction is not implemented in 0.1.
- Workspace cleanup is explicit so a user can inspect a completed attempt. Until cleanup, worktrees and simulator snapshots consume disk space.
- A validator command is user-supplied and runs inside the selected Docker image with the worktree mounted writable.

## Packaging

- The release archive installs Python and Node dependencies from their normal package registries; it is not an air-gapped dependency bundle.
- The plugin is registered from the extracted checkout. Moving or deleting that folder before uninstalling can require `-Repair` or manual Codex marketplace cleanup.
- A clean-Windows acceptance report is required before the preview is called stable.
