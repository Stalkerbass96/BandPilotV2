# Phase 2 and Phase 3 completion record

This record defines what “Phase 2–3 complete” means for the approved BandPilot
architecture. The objective is not to add every future instrument today; it is
to establish one reliable product contract on which bass, keys, generic parts,
MusicXML, humanized MIDI, and additional sound profiles can be added without
forking the system.

## Phase 2 — canonical product platform

### Canonical score contract

- Added SongIR schema `2.0` with separate source, analysis, score, technique,
  performance, validation, and reproducibility layers.
- Guitar and drum pipelines keep focused working IRs. A single adapter builds
  SongIR; reverse adapters exist only at legacy exporter boundaries.
- Stable note IDs are track-scoped. Track assignments include classifier
  confidence, reason, and whether a user overrode the result.
- Unplayable source notes are represented as `unresolved_events` with source
  index, pitch, timing, and reason. They are not given fake guitar positions.
- Strict SongIR JSON loading rejects unsupported major schema versions and
  round-trip tests protect serialization compatibility.

### Instrument routing and user correction

- Added an explicit `InstrumentPlugin` protocol and registry. Guitar and drums
  are registered implementations; bass, keys, and unknown remain truthful
  passthrough families until their own plugins exist.
- Track-family corrections are persisted through
  `PUT /api/projects/{project_id}/tracks/{track_index}` and are honored by
  subsequent repair runs.
- Multiple drum tracks now receive source-stable unique IDs; mixed, guitar-only,
  drum-only, multiple-guitar, and multiple-drum workflows share one service.

### Run modes, jobs, and artifacts

- Repair modes are explicit: `faithful`, `playable_arrangement`, and
  `creative_rewrite`. Faithful mode does not apply LLM note rewrites.
- Added Alembic revision `20260823_0002` and durable `repair_jobs` history with
  status, progress, settings, arrangement mode, run ID, error, and timestamps.
- Every repair writes `artifact_manifest.json` with SHA-256 hashes and pinned
  application, schema, knowledge, model, prompt, settings, and validation data.
- Added authenticated APIs for repair-job history, canonical SongIR, and the
  latest artifact manifest.
- `repair_manifest.json` now derives failed and passthrough tracks from final
  per-track outcomes, including failures discovered by score validation.

### Product UI

- Workbench exposes arrangement mode and per-track family correction.
- Repair responses expose validation state and structured issues.
- Existing status handling remains consistent across API, database, manifest,
  and UI.

## Phase 3 — professional playability and governed learning

### Phrase-global guitar realization

- Replaced onset-local fingering selection with bounded phrase-level beam
  search.
- The objective combines candidate cost, learned chord shapes, hand-position
  movement, string movement, playing speed, open-string economy, chord string
  uniqueness, and maximum hand span.
- Open strings remain preferred for an isolated note, while rapid phrases can
  select a fretted same-string alternative to avoid unrealistic string hopping.
- Search limits and deterministic fallback prevent combinatorial blow-up. No
  source note is silently removed by the solver.

### Technique graph and hard validation

- Articulations are converted into explicit `TechniqueIR` note relations/spans.
- Hammer-on, pull-off, and slide validation checks arity, note existence,
  ordering, same-string feasibility, and direction where applicable.
- Score validation also checks unique IDs, measure/time consistency, duration,
  pitch range, voices, performance mapping, velocity, guitar tuning/string/fret
  truth, chord collision/span, and drum realization.
- New exporters validate SongIR first and never alter score meaning. Invalid
  scores return structured errors rather than plausible-looking false output.

### Professional GP corpus model

- GP parsing now has a full-corpus representation retaining every track,
  percussion flag, program, tuning, capo, voice, tie, absolute timing, and
  explicit techniques including palm mute, let ring, staccato, vibrato, bend,
  harmonic, grace, trill, tremolo picking, legato, and slide relations.
- Style statistics include explicit technique rates; derived KB priors can
  carry learned articulation weights as well as fingering and chord-shape data.
- Corpus provenance models content hash, license ID, training permission,
  review tier, and train/validation/test split. Duplicate content across splits
  is rejected.

### Safe self-learning lifecycle

- The learning API requires a license/rights identifier, explicit training-use
  confirmation, and reviewed/expert quality tier. Knowledge provenance stores
  those governance values and content hashes rather than temporary local paths.
- Learning always creates an immutable candidate; direct promotion is rejected.
- `POST /api/elearning/evaluate` runs server-side baseline/candidate A/B
  evaluation on an independent GP corpus and records evidence. Content hashes
  are compared with candidate provenance so renamed training files cannot leak
  into validation.
- `POST /api/elearning/promote` enforces minimum sources, evaluated files,
  fingering accuracy, pitch accuracy, chord-shape accuracy, and hand-position
  deviation. Candidate snapshots cannot bypass the gate through rollback.

## Non-goals intentionally left for later phases

> Status update: the instrument-plugin, MusicXML, generic humanized MIDI, and
> humanized Ample Eclipse items below were completed in
> `PHASE_4_6_COMPLETION.md`. The list is retained as the historical Phase 2–3
> boundary.

- Bass, keys, and generic-instrument repair plugins. Their interfaces and SongIR
  realization fields are ready, but pretending they are implemented would make
  project status and score quality dishonest.
- MusicXML export, humanized generic MIDI export, and sound profiles beyond
  Ample Guitar Eclipse.
- Distributed queue workers and cancellation. Repair jobs are durable and
  observable, while execution remains in-process for the current deployment.
- A learned neural fingering model. Phase 3 establishes trustworthy corpus,
  relation, evaluation, and promotion contracts first.

## Verification snapshot

- Backend lint: passed.
- Backend unit/integration suite: 528 passed, 6 external-corpus tests skipped;
  statement coverage is 80.38% (80% gate passed).
- Frontend TypeScript and Vite production build: passed.
- Database migration tests cover fresh install, legacy adoption, and the repair
  job revision.
- New regression coverage includes SongIR round trip, artifact hashing,
  unresolved notes, strict-export rejection, technique relations, corpus rights,
  split leakage, promotion gates, family overrides, and repair-job APIs.

## Rules for Phase 4 onward

1. A new instrument requires its own plugin, working IR/adapter, playability
   validator, fixtures, and exporter behavior; never route it through guitar.
2. SongIR is the only persisted editable score truth. Schema changes require a
   version decision, serializer migration, adapter tests, and exporter tests.
3. LLM output is a proposal. Deterministic policy and musical validation decide
   whether it may alter score truth.
4. Exporters serialize only. A missing fingering, collision, impossible
   technique, or invalid rhythm must be fixed upstream or explicitly unresolved.
5. Knowledge candidates never become active from training-set statistics alone.
   Independent no-regression evidence and an auditable promotion are mandatory.
6. Each feature needs measurable musical acceptance criteria, deterministic
   regression fixtures, and a rollback path before it is called complete.
