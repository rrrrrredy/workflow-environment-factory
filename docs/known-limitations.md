# Known limitations

## Platform and Agent

- The 0.2 portable preview provides Windows, Linux, and macOS lifecycle tools for Codex. Linux has hosted real-Docker task gates. macOS has hosted build/plugin/service lifecycle evidence only; no physical Mac, Docker Desktop, or authenticated Codex task was used.
- Docker Desktop with Linux containers is required on Windows/macOS; Docker Engine is required on Linux for production Case generation and scoring.
- The UI and service are local; there is no cloud sync, remote team access, or permission model.
- Codex uses the user's active binary and authentication. Managed Runs ignore ambient user config and installed plugins, explicitly inject only the Factory MCP server, and preserve repository AGENTS rules; a user-selected model or unrelated personal Skill therefore does not automatically carry into a Case. Explicit configuration snapshots are a later-version concern.
- Start the service from a normal user terminal. A service already inside another Codex sandbox may be unable to establish the nested Run sandbox and will fail its no-model preflight instead of running the Agent.
- On 2026-08-28 the current nested development host reproduced `apply deny-read ACLs`; the preflight made zero model calls and removed its sentinel. This is a host limitation, not a completed fresh-Windows acceptance result.

## Case generation

- A code vertical needs a real failing baseline commit and a descendant known-correct commit. The factory does not invent a correct answer.
- Variant generation is deliberately limited to one confirmed string variable, two confirmed replacement values, and confirmed repository-relative text files.
- Binary files, AST transformations, database migrations, multi-repository tasks, merge-conflict tasks, and arbitrary LLM-generated variants are not supported.
- Git submodules and Git LFS materialization are not supported in 0.1. Safe in-workspace symbolic links require Windows symbolic-link support; links that resolve outside the Run workspace are rejected.
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
- Workspace cleanup is explicit so a user can inspect a completed attempt. Until cleanup, isolated working directories, shallow Git state, and simulator snapshots consume disk space.
- A validator command is user-supplied and runs inside the selected Docker image with the Agent workspace mounted read-only. Baseline repository tests remain visible to Codex; this preview is not a hidden-test service.
- Git metadata is outside the Codex writable workspace. Read-only commands such as status and diff are supported; tasks must not require Codex to create a real local commit.

## Packaging

- The release archive installs Python and Node dependencies from their normal package registries; it is not an air-gapped dependency bundle.
- The plugin is registered from the extracted checkout. Moving or deleting that folder before uninstalling can require `-Repair` or manual Codex marketplace cleanup.
- Ordinary user-owned platform acceptance and authenticated Codex task evidence are required before the preview is called stable. Hosted macOS lifecycle evidence is not a physical-machine substitute.
