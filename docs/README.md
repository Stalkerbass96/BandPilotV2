# BandPilot documentation

The documentation set has one current source for each kind of decision. This
index defines authority; it prevents historical PRDs and completion snapshots
from becoming accidental requirements.

## Consolidated status (2026-08-28)

| Question | Current answer | Owner |
|---|---|---|
| What is the product? | A desktop-first, Guitar Pro-class browser score editor with MIDI repair, reversible musical intelligence, collaboration and selection-based AI proposals. | [`PRODUCT.md`](./PRODUCT.md) |
| What is the source of musical truth? | Versioned `ScoreDocument` 3.0 snapshots and typed, validated transactions; renderer objects, SongIR, GP5, MusicXML and LLM output are derived. | [`ARCHITECTURE.md`](./ARCHITECTURE.md) |
| What works now? | MIDI/blank-score entry, five-family score preparation, single-user AlphaTab editing, same-track copy/cut/paste, undo/redo, playback practice controls, page/horizontal layout and revision-pinned exports. | [`ROADMAP.md`](./ROADMAP.md) |
| What is next? | Finish E1 release-latency qualification and professional notation depth, then move repair/humanization into reviewable editor proposals (E2). | [`ROADMAP.md`](./ROADMAP.md) |
| How do changes land? | Contract-first, one typed write boundary, focused vertical slices, real boundary tests, updated owner docs and a complete definition-of-done review. | [`DEVELOPMENT.md`](./DEVELOPMENT.md) |

This table is the short operational summary. Detailed behavior, architecture,
acceptance criteria and evidence remain in the linked owner documents; do not
copy this status into another planning file.

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

## Technical evidence

Files under `evidence/` record repeatable spike or release measurements. They
may support an active decision but do not own product scope or architecture.
Current evidence includes the
[`AlphaTab editor spike`](./evidence/alphatab-editor-spike.md).
- Do not include API keys, private corpus paths, user-specific absolute paths or
  volatile generated artifact names in documentation.
