# BandPilot development rules

This document is the mandatory working agreement for BandPilot changes. The
goal is predictable delivery: one source of truth per workflow, explicit
contracts, small reviewable changes, and no silent failure paths.

## 0. Documentation authority

- `PRODUCT.md` owns product behavior and success metrics.
- `ARCHITECTURE.md` owns system boundaries and contracts.
- This file owns development workflow and definition of done.
- `ROADMAP.md` owns priority, status and milestone gates.
- Documents under `archive/` are historical and must not be used as current
  acceptance criteria.
- Update an existing owner document. Do not create versioned PRDs or new phase
  completion files.

## 1. Architecture boundaries

The permitted dependency direction is:

```text
API routes -> application services -> orchestrator -> instrument pipelines
                                      -> working IR adapters -> SongIR
instrument pipelines -> knowledge / MIDI / working IR
SongIR -> validation -> exporters
learning ingest -> candidate snapshot -> A/B evaluation -> promotion
```

- API routes authenticate, validate transport data, open transactions, and map
  service results to responses. They do not implement repair stages.
- `RepairService` is the only application entry point for a project repair.
- `BandPilotOrchestrator` classifies and routes every physical source track.
- Instrument pipelines own instrument-specific transformations. A new
  instrument family requires a plugin, working IR, adapter, validator, fixture,
  and exporter behavior; it must never be disguised as guitar.
- SongIR is the canonical persisted score contract. Focused guitar/drum IRs
  may exist inside pipelines and compatibility adapters, but no new feature
  may create a second editable score source of truth.
- IR is a versioned contract. Schema changes require a migration strategy,
  serializer tests, exporter tests, and an explicit schema-version decision.
- Exporters are read-only consumers. They must not repair, transpose, drop,
  deduplicate, or invent realization data. Impossible source notes belong in
  SongIR's unresolved layer.
- A writer's own parse-back is necessary but not sufficient. GP5 behavior that
  affects product compatibility requires PyGuitarPro structural checks,
  AlphaTab import coverage and a Guitar Pro release smoke test where relevant.
- Packaged knowledge is an immutable seed. Runtime learning writes only to the
  configured knowledge store.
- Every repair has a durable repair-job row and reproducibility manifest.
  Project status is the latest-result projection, not execution history.
- Browser-facing repair uses start-and-poll semantics. LLM or corpus work must
  never depend on one long-lived HTTP connection: start returns `202` with a
  job ID, terminal jobs persist their typed result or explicit error, and the
  UI resumes polling after refresh. The synchronous endpoint exists only for
  backwards-compatible trusted clients and tests.

## 2. Code rules

- Prefer typed dataclasses or Pydantic models at module boundaries. Do not add
  unstructured dictionaries where a stable contract exists.
- Keep functions focused. When branching obscures one responsibility, extract
  a named helper; do not suppress complexity merely to satisfy a check.
- No duplicate orchestration paths, commented-out implementations, fake UI
  data, developer-specific absolute paths, or compatibility code without an
  identified caller and removal condition.
- Errors must be classified as fatal, partial, or warning. Never catch a broad
  exception and report success. User-facing errors may not expose secrets or
  internal paths.
- Every destructive transformation must produce a traceable `Transformation`.
- `faithful` mode never applies LLM note rewrite decisions. Arrangement mode,
  model identity, prompt version, and knowledge snapshot are pinned per run.
- External calls require authentication, bounded timeouts, validated public
  destinations, redirects disabled unless explicitly reviewed, and tests with
  no real network access.
- Client request timeouts are not job cancellation. A disconnected browser
  must not mark server-side work failed; duplicate active jobs are rejected,
  and every background failure must move the job to a terminal state.
- Retries must be idempotent. LLM retries, worker recovery and repeated client
  requests may not apply a transformation twice or create a false success.
- Runtime data writes must be atomic where readers can observe the file. Shared
  knowledge writes also require a process-safe lock.
- Learning inputs require rights, review, and split metadata. New snapshots are
  candidates until independent A/B evidence passes deterministic no-regression
  gates; rollback may restore promoted snapshots only.
- Every knowledge provenance value is a stable ID declared in
  `knowledge/assets/source_catalog.json`; file paths, song names and ad-hoc
  bibliography strings are forbidden. Empirical/derived knowledge requires a
  verified source with `derive_aggregates` permission.
- Corpus statistics are calculated within each score/excerpt and only then
  aggregated. Chords, transitions, overlaps and phrase paths may never cross a
  file, track or train/validation/test boundary.
- Knowledge resolution layers generic defaults before style and role overrides.
  A role-scoped entry must never satisfy a query that omitted the role.
- Database schema changes are Alembic revisions. `create_all()` is allowed only
  in isolated tests, never as the application migration mechanism.

## 3. Status contract

Project repair status has one meaning across API, database, UI, and manifest:

- `processing`: work started and has not reached a terminal outcome.
- `repaired`: every note-bearing source track had a supported pipeline and all
  those pipelines completed.
- `partial`: at least one instrument plugin completed, but another track failed
  execution or professional-score validation. The failed track and unresolved
  source events remain explicit in the manifest and SongIR.
- `failed`: no instrument plugin completed or the project-level workflow
  failed before an output could be produced.

## 4. Change workflow

1. Write a short issue or task statement with outcome, user-visible acceptance,
   musical invariant, affected contracts, failure/degraded behavior, regression
   fixture/metric, non-goals, and rollback or migration needs.
2. Inspect existing ownership boundaries and tests. Reuse the current service
   and IR contracts instead of adding a parallel path.
3. Add or update a failing test for each behavior change. Bug fixes require a
   regression test that fails for the original cause.
4. Implement the smallest coherent change. Keep refactors separate from
   unrelated product behavior when practical.
5. Run the local gates below. For security, migration, job, LLM or export
   changes, also run the relevant real boundary integration scenario.
6. Update documentation and `.env.example` when behavior, operations, or
   configuration changes.
7. Review the diff for unrelated formatting, generated artifacts, secrets,
   absolute paths, stale code, and missing failure handling.
8. Merge only after CI passes and acceptance criteria are demonstrably met.

Musical-intelligence changes must add at least one machine-checkable
playability invariant (pitch/string/fret, span, technique relation, rhythm, or
export round trip) and a comparison against the current knowledge snapshot.
Changes to empirical formulas also rebuild the asset from its pinned source,
report held-out split drift, and keep the frozen test split out of tuning.

## 5. Required local gates

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

External GP corpus tests are opt-in and use
`FRETPILOR_TEST_REFERENCE_ZIP=/absolute/path/to/archive.zip`. CI and the normal
unit suite never depend on that archive.

The public GuitarSet KB2 seed is reproducible from the verified 360-file JAMS
annotation directory (the artifact hash is pinned in `source_catalog.json`):

```bash
cd backend
uv run python -m fretpilot.elearning.guitarset /path/to/annotations \
  --output src/fretpilot/knowledge/assets/kb2_performance.json
```

Never point this builder at a private or rights-unknown corpus. Such corpora use
the candidate/evaluation workflow and require catalogue registration first.

GP5 changes also require the committed compatibility fixture to pass the
frontend AlphaTab importer. A release candidate that changes GP5 structure is
opened once in Guitar Pro 8 and the tested application version is recorded in
the task or release evidence.

## 6. Definition of done

A task is complete only when its acceptance criteria pass, migrations and
contracts are updated, failure states are observable, tests are deterministic,
active documentation is current, CI is green, and no unused/dead/fake
implementation remains in the changed area. Passing a happy-path demo or a
single library's parse-back alone is not completion.

## 7. Pull-request scope and review

- One logical outcome per pull request. Split architecture migrations from new
  feature families when they can be reviewed independently.
- Call out database, IR, API, security, and operational compatibility impacts.
- High-risk changes require explicit tests: auth/SSRF/archive handling,
  migration from existing data, multi-track exports, and KB promotion/rollback.
- Reviewers reject silent fallback, route-level business logic, mutable package
  data, and output status that does not match the actual per-track results.
