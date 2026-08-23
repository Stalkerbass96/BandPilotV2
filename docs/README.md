# BandPilot documentation

The documentation set has one current source for each kind of decision. This
index defines authority; it prevents historical PRDs and completion snapshots
from becoming accidental requirements.

## Active documents

| Document | Authority |
|---|---|
| [`../README.md`](../README.md) | Repository entry point, setup and quality commands. |
| [`PRODUCT.md`](./PRODUCT.md) | Product goals, user journey, scope, invariants and success metrics. |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | Current ownership, data flow, contracts and technical boundaries. |
| [`DEVELOPMENT.md`](./DEVELOPMENT.md) | Mandatory change workflow, development rules and definition of done. |
| [`ROADMAP.md`](./ROADMAP.md) | Current baseline, next priorities, metric gates and deferred work. |

## Authority order

When documents disagree:

1. Executable code, migrations and tests describe actual behavior.
2. The active documents above define intended current behavior and process.
3. Accepted task/issue criteria may define a scoped change to those documents.
4. Files under `archive/` are historical evidence only.

Fix a discovered disagreement in the same change. Do not add another PRD or
`v4` document; update the one active owner document and record durable design
context in code/tests or a narrowly scoped ADR if one is later introduced.

## Archive

[`archive/README.md`](./archive/README.md) indexes the original FretPilot,
StickPilot, frontend, stream-separation, learning-loop and Phase 0–7 records.
They retain useful investigation and decision history, but their status tables,
file lists, test counts, schedules and open questions are not current.

## Documentation maintenance

- Product behavior changes update `PRODUCT.md`.
- Ownership, data flow, schema or operational changes update `ARCHITECTURE.md`.
- Engineering policy or quality-gate changes update `DEVELOPMENT.md`.
- Priority, baseline or milestone acceptance changes update `ROADMAP.md`.
- Setup and public capability changes update the root `README.md`.
- Archived documents are immutable except to repair an archive link or add a
  factual archival note.
- Do not include API keys, private corpus paths, user-specific absolute paths or
  volatile generated artifact names in documentation.
