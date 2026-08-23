# BandPilot roadmap

Updated: 2026-08-23

This document is the only active priority/status plan. Historical Phase 0–7
records are snapshots under `docs/archive/milestones/` and must not be edited
into a competing roadmap.

## 1. Current baseline

The product currently has one end-to-end path for guitar, drums, bass, keys and
generic pitched tracks; SongIR 2.0 validation; async start/poll repair; GP5,
MusicXML, humanized band MIDI and Ample Eclipse exports; AlphaTab preview; BYOK
LLM fallback; and governed corpus candidate/evaluation/promotion APIs.

Current engineering verification:

- Backend: 551 passed, 6 opt-in external-corpus tests skipped.
- Frontend: 8 passed; TypeScript and production Vite build passed.
- `Story of Despair.mid`: API export/download passed, the 12-track/113-measure
  GP5 opened in Guitar Pro 8 and imported in AlphaTab.

The recent GP5 incident established two release invariants: pitched GP5 tracks
must have 4–7 strings, and any used voice 2 must remain continuous through
rest-only/padded measures.

## 2. Professional corpus evidence

The current 100-song full-product round-trip baseline used 99 successful songs:

| Metric | Baseline |
|---|---:|
| Source/generated notes | 259,757 / 254,687 |
| Aligned notes | 244,716 |
| Track classification accuracy | 100% |
| Note recall / precision | 94.21% / 96.07% |
| Exact onset / duration | 94.26% / 91.47% |
| Guitar/bass exact string position | 50.62% |
| Chord-shape agreement | 56.21% |
| Technique precision / recall / F1 | 6.44% / 0.76% / 1.35% |

Instrument evidence:

| Family | Note recall | Exact duration | Exact string position | Technique F1 |
|---|---:|---:|---:|---:|
| Guitar | 99.34% | 94.17% | 57.71% | 1.53% |
| Bass | 89.56% | 89.76% | 47.52% | 0% |
| Drums | 80.33% | 92.40% | — | 0.26% |
| Keys | 96.23% | 81.07% | — | 0% |
| Generic | 98.68% | 85.31% | — | 0% |

These values diagnose the product; they do not authorize training. Corpus
rights and split metadata are still incomplete. Composite score is for ranking
only and never replaces per-dimension gates.

## 3. Recommended sequence

The next investment should not be another export format or sound library. The
highest-value path is: make every run/export operationally trustworthy, then
improve tuning and phrase fingering, then restore techniques. Fingering must
precede most technique work because slide/hammer/pull feasibility depends on
stable string and fret realization.

### Immediate development batch

Start with three separate, reviewable changes. Do not combine them into one
large refactor:

1. **Export trust contract** — extend the export record with artifact hash,
   exporter version, compatibility status and warnings; make GP5 generation
   content-addressed; add the mixed-score compatibility fixture and gate.
2. **Repair/LLM reliability** — persist real stage transitions and LLM attempt
   metadata, add bounded transient retry and idempotency, then move execution
   behind a recoverable worker without changing the public start/poll API.
3. **M9 research baseline** — freeze the authorized validation split, report
   fingering metrics by tuning/role/style, and only then implement Top-K
   tuning/capo inference and phrase-level fingering candidates.

Each change must land with its migration, API/frontend contract update,
regression fixtures and rollback behavior. The first two changes are production
reliability work; the third begins measurable music-quality improvement.

### M8 — export trust and repair reliability (P0)

Objective: eliminate “reported success but unusable artifact” and make long LLM
runs recoverable.

Deliverables:

- Add a format-compatibility validator that checks GP5 semantic constraints not
  covered by PyGuitarPro.
- Add a committed small mixed-score fixture that is imported by PyGuitarPro and
  AlphaTab in CI; retain Guitar Pro 8 as a release smoke checklist.
- Persist export warnings, compatibility status, exporter version and artifact
  hash, and show them in export history.
- Make export content-addressed using SongIR hash, format, exporter version and
  profile, so preview/download retries reuse one artifact instead of filling
  history with duplicate files.
- Move repair execution from API-process background tasks to a durable worker
  queue with startup recovery, idempotent attempts and cancellation.
- Add an LLM attempt ledger, bounded retry for transient errors, provider
  circuit breaker, request fingerprint/cache and per-stage latency/degraded
  metrics. Retries must never duplicate score transformations.
- Replace the current first-200-note rewrite sample with section/phrase feature
  summaries. Do not solve token limits by sending an entire long score.
- Replace simulated stage progress with persisted stage transitions.

Acceptance:

- No export record is created until validation and compatibility gates pass.
- Restarting the API during an active repair does not lose or falsely complete
  the job.
- Duplicate request/retry produces one logical run and one transformation set.
- GP5 fixture passes PyGuitarPro and AlphaTab automatically and GP8 manually.

### M9 — tuning and professional guitar fingering (P0 product quality)

Objective: improve the primary GP score's physical realization without
regressing pitch or rhythm.

Deliverables:

- Per-guitar-track Top-K tuning/capo inference with calibrated confidence,
  evidence and user confirmation/override.
- Preserve selected tuning/capo in SongIR pins and round-trip sidecar metadata.
- Calibrate the phrase-global optimizer from authorized corpus statistics:
  position movement, string continuity, repeated-note stability, open strings,
  chord shape, barre feasibility, stretch, tempo and role.
- Compare several playable candidates against knowledge priors; never imitate
  a reference position when it violates hard constraints.
- Optionally let the LLM rank a small deterministic set of already playable
  phrase candidates; the no-LLM ranking remains the reproducible baseline and
  hard validation keeps veto power.
- Add difficult fixtures for low tunings, duplicate pitches, 7-string parts,
  fast position shifts and mixed lead/rhythm source tracks.

First milestone gates on the fixed validation set:

- Guitar note recall remains at least 99%.
- Exact onset and duration do not regress by more than 0.5 percentage point.
- Guitar exact string position improves from 57.71% to at least 65%.
- Chord-shape agreement improves from 56.21% to at least 65%.
- Hard playability errors remain zero in accepted exports.

Targets are ratified against a frozen, licensed validation split before merge.

### M10 — evidence-based technique recovery (P0 product quality)

Objective: make articulation useful to professional players rather than merely
present in the schema.

Deliverables:

- Build a per-technique evidence matrix from note overlap, velocity/gate,
  repeated pitch, interval/direction, string continuity, phrase boundary and
  tempo.
- Implement deterministic candidates for let ring, staccato, palm mute,
  hammer-on, pull-off and slide before bend/vibrato/grace extensions.
- Validate technique relations after fingering and remove impossible
  candidates with explicit reasons.
- Allow the LLM only to rank or explain already valid candidates, with a
  no-LLM result as the reproducible baseline.
- Report precision/recall/F1 separately per technique and by style/role.

First milestone gates:

- Overall technique precision at least 30%, recall at least 10%, F1 at least
  15% on the frozen validation split.
- No regression in note, rhythm, fingering or hard-validation gates.
- Every emitted linked technique passes same-string/order/direction checks.

### M11 — instrument depth (P1)

Objective: stop measuring “multi-instrument support exists” and start measuring
professional quality for each family.

Order:

1. Bass: independent left-hand phrase optimizer, right-hand alternation,
   muting/sustain and bass-specific technique priors. First exact-position gate
   is 60% without note/rhythm regression.
2. Drums: family-equivalent evaluation before changing mappings, then improve
   GM variants, cymbal/tom roles, sticking, accents, ghost notes and flams.
3. Keys: pedal inference, voice-leading, hand crossing and duration/pedal
   interaction; MusicXML is the primary notation acceptance format.
4. Generic: retain faithful notation/performance and add instrument-family
   behavior only when a typed plugin and validation model exist.

### M12 — governed self-learning product (P1)

Objective: turn the local corpus experiment into a legal, reproducible learning
workflow.

- Inventory source, license, permission, review tier and content hash.
- Freeze train/validation/test splits and reject duplicates across them.
- Expose candidate evidence, diffs and promotion decisions in an admin UI.
- Learn style/role/instrument priors only from approved training data.
- Promote only after independent M9–M11 gates pass; preserve one-click rollback
  to a previously promoted snapshot.

### M13 — performance and sound profiles (P2)

Only after the GP score gates are stable:

- Add profile-schema validation and a governed mapping test harness.
- Learn timing/dynamics/gate profiles by style and instrument.
- Add the next Ample or other virtual-instrument profile through the registry,
  never through exporter-specific hard-coded branches.
- Evaluate MIDI controller/keyswitch correctness and audible A/B renders.

## 4. Work deliberately deferred

- End-to-end neural score generation.
- Automatic promotion from the unlicensed desktop corpus.
- Supporting legacy `.gtp` 2.21 through an unverified parser.
- Native modern Guitar Pro formats until GP5 and MusicXML quality gates are
  stable.
- More frontend animation before async truth, warnings and musical comparison
  are visible.

## 5. Task intake template

Every roadmap task starts with:

```text
Outcome:
User-visible acceptance:
Musical invariant:
Affected contracts:
Failure/degraded behavior:
Regression fixture and metric:
Non-goals:
Rollback/migration:
```

A milestone is complete only when its metric is computed by the real product
round-trip path, not a benchmark-only implementation.
