# Historical documentation archive

These files preserve product and engineering decision history. They are not
current requirements, schedules, file inventories or completion evidence.
Use the active documents in the parent directory for new work.

## Design history

| File | Historical purpose | Superseded by |
|---|---|---|
| `design/BANDPILOT_PRD.md` | Initial guitar/drum BandPilot expansion plan. | `../PRODUCT.md`, `../ARCHITECTURE.md` |
| `design/STREAM_SEPARATION_PRD.md` | Incremental guitar stream-separation requirements. | `../PRODUCT.md` |
| `design/STREAM_SEPARATION_ARCHITECTURE.md` | Planned eight-stage separation implementation. | `../ARCHITECTURE.md` and code |
| `design/PRD-learning-loop.md` | Initial GP corpus learning-loop product plan. | `../PRODUCT.md`, `../ROADMAP.md` |
| `design/ARCH-learning-loop.md` | Detailed proposed learning-loop implementation. | `../ARCHITECTURE.md` and code |
| `design/FRONTEND_PRD.md` | Original light-theme frontend redesign. | Current frontend and `../PRODUCT.md` |
| `design/FRONTEND_REDESIGN_PRD_v2.md` | Transitional dark-first proposal. | Current frontend and `../PRODUCT.md` |
| `design/FRONTEND_REDESIGN_PRD_v3.md` | Final pre-implementation visual specification. | Current frontend and `../PRODUCT.md` |
| `design/FRONTEND_ARCHITECTURE.md` | Proposed frontend tasks, types and flows. | `../ARCHITECTURE.md` and code |

The Mermaid files in `design/` accompanied those proposals and may contain
old class names or dependencies.

## Milestone snapshots

| File | Snapshot |
|---|---|
| `milestones/PHASE_0_1_COMPLETION.md` | Engineering baseline and unified repair workflow. |
| `milestones/PHASE_2_3_COMPLETION.md` | SongIR, validation, durable jobs and governed learning foundation. |
| `milestones/PHASE_4_6_COMPLETION.md` | Multi-instrument, MusicXML and humanized/Eclipse outputs. |
| `milestones/PHASE_7_GTP_ROUNDTRIP_BASELINE.md` | First 100-song full-product GP corpus baseline. |

Test counts and status statements in milestone files were correct only when
recorded. The current engineering snapshot and priorities live in
[`../ROADMAP.md`](../ROADMAP.md).
