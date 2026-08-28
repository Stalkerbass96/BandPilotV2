# BandPilot development rules

This is the mandatory working agreement for BandPilot. The upgrade must produce
one coherent professional editor, not a new UI layered over duplicate musical
state or unreviewable feature batches.

## 0. Documentation authority

- `PRODUCT.md` owns product behavior, scope and experience.
- `ARCHITECTURE.md` owns system boundaries, canonical contracts and migration.
- `ROADMAP.md` owns priority, status and milestone gates.
- This file owns implementation workflow and definition of done.
- `README.md` owns setup and public capability summaries.
- `archive/` is historical evidence, not active acceptance criteria.

Update the existing owner document. Do not create `PRD-v2`, new phase reports
or personal planning files that compete with these sources.

## 1. Non-negotiable engineering rules

- One canonical editable score document. Renderer models, GP/MusicXML files,
  SongIR compatibility objects, client caches and LLM responses are derived.
- One write boundary. Manual, repair, humanize, migration and AI changes commit
  through the typed score command service.
- One accepted user action is one understandable undo transaction.
- Stable entity IDs and exact rational score time are used across persistence,
  selection, comments, collaboration and proposals.
- Every automated change is pinned, diffable, validated, attributable and
  reversible.
- Exporters are read-only consumers of a validated pinned revision.
- No accepted command, job or export reports success before durable state and
  required validation exist.
- Existing source MIDI and historical artifacts are never overwritten by an
  editor migration.

## 2. Dependency and ownership boundaries

Target dependency direction:

```text
React editor -> typed API/WebSocket client
API -> application services -> score command service -> ScoreDocument validator
proposal services -> engine/AI/knowledge -> candidate operations -> command service
ScoreDocument revision -> exporters / renderer projection / playback projection
collaboration gateway -> permissions + accepted-command stream
learning ingest -> candidate snapshot -> A/B evaluation -> promotion
```

During migration, SongIR 2.0 adapters may sit at engine/export boundaries. They
must not become a second write path.

The E1-A first-preparation bridge is the sole temporary whole-snapshot
exception: it accepts only an untouched raw revision zero, appends an audited
`repair` command/revision with a document-wide conflict fence, and cannot run
over manual edits. Do not reuse it for repair reruns, humanization or AI;
those require E2 proposal operations and Apply/Reject.

- Routes authenticate, authorize, validate transport, open transactions and map
  typed errors. They do not implement music operations or rebasing.
- Application services own use cases, not rendering or instrument algorithms.
- The command service alone accepts persisted musical mutations.
- Instrument pipelines own physical/notation realization for their family.
- Validators are independent from both command authors and exporters.
- Frontend components render state and dispatch commands; they do not re-create
  backend fingering, drum mapping or validation policy.
- Knowledge seeds are immutable. Runtime learning writes governed snapshots.

## 3. Document and command discipline

### Contracts

- Use Pydantic/dataclass/domain types at module boundaries. A new stable payload
  cannot be an untyped dictionary.
- ScoreOperation is a closed versioned union. Adding an operation requires
  schema validation, apply, inverse/undo, conflict, permission, serialization
  and frontend dispatch tests.
- Every operation states its stable target IDs, exact positions when applicable
  and field-level preconditions.
- `command_id` is a client-generated idempotency key. Retrying the same command
  returns the same accepted/rejected outcome and never duplicates an edit.
- Canonical serialization is deterministic: normalized rational values,
  deterministic ordering and content hash tests are required.
- Unsupported major schema or command versions fail explicitly; they are never
  guessed.

### Transaction behavior

- Apply operations to an isolated document, validate, then persist command and
  revision atomically.
- Hard musical or referential errors block commit. Warnings remain typed and
  visible at anchored score locations.
- Rebase only when stable targets and protected fields are demonstrably
  disjoint. Do not use silent last-writer-wins for score content.
- Undo is a compensating transaction against current state, not a global
  revision pointer reset.
- Batch repair/AI transactions carry a semantic summary and retain one-step
  undo even when they contain many primitive operations.
- No arbitrary JSON Patch, direct ORM score mutation or renderer-model
  persistence endpoint is allowed.

### Schema migration

- ScoreDocument changes require a version decision, adapter/migration,
  canonical fixtures, hash expectation, validator tests and export tests.
- Database changes use Alembic. `create_all()` is isolated-test-only.
- A temporary dual representation declares which side is derived, how equality
  is checked and the milestone that removes it.
- Migrations are tested from a copy of the current schema with representative
  projects, source files, SongIR artifacts and exports.

## 4. Frontend editor rules

- The project route is the product workspace; do not rebuild separate repair,
  AI and export applications.
- Score selection has one typed state model used by commands, playback,
  comments and AI. Screen coordinates are translated through the renderer
  adapter and never persisted.
- Renderer-specific objects stay inside the adapter. Components use BandPilot
  IDs and command types.
- Routine note entry and navigation are keyboard-first and do not require
  opening the inspector.
- Guitar/bass numeric entry targets the active string caret, supports a short
  multi-digit fret buffer and must pass tuning/fret validation before dispatch.
  Drum, keyboard and generic input use family-aware palettes instead of
  pretending that one pitched-note interaction fits every staff.
- Every command has explicit optimistic, saving, accepted, rejected, conflict
  and offline behavior. Do not show success from a timer or assumed response.
- Autosave means accepted server commands, not merely local React state.
- Undo/redo availability comes from command history and current preconditions.
- Long operations appear as durable tasks that recover after route change,
  refresh and reconnect.
- Panels are contextual and progressively disclosed. The score remains the
  dominant workspace; technical logs are details, not default UI.
- UI strings describe user outcomes. Internal class names, schema jargon,
  provider payloads and stack traces do not enter normal product copy.
- Feature flags wrap complete vertical behavior, not dead buttons or fake
  screens.

### Accessibility and interaction testing

- Core editor commands, including copy/cut/paste, are reachable by keyboard, with visible focus and
  non-color-only state.
- Shortcuts avoid browser/OS collisions where practical and are discoverable in
  the command palette.
- Pointer hit areas, zoom and notation contrast are tested at supported browser
  scale factors.
- Remote selections remain distinguishable but never obscure the local caret or
  printed notation.

## 5. Renderer rules

- AlphaTab is a renderer/player candidate behind an adapter, not an editor
  architecture.
- Vite integration uses the official `@coderline/alphatab-vite` plugin so
  renderer assets, Web Workers and AudioWorklets stay compatible. Do not
  replace it with hand-copied fonts/soundfonts that leave playback uninitialized.
- A renderer change must preserve stable-ID hit mapping, selection, playback
  synchronization and required notation semantics.
- Do not generate GP5 on each edit merely to refresh the view.
- Keep renderer/player initialization separate from document projection.
  Accepted score commands rerender the existing AlphaTab API; they must not
  recreate the player or reload the soundfont for every edit.
- Visual correctness alone is insufficient. A notation feature must also edit,
  undo, collaborate, persist, play and round-trip through required exports.
- Performance work starts with measurement on the committed mixed-score
  fixture. Avoid caching that can show a revision different from the saved
  document.
- Renderer licenses and redistributed assets/workers/fonts are reviewed before
  production integration.

## 6. Collaboration rules

- REST and WebSocket paths use the same membership roles and authorization
  policy.
- Persist commands, comments and versions. Presence, viewport and live cursor
  awareness are ephemeral and contain no durable music truth.
- Client projection may be optimistic, but accepted revision order is
  server-authoritative.
- Reconnect sends the last accepted revision and command IDs, then receives
  missing commands or a verified snapshot.
- Access revocation closes active document sessions and invalidates artifact
  access.
- If CRDT tooling is used, raw updates may not bypass typed commands,
  validation, audit or permissions.
- Multi-instance fan-out is tested for duplicate, delayed and reordered
  delivery. Accepted commands remain idempotent.
- Offline concurrent editing is not inferred from local caching; it requires a
  separate product milestone and conflict contract.

## 7. Tasks, repair and LLM proposals

### Durable tasks

- Browser-facing long work uses start-and-resume semantics. Starting returns a
  durable task ID; refresh or disconnect does not cancel server work.
- State changes are persisted real stages, not simulated frontend percentages.
- Every failure reaches a terminal typed state; broad exception handling cannot
  report success.
- Worker retry and recovery are idempotent and cannot apply a proposal or create
  an export twice.
- Cancellation is cooperative and becomes final only when the worker
  acknowledges no commit occurred after cancellation.

### Proposal safety

- Repair, make-playable and LLM work read a pinned base revision and write a
  candidate proposal, not the live document.
- Apply rechecks base revision, permissions, preconditions and hard validation
  through the command service.
- Reject changes no score state. Stale proposals are explicitly rebased or
  regenerated; never blindly applied.
- `faithful` mode never changes source pitches through LLM rewriting.
- Humanization normally writes performance-layer operations rather than visible
  notation.

### External model calls

- External calls require authentication, bounded connect/read timeout,
  validated public destinations, disabled redirects unless reviewed, no
  inherited proxy trust and deterministic mocked tests.
- Send only selected score context plus the minimum musical neighborhood.
- Constrain output with a versioned operation schema and intent vocabulary.
- Record provider/model, prompt/schema, knowledge snapshot, request fingerprint,
  attempt result and latency. Never log keys or unnecessary score content.
- Model output is a proposal. Deterministic resolution and hard validation keep
  authority.
- Provider failure cannot block manual editing or corrupt current state.
- A user's BYOK secret cannot be used by or revealed to another collaborator.

## 8. Musical, export and knowledge rules

- Every source note is represented or explicitly unresolved. Silent deletion
  requires an explicit user-authorized creative operation.
- Guitar/bass pitch-string-fret truth, string collision, span and technique
  relation invariants are machine checked.
- Drum score time comes from onsets and notation voice; sampler note-off gates
  remain performance data. Five-line voice/stem and exact GM mapping rules are
  validated.
- A tie is one musical relation represented by paired adjacent endpoints in
  the same staff/voice lane; create/remove both endpoints in one transaction and
  validate matching pitched content before commit.
- Dynamics have two coordinated meanings: a written beat mark and note-level
  performance velocity. Editor actions update both atomically; exporters may
  quantize velocity only at a documented format boundary.
- Track creation copies only the score-wide measure/time-signature shape and
  starts with no notes; it never clones another instrument's musical content.
  Reorder commands name every stable track ID exactly once. Retuning or changing
  capo preserves written pitch by recalculating all frets in the same atomic
  transaction and rejects any unplayable result.
- Mixer state is normalized in ScoreDocument (`volume` 0..1, `pan` -1..1,
  mute/solo booleans). Renderer and exporter quantization belongs at their
  adapters, not in canonical state.
- Keyboard hands, staff, voices and fingering remain typed, not inferred only
  in an exporter.
- A new instrument family needs a plugin, typed realization, adapter,
  validator, editor palette, fixtures and exporter policy.
- A writer's own parse-back is necessary but not sufficient. GP5 changes run
  PyGuitarPro, AlphaTab and the release Guitar Pro smoke scenario.
- Corpus input requires rights, review, stable source ID and leakage-safe split.
  Paths, song names and ad-hoc bibliography strings are forbidden provenance.
- Corpus statistics are calculated within each score/track before aggregation;
  transitions or chords never cross file or split boundaries.
- Candidate knowledge is inactive until independent deterministic
  no-regression gates pass; rollback activates only a previously promoted
  snapshot.
- Promoting knowledge never rewrites an existing document revision.

## 9. Change workflow

1. Write the roadmap intake fields: outcome, acceptance, musical invariant,
   document/command impact, collaboration/permission impact, affected
   API/export/migration contracts, failure/offline behavior, fixture/metric,
   observability, non-goals, rollout and rollback.
2. Trace the existing data owner and write boundary. Delete or adapt a competing
   path before adding another one.
3. Add a failing contract or regression test for each behavior change.
4. Implement the smallest complete vertical slice. A schema-only layer without
   a caller is allowed only in the explicitly scoped E0 contract milestone.
5. Run focused tests continuously, then the required local gates.
6. Exercise the real boundary for migrations, collaboration, jobs, LLM,
   renderer and export changes.
7. Update the authoritative docs, API types, migrations, configuration and
   operational notes in the same change.
8. Review the diff for unrelated formatting, generated artifacts, secrets,
   absolute paths, duplicate state, dead flags, fake UI data and silent failure.
9. Merge only after CI and user-visible acceptance pass with recorded evidence.

Refactors and behavior changes are separate when they can be reviewed
independently. A major editor milestone is delivered through small vertical pull
requests, not one long-lived rewrite branch.

## 10. Required test matrix

### Every score operation

- schema accept/reject;
- deterministic apply and canonical hash;
- inverse/undo and redo preconditions;
- invalid target/reference;
- stale base, safe rebase and real conflict;
- permission boundary;
- serialization and refresh;
- relevant musical invariant;
- renderer projection and required export round-trip.

### Collaboration changes

- two clients on disjoint edits;
- same-field and delete/edit conflict;
- duplicate/reordered broadcast;
- reconnect/catch-up from command and snapshot;
- undo preserving another actor's work;
- role downgrade/revocation and artifact authorization;
- multi-instance behavior where applicable.

### Proposal changes

- strict mocked provider/engine output;
- invalid and out-of-selection operation;
- validation failure;
- stale proposal;
- Apply/Reject/undo;
- timeout, retry and cancellation;
- BYOK ownership and redaction.

### Migration and release fixtures

- current database -> target migration;
- current SongIR -> ScoreDocument conversion;
- mixed guitar/drum/bass/keys/generic score;
- long 100+ measure score;
- GP5 PyGuitarPro + AlphaTab automation and Guitar Pro release smoke;
- immutable source and historical artifact verification.

## 11. Local gates

Current repository gates:

```bash
cd backend
uv sync --frozen --extra dev
uv run ruff check src tests
uv run pytest --cov --cov-report=term-missing
uv build

cd ../frontend
npm ci
npm test
npm run build
```

The current editor browser gate is an in-app Browser run recorded in
`docs/evidence/alphatab-editor-spike.md`; it covers real hit testing, command
execution, persistence, rerender and playback on the 104-measure fixture. A
committed Playwright-equivalent suite is not yet present. Until that automation
lands, any editor change must include a repeatable browser-gate note in the
evidence file rather than claiming CI-level E2E coverage.

External GP corpus tests are opt-in and use
`FRETPILOR_TEST_REFERENCE_ZIP=/absolute/path/to/archive.zip`. Normal CI never
depends on the private archive.

The public GuitarSet seed remains reproducible from its pinned verified
annotation artifact:

```bash
cd backend
uv run python -m fretpilot.elearning.guitarset /path/to/annotations \
  --output src/fretpilot/knowledge/assets/kb2_performance.json
```

Never use a private or rights-unknown corpus with this seed builder.

## 12. Definition of done

A task is complete only when:

- its real product acceptance scenario passes;
- document/command, migration, permission and failure contracts are current;
- state is durable and observable, with no simulated success;
- tests are deterministic and relevant performance limits are measured;
- undo, collaboration and export behavior are covered when affected;
- active documentation and generated API types are current;
- CI is green;
- rollout/rollback is credible;
- no unused, dead, fake or duplicate implementation remains in the changed
  area.

A demo that only edits renderer memory, a benchmark-only music improvement, or
an exporter parsing its own file is not completion.

## 13. Pull-request and review policy

- One logical outcome per pull request. Prefer contract -> persistence -> thin
  vertical slice -> breadth over a cross-layer mega-PR.
- State database, document schema, API, WebSocket, security, export and
  operational compatibility impacts in the description.
- Include before/after evidence for musical formulas, renderer performance and
  user journey behavior.
- High-risk changes require migration, auth, reconnect, retry, SSRF and
  multi-track export scenarios as applicable.
- Reviewers reject arbitrary score JSON mutation, route-level music logic,
  client-only autosave claims, silent conflict fallback, mutable package data,
  unbounded prompts and status that does not reflect durable truth.
