# BandPilot architecture

This document is the current architecture source of truth. It distinguishes the
implemented baseline from the target cloud-editor architecture. Historical
implementation proposals remain under `docs/archive/`.

## 1. Architecture decision

BandPilot is evolving from a repair pipeline with a read-only score preview into
a server-authoritative collaborative score editor. The first single-user editor
slice is implemented; collaboration and proposal workflows remain ahead.

The central decision is:

> Manual edits, import repair, humanization and LLM edits all become typed,
> validated score transactions against one canonical, versioned document.

Neither AlphaTab objects, Guitar Pro files, MusicXML files, LLM responses nor a
generic CRDT document may become a second editable score truth.

## 2. Current implemented baseline

```text
React import/preparation/editor/export UI
  -> FastAPI authentication and project routes
  -> ScoreDocument command service
       -> immutable revisions + snapshots + command ledger
       -> conflict/precondition validation + compensating undo
  -> RepairService / BandPilotOrchestrator
  -> instrument plugin registry
       -> guitar / drum / bass / keys / generic pipelines
  -> working IR adapters
  -> SongIR 2.0 compatibility artifact
  -> prepared ScoreDocument revision
  -> hard validation
  -> revision-pinned GP5 export (legacy exports remain available)
  -> strict ScoreDocument-to-AlphaTab editor adapter
```

The existing engine remains in service during migration. ScoreDocument 3.0 is
now the persisted editor truth, with rational time, stable identity, revision
hashes, typed note/beat operations, copy/cut/paste and undo. Project ownership is still
single-user; range editing, complete notation operations, comments, presence,
roles and real-time collaboration remain target capabilities.

The temporary preparation bridge is deliberately narrow: MIDI upload creates a
truthful raw revision zero; the first completed repair may promote SongIR into
one whole-document `repair` revision only while raw revision zero is untouched.
That revision carries a global conflict fence. A repair may never overwrite a
manually edited history. E2 replaces this bridge with a visible Apply/Reject
proposal made of typed musical operations.

## 3. Target system shape

```text
React editor shell
  ├─ local selection, keyboard commands and optimistic projection
  ├─ renderer/player adapter (AlphaTab first)
  ├─ collaboration client and ephemeral presence
  └─ task/proposal/export panels
          │ REST + authenticated WebSocket
          ▼
FastAPI application boundary
  ├─ Project / membership / invitation service
  ├─ Score command service ──> validator ──> revision store
  ├─ Collaboration gateway ──> accepted command broadcast
  ├─ Proposal service
  │    ├─ repair and instrument engines
  │    ├─ LLM edit planner
  │    └─ deterministic resolver + validator
  ├─ Export service ──> validated revision ──> exporters
  └─ Durable task service ──> recoverable workers
          │
          ├─ PostgreSQL: documents, commands, revisions, members, audit
          ├─ object storage: MIDI, snapshots, exports and manifests
          └─ ephemeral store/pub-sub: presence, fan-out and task coordination

Governed corpus
  -> ingest and rights checks
  -> candidate knowledge snapshot
  -> independent A/B gates
  -> explicit promotion or rollback
```

The score command service is the only write boundary for committed musical
state. Services may calculate proposals in parallel, but they commit only
through this boundary.

## 4. Repository ownership

Current packages remain valid. Target packages are introduced milestone by
milestone, not as a parallel rewrite.

| Area | Responsibility |
|---|---|
| `backend/src/fretpilot/api` | Authentication, permissions, transport validation and error mapping. |
| `backend/src/fretpilot/services` | Application workflows: project, command, proposal, task and export. |
| `backend/src/fretpilot/editor` | ScoreDocument, typed operations, transactions, rebasing and undo. |
| `backend/src/fretpilot/collaboration` (target) | WebSocket sessions, accepted-command fan-out and ephemeral presence. |
| `backend/src/fretpilot/orchestrator` | Instrument classification and repair proposal orchestration. |
| `backend/src/fretpilot/engine` | Deterministic repair, realization and performance stages. |
| `backend/src/fretpilot/ir` | SongIR 2.0 compatibility and ScoreDocument 3.0 adapters/serialization. |
| `backend/src/fretpilot/validation` | Independent notation, physical and transaction invariants. |
| `backend/src/fretpilot/exporters` | Read-only serialization from a pinned validated revision. |
| `backend/src/fretpilot/knowledge` | Immutable seed assets, promoted snapshots and deterministic queries. |
| `backend/src/fretpilot/elearning` | Corpus ingest, alignment, evaluation and governed candidates. |
| `backend/src/fretpilot/ai` | BYOK providers and typed proposal planning; no document persistence. |
| `frontend/src/editor` | Strict renderer projection, stable identity mapping, beat-edit helpers and contextual editor controls. |
| `frontend/src/components` | Reusable product UI without musical business rules. |
| `frontend/src/api` | Generated/typed REST and WebSocket contracts. |

Modules may be added only when the milestone activates their responsibility.
An empty framework or duplicate old/new business path is not progress.

## 5. Canonical document model

### ScoreDocument 3.0

ScoreDocument 3.0 is the target editable snapshot. It retains the separation
that made SongIR useful while adding editor identity and exact time:

- score metadata, ordered tracks, staves, measures, voices, beats/events and
  notes;
- stable opaque IDs for every editable entity;
- exact rational musical positions and durations, normalized at boundaries;
- instrument realization such as tuning, capo, string/fret, drum piece, hand
  and fingering;
- notated techniques, expressions, structural directions and layout intent;
- a separate performance layer for timing, gate, velocity and controls;
- immutable source provenance and unresolved source events;
- validation state, reproducibility pins and traceable transformations.

Rational time is serialized as a normalized numerator/denominator pair. Float
seconds and MIDI ticks may be derived at import/playback boundaries but cannot
identify an edit location.

### Snapshot and history

The authoritative history consists of:

1. accepted typed transactions in revision order;
2. periodic immutable ScoreDocument snapshots for fast loading;
3. a content hash for every committed revision.

The current document is a projection of that history. A snapshot is not another
truth, and a command is never marked accepted before its state and revision are
durably committed.

### SongIR 2.0 migration

SongIR 2.0 remains the implemented compatibility contract during migration:

1. freeze representative SongIR 2.0 fixtures and exporter results;
2. implement a deterministic SongIR 2.0 -> ScoreDocument 3.0 adapter (done);
3. create raw/blank revision zero and promote the first untouched prepared
   result into revision history (done for the E1-A bridge);
4. move validation and exporters to ScoreDocument 3.0 behind compatibility
   adapters (typed edit validation and pinned GP5/MusicXML/humanized MIDI paths
   done; Eclipse remains on the compatibility path);
5. remove the old SongIR write path only after fixture, migration and export
   equivalence gates pass.

A long-lived dual-write scheme is forbidden. If a migration step temporarily
writes both forms, one is explicitly derived, hash-checked and has a removal
milestone.

## 6. Typed command protocol

### Transaction envelope

```text
ScoreTransaction
  command_id          client-generated idempotency key
  document_id
  actor_id
  base_revision
  origin              manual | import | repair | humanize | ai | migration
  intent              user-readable action name
  selection_anchor
  operations[]
  preconditions[]
  inverse_metadata
  created_at
```

Operations are a closed, versioned union. Initial families include:

- insert/update/delete note or rest;
- set pitch, duration, voice, string/fret, drum piece or technique;
- insert/delete/update beat and measure;
- paste/move a range;
- set track, tuning, capo, staff, mixer or score metadata;
- add/update/resolve an anchored annotation;
- update performance events or select a humanization profile.

The implemented E1 command subset includes beat insert/delete/duration/voice,
dot/triplet duration transforms, paired tie endpoints, beat dynamics,
performance velocity, individual note add/delete/pitch/realization, aligned
all-track measure-group insert/delete, and technique add/delete with
bidirectional references and deterministic inverse operations. Tie commands
require adjacent pitched beats in the same staff/voice lane and are submitted
as one atomic endpoint pair. A dynamic command updates the notation mark and
each selected note's performance velocity in the same transaction.
Track operations create a fully aligned empty timeline, delete only empty
tracks, reorder the complete stable-ID set, and update name, instrument,
notation mode or normalized mixer state. Tuning/capo UI transactions preserve
pitch by recomputing every affected fret and fail atomically if any note would
become unplayable. Inferred default track-extension fields are omitted from
canonical 3.0 snapshots but expanded in API responses, preserving historical
revision hashes without giving clients ambiguous state. Measure-group operations shift notation,
performance, tempo and time-signature positions together and cannot delete the
last score measure. Deleting the final note converts the beat to an explicit
rest; typing into a rest adds a note plus its performance event. Copy, cut and
paste are same-track typed operations; cut captures the beat in the editor
clipboard and deletes it as one revision, so undo restores the musical event
while preserving paste availability. Range and measure edits are composed into
one atomic transaction rather than persisted as partial UI mutations.

No API accepts an arbitrary JSON patch to the score document.

### Acceptance algorithm

The server processes one transaction atomically:

1. authenticate the actor and authorize the project role;
2. return the prior result when `command_id` is already accepted;
3. load the current revision and check base revision and preconditions;
4. rebase only operations whose stable targets and fields do not conflict;
5. apply operations to an isolated document;
6. run schema, rhythm, reference, physical-playability and export-critical
   validation;
7. persist transaction, resulting revision hash, audit metadata and snapshot
   when due in one database transaction;
8. acknowledge the origin client and broadcast the accepted transaction.

Accepted commands are deterministic for the same base revision and inputs.
Validation warnings may be committed when policy permits; hard errors cannot.

### Conflict and undo semantics

- Concurrent commands on disjoint entities or fields can rebase.
- Delete-versus-edit, incompatible structural edits and two writes to the same
  protected field return an explicit conflict. The client never pretends that
  silent last-writer-wins succeeded.
- Undo creates a compensating transaction against the current revision using
  the original transaction's inverse metadata and preconditions.
- One UI action, repair proposal or AI proposal is one transaction and one undo
  step, even when it contains many operations.
- Redo reissues the semantic transaction with new revision checks; it does not
  restore an old database pointer.

## 7. Editor rendering boundary

AlphaTab remains the first renderer/player candidate because the current client
already uses it and it exposes score rendering, playback hooks, notation bounds
and selection-related events. BandPilot must still implement editing behavior.

The adapter boundary is:

```text
ScoreDocument projection
  -> AlphaTab model/view
  -> rendered bounds mapped back to stable BandPilot IDs
  -> user gesture becomes a typed BandPilot transaction
  -> accepted document projection is rendered again
```

AlphaTab model object identity never appears in persisted commands. GP5 is not
generated merely to render an editing session.

Before committing to the renderer for the complete editor, a time-boxed spike
must prove:

- caret and range hit testing on standard notation, TAB, five-line drums and
  keyboard grand staff;
- direct note/rest input and duration/pitch/string changes;
- partial or sufficiently fast rerender, scroll/caret stability and playback
  synchronization on a representative 100+ measure multi-track score;
- visual representation of required techniques and two drum voices;
- deterministic mapping between renderer bounds and stable document IDs;
- licensing and redistribution compatibility.

If the spike fails, the renderer is replaceable behind this adapter. Replacing
the canonical document or command protocol is not an acceptable workaround.

## 8. Collaboration architecture

### Server-authoritative score, ephemeral presence

The first release is online-first. WebSocket sessions carry:

- accepted score transactions and revision acknowledgements;
- presence, viewport, caret and selection awareness;
- task/proposal status and comment notifications.

Presence is not persisted. Score commands, comments, roles, invitations,
versions and audit events are persisted.

CRDT technology such as Yjs may support presence, client replicas, reconnect
transport or text fields after a spike. Raw CRDT updates may not bypass typed
musical commands, permission checks or hard validation. This hybrid preserves
the useful convergence properties of collaborative tooling without allowing a
temporarily converged but musically invalid score to become authoritative.

### Connection lifecycle

1. The client loads a snapshot plus current revision and opens an authenticated
   document channel.
2. It may optimistically project a local command, visibly marked unsaved.
3. The server accepts/rebases/rejects the command and broadcasts the result.
4. On reconnect the client sends its last accepted revision and command IDs;
   the server supplies missing transactions or a newer snapshot.
5. Commands that were never accepted remain local and are retried only with
   idempotency and explicit conflict handling.

### Permission model

- `owner`: membership, project deletion, editor rights and export policy;
- `editor`: score commands, comments, tasks, proposals and allowed exports;
- `commenter`: comments, playback and proposal review without score mutation;
- `viewer`: read/play and optionally export.

REST and WebSocket entry points enforce the same policy. Removing access closes
active sessions. Invitation tokens are single-purpose, expiring and
non-enumerable.

## 9. Proposal architecture

Repair and LLM work share a proposal lifecycle:

```text
selection + pinned base revision + intent
  -> durable task
  -> candidate operations
  -> deterministic resolution on isolated document
  -> hard validation
  -> semantic/visual diff + optional A/B performance
  -> Apply as one ScoreTransaction | Reject with no mutation
```

### Repair and humanization

- Import stores the source and creates a raw editable revision.
- “Prepare score” runs the existing orchestrator and instrument plugins, then
  converts the resulting delta into typed operations.
- Guitar, bass, drums, keys and generic plugins retain ownership of physical or
  notation realization.
- Humanization normally changes performance events/profile pins. It changes
  visible notation only when the user invokes an explicit notation command.
- Proposal work may run asynchronously, but applying it must use the same
  command service as manual editing.

### LLM edit proposal

The LLM receives a bounded, typed context:

- selected stable IDs and exact range;
- relevant measures before/after for continuity;
- current instrument, tuning, playable range and product mode;
- applicable promoted knowledge and validation constraints;
- an operation JSON schema and supported intent vocabulary.

It returns an `EditProposal` containing summary, typed candidate operations,
assumptions and confidence. It never returns executable code or persists state.
Deterministic resolvers compute exact voicing, fingering and notation details
when a semantic intent is underspecified.

All attempts record provider/model, prompt/schema version, request fingerprint,
base revision, latency, outcome and validation result without logging secrets.
Provider timeout or failure leaves the editor available and the score unchanged.

## 10. Instrument and validation contracts

Each family owns its physical or notation realization:

- **Guitar:** quantization, stream separation, tuning, phrase fingering and
  articulation assembly.
- **Drums:** onset-gap quantization, deterministic GM mapping, pattern,
  velocity, sticking and standard two-voice notation. MIDI note-off gates do
  not create ties or bar-spanning written durations; performance gates remain
  in the performance layer.
- **Bass:** tuning-aware phrase position and chord realization with bass priors.
- **Keys:** quantization, hand partition, fingers, voices and grand-staff
  semantics.
- **Generic:** pitch/timing-preserving standard notation without fabricated
  physical techniques.

Independent validation checks measure/rational bounds, timing, voices, stable
references, physical mappings, collisions, hand span, keyboard hands/fingers,
drum pieces/voices and linked techniques. Transaction validation additionally
checks referential integrity and operation preconditions.

A new family requires a plugin, typed realization, ScoreDocument adapter,
validator, editor palette, fixtures and exporter policy.

## 11. Export contracts

Every export pins document revision/hash, exporter version, knowledge snapshot,
performance profile and compatibility result. Exporters are read-only.

### GP5

- Guitar/bass use real tuning and string/fret realization.
- Drums use a notation-only five-line percussion track on GM channel 10. Voice
  1 carries hands/cymbals and voice 2 carries feet for conventional stem
  separation; exact source GM pitch variants are preserved.
- Keys/generic use the existing pitch-preserving compatibility view; MusicXML
  remains preferred for native grand staff.
- Pitched tracks use 4–7 serialization strings because Guitar Pro 8 rejects
  fewer than four.
- Any used voice 2 remains continuous through rest-only and padded measures for
  AlphaTab compatibility.

GP5 release gates include PyGuitarPro structural round-trip, AlphaTab import and
a real Guitar Pro smoke test. A writer parsing its own output is insufficient.

### MusicXML and MIDI

MusicXML represents native staves, voices, technical data and percussion
notation, and remains an interchange format rather than storage. Humanized MIDI
derives a performance view from the pinned revision/profile. Eclipse mapping is
applied after performance selection and never mutates the score.

## 12. Persistence and operational target

### Target transport surface

The first target contract families are:

| Transport | Purpose |
|---|---|
| `GET /api/projects/{id}/document?revision=` | Load a verified snapshot and current revision metadata. |
| `POST /api/projects/{id}/commands` | Submit one idempotent ScoreTransaction. |
| `GET /api/projects/{id}/commands?after=` | Catch up accepted transactions when WebSocket is unavailable. |
| `POST /api/projects/{id}/tasks/prepare` | Start a repair/make-playable proposal against a pinned revision. |
| `POST /api/projects/{id}/ai-proposals` | Start a selected-range AI proposal. |
| `POST /api/projects/{id}/proposals/{proposal_id}/apply` | Revalidate and commit the proposal as one transaction. |
| `POST /api/projects/{id}/proposals/{proposal_id}/reject` | Record rejection without score mutation. |
| `POST /api/projects/{id}/invitations` | Invite a project member with a bounded role. |
| `WS /api/projects/{id}/collaboration` | Revision acknowledgements, accepted commands, tasks and presence. |

OpenAPI and WebSocket messages use one shared schema package. Expected domain
errors include `revision_conflict`, `validation_failed`, `proposal_stale`,
`permission_denied`, `task_not_ready` and `unsupported_operation`; clients do
not infer these states from free-form messages. Existing repair/export routes
remain compatibility adapters through E2.

Legacy repair statuses map without changing their current meaning:

- `processing` -> target task `queued` or `running`;
- `repaired` -> `succeeded` after its validated result is durable;
- `partial` -> `partial` with explicit unresolved tracks/events;
- `failed` -> `failed` when no acceptable result exists.

`needs_review` is new and is used when a proposal exists but has not been
applied. Compatibility routes may continue to expose `repaired` for that
artifact while the editor exposes the proposal decision separately.

### Data model

The target relational model adds:

- `project_members` and `project_invitations`;
- `score_documents`, `score_revisions`, `score_snapshots` and
  `score_commands`;
- `comment_threads` and `comments`;
- `tasks`, `proposal_attempts`, `edit_proposals` and proposal decisions;
- exports pinned to `revision_id` and `revision_hash`;
- audit events for access and committed mutations.

Project membership is the initial product boundary. A nullable/workspace-ready
ownership key may be introduced, but a second authorization hierarchy is not
activated before it has product behavior and tests.

### Infrastructure

- SQLite and local artifact files remain supported for local development and
  single-user migration tests.
- Production collaboration requires PostgreSQL for transactions and locking,
  durable object storage for sources/snapshots/exports, recoverable workers and
  a supported pub-sub/ephemeral store for multi-instance fan-out.
- The exact queue/pub-sub vendor is an implementation decision made through a
  deployment spike; application contracts must not depend on it.
- Writes visible to readers are atomic. Commands and revision metadata commit
  transactionally; large artifacts become visible only after hash verification.

## 13. Security and privacy

- Project access is membership-scoped in every API, WebSocket and artifact URL.
- Production startup fails without non-default JWT and encryption keys.
- BYOK secrets are encrypted, never broadcast and usable only by their owner.
- LLM destinations are validated against SSRF before and after DNS resolution;
  calls use bounded timeout, disabled redirects and no inherited proxy trust.
- Prompts contain only the selected score context required for the operation.
- Upload/archive size and member counts are bounded and validated.
- Presence and telemetry exclude score content by default.
- User-facing errors never expose provider responses, secrets or internal paths.
- Tests do not call real LLMs or private corpora by default.

## 14. Learning governance

Professional reference files retain tracks, tuning, capo, voices, ties and
techniques. Ingest requires content hash, rights identifier, permission, review
tier and leakage-safe split. The drum learner additionally records written
duration, two-voice use and foot-voice agreement.

Learning writes immutable candidate snapshots. Promotion requires an independent
corpus, minimum evidence and deterministic no-regression gates. The packaged
seed remains immutable and every provenance ID is declared in
`knowledge/assets/source_catalog.json`.

The public GuitarSet baseline retains its performer-disjoint split and CC BY 4.0
attribution. The user-supplied GTP archive remains private evaluation material
until explicit rights and split metadata authorize aggregate learning.

Promoting knowledge never changes an already committed score revision. A user
must rerun a tool to create a new proposal with the newer snapshot.

## 15. Observability and service objectives

Telemetry follows durable states rather than simulated progress. Initial editor
objectives, ratified with measured baselines before release, are:

- local command feedback within 50 ms for routine note edits;
- accepted-command acknowledgement within 500 ms p95 in the primary region;
- collaborator propagation within 250 ms p95 after server acceptance;
- no loss of acknowledged commands across refresh, reconnect or worker restart;
- deterministic export reproduction from revision hash and pinned versions;
- task states, proposal attempts, validation failures and conflicts observable
  without logging score content or secrets.

Large-score render and collaboration limits are established by the editor spike
and recorded as explicit supported limits, not left undefined.

## 16. Migration gates and rollback

- Database changes are forward Alembic migrations with tested upgrade from the
  current schema and a documented rollback/roll-forward plan.
- Existing project routes remain functional behind adapters until the new editor
  completes export equivalence and adoption telemetry.
- Feature flags gate ScoreDocument writes, collaborative sessions and AI Apply
  separately. A flag disables new writes without invalidating committed data.
- Every milestone includes fixture migration, API contract tests, renderer
  checks and one real end-to-end project.
- No milestone deletes source MIDI, SongIR artifacts or old exports.

## 17. Decision evidence

- Guitar Pro's official feature guide demonstrates the expected workflow depth:
  beat-level design controls, stylesheet options, nested tuplets, piano
  fingering/pedal, command palette and playback/practice tools:
  <https://www.guitar-pro.com/c/10-guitar-pro-new-features>
- AlphaTab exposes rendering/player APIs and notation-bound lookup suitable for
  an adapter spike: <https://docs.alphatab.net/docs/reference/types/alphatabapi/>
- Yjs documents convergent shared types, awareness and offline collaboration;
  BandPilot limits any use to a layer that cannot bypass musical commands:
  <https://github.com/yjs/yjs>
- MusicXML is an open interchange/archival format, supporting the decision to
  keep it at the import/export boundary:
  <https://www.w3.org/2021/06/musicxml40/>
