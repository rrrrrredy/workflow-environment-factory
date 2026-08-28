# Release evidence

This directory accepts only sanitized evidence produced by `scripts/Prepare-ReleaseEvidence.ps1` from a clean, reviewed commit.

`workflow-product-gate-<version>.json` proves two single authenticated Codex attempts against fully synthetic inputs: one code Case and one Issue-to-PR Case. The generator excludes prompts, repository content, credentials, and local paths, and it removes the temporary plugin, marketplace, service, and product data before finalizing the file.

Do not hand-author, copy forward, or edit a gate file to make verification pass. `scripts/Verify-ReleaseEvidence.ps1` binds it to the tested commit and permits only that evidence file to change before the release tag.
