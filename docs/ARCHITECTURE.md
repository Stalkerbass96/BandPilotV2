# BandPilot architecture

This is the current architecture source of truth. Historical implementation
proposals and diagrams are archived under `docs/archive/`.

## 1. System shape

```text
React application
  -> FastAPI transport and authentication
  -> RepairService
  -> BandPilotOrchestrator
  -> instrument plugin registry
       -> Guitar pipeline
       -> Drum pipeline
       -> Bass pipeline
       -> Keys pipeline
       -> Generic pitched pipeline
  -> working-IR adapters
  -> SongIR 2.0
  -> hard validation
  -> exporter registry
       -> GP5
       -> MusicXML
       -> humanized band MIDI
       -> Ample Eclipse MIDI

Authorized GP corpus
  -> full-score reader and GP-to-MIDI conversion
  -> the same product repair/export path
  -> reference/generated alignment and metrics
  -> candidate knowledge snapshot
  -> independent A/B gate
  -> explicit promotion or rollback

Rights-clear public annotations (GuitarSet)
  -> performer-disjoint train / validation / test split
  -> per-file string, fret, transition and chord aggregation
  -> absolute shapes + transposition-invariant templates
  -> safe-default versus candidate fingering A/B on held-out performers
  -> source-catalog validation
  -> only non-regressing priors become active
```

The dependency direction is one-way. Routes do not implement musical stages;
exporters do not repair score semantics; learning cannot mutate packaged seed
knowledge or bypass promotion governance.

## 2. Repository ownership

| Area | Owner responsibility |
|---|---|
| `backend/src/fretpilot/api` | Authentication, request/response validation, transactions and HTTP error mapping. |
| `backend/src/fretpilot/services` | One application-facing repair workflow and artifact persistence. |
| `backend/src/fretpilot/orchestrator` | Track classification, user overrides, plugin routing and result aggregation. |
| `backend/src/fretpilot/engine` | Guitar, drum and pitched repair stages plus preprocessing. |
| `backend/src/fretpilot/ir` | Working IRs, canonical SongIR and strict serializers/adapters. |
| `backend/src/fretpilot/validation` | Independent professional-score invariants. |
| `backend/src/fretpilot/exporters` | Read-only format serialization. |
| `backend/src/fretpilot/knowledge` | Immutable seed assets, runtime snapshots and deterministic queries. |
| `backend/src/fretpilot/elearning` | Corpus ingest, conversion, alignment, evaluation and governed candidates. |
| `backend/src/fretpilot/ai` | BYOK provider boundary and bounded decision proposals. |
| `frontend/src/pages` | Product workflows; no duplicated musical business logic. |
| `frontend/src/api` | Typed transport client and job polling. |

## 3. Repair lifecycle

1. Import validates size and parses the MIDI while preserving physical tracks,
   channels, programs, absolute ticks, tempo and time signatures.
2. Detection classifies every note-bearing track. User family corrections are
   persisted and override later automatic classification.
3. `POST /api/projects/{id}/repair-async` creates a durable `repair_jobs` row
   and returns HTTP 202 with a job ID.
4. The background runner opens a new database session and calls the same
   `RepairService` used by the synchronous compatibility endpoint.
5. Guitar preprocessing performs cleanup, tuning selection and optional
   policy-bounded LLM advice. Other families use their registered plugin.
6. Working results are adapted once into SongIR, then independently validated.
7. JSON artifacts and their manifest are written atomically. The terminal job
   stores its typed result or explicit error; the project status is updated.
8. The frontend polls the job, survives page refresh and restores the report,
   latest export and preview from durable state.

Client timeout is not cancellation. Duplicate active jobs for one project are
rejected. The current runner is in-process, so process-crash recovery is a
known operational boundary.

## 4. Score contracts

### SongIR 2.0

`song_ir.json` separates:

- immutable source metadata and source-track identity;
- analysis, family assignments and unresolved source events;
- notation events and instrument realization;
- explicit technique relations;
- performance timing, velocity and controls;
- validation status and issues;
- reproducibility pins and traceable transformations.

Stable track-scoped note IDs connect score, performance, technique and source
layers. Unsupported major schema versions are rejected rather than guessed.

### Working IRs

Guitar, drum and pitched working IRs exist to keep pipelines focused. They are
transient implementation contracts and may be adapted at legacy export
boundaries, but they are not a second persisted score truth.

### Validation boundary

Validation independently checks measure bounds, timing, voices, IDs,
performance mapping, guitar/bass pitch-string-fret truth, collisions, spans,
keyboard hands/fingers, drum pieces and linked techniques. A hard error blocks
strict export.

## 5. Instrument plugins

Each instrument family owns its physical or notation realization:

- Guitar: eight stages from quantization through stream separation, phrase
  fingering and articulation assembly.
- Drums: quantization, measure split, GM piece mapping, pattern, velocity,
  sticking, notation and assembly.
- Bass: tuning-aware phrase position and chord realization with bass priors.
- Keys: quantization, hand partition, fingers, voices and grand-staff semantics.
- Generic: pitch- and timing-preserving standard notation without fabricated
  physical technique.

A new family requires a plugin, typed working result, SongIR adapter, validator,
fixtures, exporter policy and user-visible capability rule.

## 6. LLM boundary

The OpenAI-compatible BYOK adapter currently supports style classification and
bounded rewrite proposals. Requests use a configured timeout, validated public
base URL, disabled redirects and no environment proxy trust. Provider failures
degrade to deterministic behavior and are recorded.

The LLM cannot directly mutate MIDI or SongIR. Deterministic policy validates
operation type, index, count and target pitch before any allowed transformation
is applied. `faithful` mode never applies LLM note rewrites.

## 7. Export contracts

Every exporter validates SongIR before serialization and reports the real
format, note count, measure count and warnings.

### GP5

- Guitar and bass use real tuning/string/fret realization.
- Drums use distinct virtual serialization slots for simultaneous hits.
- Keys/generic tracks use a pitch-preserving virtual-string view; MusicXML is
  preferred for native grand staff.
- Pitched GP5 tracks use 4–7 serialization strings because Guitar Pro 8 rejects
  fewer than four even when PyGuitarPro can parse the file.
- A track that uses voice 2 has a continuous voice 2, including rest-only and
  padded measures, because AlphaTab requires cross-measure voice continuity.
- Unicode metadata outside GP5's legacy encoding degrades safely with a
  warning; MusicXML preserves it.

Compatibility must be tested at three levels: PyGuitarPro structural
round-trip, AlphaTab import, and a real Guitar Pro smoke test for release
candidates. Passing only the writer's own parser is insufficient.

### MusicXML and MIDI

MusicXML represents native parts, staves, voices, technical data and percussion
notation. Humanized MIDI derives a temporary performance view using a versioned
profile. Eclipse exporters apply instrument mappings after performance
selection and never mutate SongIR.

## 8. Persistence and reproducibility

- SQLite is the current store; schema changes use Alembic revisions.
- User BYOK values are encrypted with a configured Fernet master key.
- Project artifacts live below the configured job root by user/project.
- Writes visible to readers are atomic.
- `artifact_manifest.json` pins hashes, application/schema/knowledge versions,
  model/prompt identity, settings and validation state.
- `repair_manifest.json` records per-track completion, warning and failure.
- Runtime knowledge lives in the configured knowledge store; packaged assets
  are immutable bootstrap seeds.

## 9. Learning governance

Professional GP files retain tracks, tuning, capo, voices, ties and explicit
techniques. Ingest requires content hash, rights identifier, permission,
review tier and dataset split. Duplicate content across train/validation/test
is rejected.

Learning writes an immutable candidate snapshot. Promotion requires an
independent corpus, minimum evidence and deterministic no-regression gates.
Rollback can restore a promoted snapshot but cannot activate an unevaluated
candidate.

`knowledge/assets/source_catalog.json` is the provenance authority. Runtime
entries store stable IDs only; the registry rejects unknown IDs and local
paths. Empirical or derived entries additionally require a rights-verified
source that permits aggregate derivation. URLs, licence terms, attribution and
artifact hashes remain in the catalogue rather than being copied into every
entry.

The first public guitar baseline is GuitarSet under CC BY 4.0. Its split is
frozen by performer: `00`–`03` train, `04` validation and `05` test. Statistics
and transitions are accumulated per excerpt before aggregation, so identical
measure/beat coordinates in different songs can never form false chords or
cross-song position changes. Only aggregate priors and top chord patterns are
packaged.

Every style-role profile is compared with the generic safe fallback through
the real fingering stage. A profile is active only when exact string/fret
agreement is non-regressing on both validation and frozen test performers.
Failed profiles remain inspectable candidates in the snapshot but normal
runtime queries exclude them.

The user-supplied GTP archive remains a private evaluation corpus. The package
contains only a hash-keyed, title-free coverage inventory. It cannot contribute
active priors until explicit rights, review tier and leakage-safe split metadata
pass the existing promotion gate.

## 10. Security boundary

- Production startup fails without a non-default JWT secret and master key.
- API access is ownership-scoped; global knowledge mutation is admin-only.
- Upload size and archive members are bounded and validated.
- LLM URLs are checked against unsafe destinations before requests and after
  DNS resolution; redirects are disabled.
- Secrets, provider responses and internal absolute paths are not returned in
  user-facing errors.
- Tests never call a real LLM or require a private corpus by default.

## 11. Known architecture debt

- In-process background execution lacks crash recovery, cancellation and worker
  isolation.
- Export compatibility has manual GP8 coverage; AlphaTab cross-parser coverage
  should become a stable automated release gate.
- Per-track tuning/capo confidence is not yet a first-class SongIR decision.
- LLM calls lack a durable attempt ledger, response cache and provider circuit
  breaker.
- The frontend production bundle is large because AlphaTab is eagerly bundled;
  route/component lazy loading is not yet applied.
