# RunCase Interchange integration

Workflow Environment Factory depends on [RunCase Interchange](https://github.com/rrrrrredy/runcase-interchange) 0.1.2 for three document types:

- `workflow.case.v1`: one generated task, environment/reset contract, allowed tools, objective validators, provenance, and safety limits;
- `workflow.score.v1`: one Run's execution status, task result, validator evidence, resource use, and nondeterminism statement;
- `agent.run.v1`: the shared Run envelope used for future cross-product import/export.

The product validates Case and Score documents against the JSON Schema 2020-12 files before storing or exporting them. Release packages include those three schemas under `.runtime-deps\runcase-interchange\0.1.2\schemas` with dependency metadata. Source checkouts sync them explicitly:

```powershell
.\scripts\Sync-Protocol.ps1 -ProtocolRoot C:\path\to\runcase-interchange
```

Remote sync requires both a release URL and an exact SHA-256. An unverified download is rejected.

The Runs & Scores protocol library accepts any of the three exact v1 documents. It validates the input, redacts secret-like content, validates the redacted document again, and stores it by canonical SHA-256. Reimporting the same sanitized document is idempotent. Imported documents remain read-only evidence and do not become executable local Cases.

The Case Factory exports individual `workflow.case.v1` documents and a three-Case task pack. Runs with a completed Score can export `workflow.score.v1`. A Runtime Evolution Workbench `agent.run.v1` export can be imported into the protocol library.

## Product-specific task pack

`wef.task-pack.v1` is a small product envelope, not a shared protocol schema. It contains:

- the Blueprint ID and name;
- creation time;
- exactly three individually valid `workflow.case.v1` documents;
- a short evidence-boundary statement.

Consumers should validate every nested Case with RunCase Interchange. They must not interpret the task-pack envelope as a benchmark result or a general quality claim.

## Versioning rule

The 0.1 product accepts only the exact `*.v1` schema identifiers. A future protocol version must be added explicitly with migration and compatibility evidence; unknown schema versions fail closed.

OpenTelemetry GenAI mappings may be offered as optional adapters later. They are not the internal data model because the relevant conventions continue to evolve and do not cover this product's provenance and reset contract.
