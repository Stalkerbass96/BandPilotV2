# BandPilot roadmap

Updated: 2026-08-28

This is the only active priority and status plan. Historical Phase 0–7 records
remain immutable snapshots under `docs/archive/milestones/`.

## 1. Current verified baseline

BandPilot currently provides one end-to-end MIDI path for guitar, drums, bass,
keys and generic pitched tracks; SongIR 2.0 validation; asynchronous repair;
GP5, MusicXML, humanized MIDI and Ample Eclipse exports; AlphaTab preview; BYOK
LLM fallback; and governed corpus candidate/evaluation/promotion APIs.

Latest recorded engineering evidence:

- Backend: 616 tests passed, 6 external-corpus tests skipped; Ruff and package
  build passed.
- Frontend: 50 tests passed; TypeScript and production Vite build passed.
- `Story of Despair.mid`: 12-track/113-measure GP5 exported, opened in Guitar
  Pro 8 and imported in AlphaTab.
- Pitched GP5 tracks use 4–7 serialization strings, and a used voice 2 remains
  continuous across rest/padded measures.
- Drum notation uses onset-safe durations, exact GM variants and conventional
  five-line/two-voice notation. The fixed 20-song regression sample improved
  strict GM recall from 89.63% to 99.31% with 100% exact onset/written duration
  among matched notes and no failed song.
- The frontend now has a full-screen Studio foundation: direct
  ScoreDocument-to-AlphaTab rendering, deterministic caret/range selection,
  direct guitar/bass fret entry, individual chord-tone add/delete, note/rest
  conversion, duration/voice/transpose/basic-technique commands, exact
  dot/triplet values, paired ties, notation/performance dynamics, same-track
  beat copy/cut/paste, optimistic save acknowledgement, session undo/redo,
  keyboard shortcuts, a searchable action-aware command palette, direct bar
  navigation, 75–150% notation zoom, page/horizontal score layouts, persistent playback, count-in,
  selected-passage looping, musician-facing relative speed and metronome
  controls, and revision-pinned GP5, MusicXML and humanized MIDI export. The
  track rail now creates and safely deletes empty tracks, reorders them, edits
  names/programs/notation modes, retunes or applies capo while preserving
  playable pitch, and persists mute/solo/volume/pan. The complete Guitar
  Pro-level editing surface is not complete.

These counts describe the current worktree evidence and must be refreshed at
each accepted milestone.

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

These metrics diagnose the product; they do not authorize training. The private
GTP corpus still lacks rights and leakage-safe split metadata for knowledge
promotion.

The fixed drum regression sample (8 drum tracks, 8,315 source notes) is:

| Drum metric | Previous | Current |
|---|---:|---:|
| Strict GM note recall | 89.63% | 99.31% |
| Exact onset | 99.93% | 100.00% |
| Exact written duration | 100.00% | 100.00% |
| Professional score score | 90.99% | 96.22% |
| Failed songs | 0 | 0 |

Drum evaluation continues to report fidelity and notation validity separately;
duration agreement cannot hide an open voice, overlap or invalid stem policy.

## 3. Strategic priority

The product owner confirmed the four release defaults on 2026-08-26: desktop
editing first, mobile review/comment/playback, AI preview-before-Apply,
project-level collaboration roles, and blank-score/MIDI entry before Guitar Pro
or MusicXML import. E0 may proceed without another scope decision.

The next product is the score editor, not another format, model or sound
library. Delivery order is constrained by data integrity:

1. establish the canonical editable document, typed command and renderer
   boundary;
2. ship a complete single-user editing slice;
3. integrate every existing core engine as a reversible editor tool;
4. add collaboration on the same command protocol;
5. add selected-range LLM proposals on the same protocol;
6. broaden Guitar Pro-level notation depth and production scale.

Music-quality work continues through explicit parallel quality tracks. It may
not create a competing model or delay the editor foundation with unrelated
refactors.

## 4. Editor upgrade program

### E0 — contract and renderer proof (P0)

Status (2026-08-28): ScoreDocument, typed transaction, relational
revision/snapshot/command persistence, raw/blank initialization, SongIR
compatibility adapters and revision-pinned export are implemented with contract
tests. The repeatable AlphaTab core/model probe passed, the production strict
adapter is in place, and the E1-A desktop browser gate passed real TAB hit
testing, stable-ID selection, rerender and playback. The later five-family
browser matrix also passed exact note-head-to-stable-ID selection. The production
104-measure/five-track browser gate now records lazy SVG render and rerender
timings, bottom-system stable identity, end-of-score playback and synchronized
cursor movement across three tempo regions. Evidence:
[`evidence/alphatab-editor-spike.md`](./evidence/alphatab-editor-spike.md).

**Outcome:** remove the two highest technical uncertainties before building UI:
editable document semantics and the AlphaTab interaction boundary.

Deliverables:

- ScoreDocument 3.0 schema with stable IDs, rational time, performance layer,
  validation and transformation provenance.
- A versioned closed union of ScoreOperation and ScoreTransaction with
  idempotency, preconditions, conflict results and inverse metadata.
- Deterministic SongIR 2.0 -> ScoreDocument 3.0 fixtures for guitar, drums,
  bass, keys and generic tracks.
- A disposable AlphaTab editor spike proving hit testing, caret/range
  selection, note/rest mutation, rerender and playback synchronization.
- A 100+ measure mixed-score performance profile and a licensing check.
- Relational schema/migration plan for documents, revisions, commands, members,
  proposals, comments and revision-pinned exports.
- API and WebSocket contract sketches with permission/error vocabulary.

Acceptance:

- Repeated fixture conversion produces byte-stable canonical JSON and the same
  revision hash.
- A note edit survives render -> command -> validation -> render without using
  GP5 or renderer object identity as storage.
- Drum and keyboard selection mapping works, not only guitar TAB.
- Invalid duration, broken reference, string/fret collision and bad drum voice
  transactions fail before commit.
- The spike records measured render/input/playback limits and ends in a written
  keep/replace decision for AlphaTab.
- No production editor framework is merged from the disposable spike.

### E1 — single-user editor vertical slice (P0)

Status (2026-08-28): E1-A and E1-B are complete locally; the expanded E1-C
editing surface and E1-D typed track surface are implemented. MIDI projects keep an
immutable source and raw revision zero, use the existing preparation workbench,
then promote the first prepared SongIR as one fenced system revision. Blank
projects enter the editor directly. Authenticated snapshot/command/catch-up/undo
APIs and the desktop shell now support stable note/beat/explicit-rest and
shift-extended range selection, first note/rest input, direct guitar/bass fret
entry, conventional drum-kit input with hand/foot voice routing, chromatic
keys/generic input, individual chord-tone add/delete, note/rest conversion,
written-duration and voice changes, exact dot/triplet modifiers, paired
same-voice ties, notation/performance dynamics, selected-range transpose, aligned all-track
measure insert/duplicate/delete, eleven common technique controls, same-track
beat copy/cut/paste, optimistic local projection, truthful save/conflict states,
session undo/redo, core keyboard shortcuts, working AlphaTab playback and
exact-revision GP5, MusicXML and humanized MIDI export. The technique path includes validated same-string
hammer-on/pull-off/slide links plus bend, natural harmonic and vibrato renderer
and GP5 coverage. MusicXML carries written tuplets, dots, ties and explicit
dynamics; humanized MIDI joins valid tie chains without duplicating their
continuations. A real browser run verified the earlier input sequence through
revision 15, including chord input, rest conversion, range voice edit, undo,
palm mute and transpose while playback stayed ready. The E1-D typed track
surface now covers aligned track creation, empty-track deletion, reorder,
name/program/notation mode, tuning/capo and mixer state; AlphaTab playback,
GP5 and humanized MIDI consume the applicable settings. Default extension
fields are omitted from canonical 3.0 snapshots so prior revision hashes remain
valid. A later desktop browser gate exercised all five track families through
revision 31, including create, input, reorder, setup, mixer, refresh and
undo/redo. A fresh five-track revision 9 then exported GP5, MusicXML and
humanized MIDI from the same hash; GP5 parsed back with the editor's stable
track order. Exact rendered note-head selection now resolves stable IDs for all
five families, including keyboard grand-staff collisions. The 104-measure scale
gate now passes for the supported subset, including bar-104 hit testing and
playback across exact tempo-map projections. Remaining advanced notation and
release latency objectives keep E1 as a whole incomplete. The core
transport now supports count-in, exact selection-loop ranges, 50–150%
musician-facing speed presets and metronome state that survives score rerenders.
The command palette routes editing, navigation, playback and exact-revision
export actions through the same production handlers, includes contextual
disabled states and searches large bar indexes without flooding its default
result list. Page and continuous horizontal layouts use the same persistent
renderer and preserve the current selection and practice state. A stale
AlphaTab highlight discovered during track switching is
also cleared before each render, preventing the editor from becoming stuck
behind its loading mask.

**Outcome:** a musician can create or import a project, edit the score, refresh
and export the exact edited revision.

Deliverables:

- The project route becomes the editor shell with project bar, transport, track
  rail, dominant score canvas and contextual inspector.
- Blank score and MIDI import create ScoreDocument revision zero; the source
  MIDI stays immutable.
- Caret/range selection, note/rest input, pitch/duration edits, insert/delete,
  copy/cut/paste, transpose and measure operations.
- Guitar/bass TAB positions, standard pitched notes, conventional drum input
  and keyboard staff navigation.
- Undo/redo as compensating typed transactions; autosave and truthful
  saving/offline/conflict states.
- Track add/reorder, instrument, tuning/capo, notation mode, mute/solo,
  volume/pan.
- Playback, metronome, loop selection, relative tempo, keyboard shortcuts and
  initial command palette.
- GP5, MusicXML and MIDI export pinned to the active committed revision.

Acceptance:

- Create -> first editable score requires no repair report page.
- A representative edit on every instrument family persists after refresh and
  appears in the pinned export.
- One user action is one undo step; 100 randomized edit/undo pairs restore the
  same document hash.
- Routine input gives local visual feedback within 50 ms on the supported
  reference device; autosave acknowledgement meets the measured target.
- The current import/repair/export path remains accessible until E2 equivalence
  is proven.

### E2 — intelligence inside the editor (P0)

**Outcome:** all existing core features work from the editor as reviewable,
reversible tools.

Deliverables:

- “Prepare score” converts current orchestrator output into one proposed
  ScoreTransaction instead of overwriting an artifact.
- Import opens a raw score immediately; preparation runs as a durable,
  resumable background task.
- Notation diff, change summary, validation markers, Apply/Reject and one-step
  undo for preparation.
- “Make playable” works on selection, track or score and uses promoted
  knowledge with pinned versions.
- Humanization modifies the performance layer/profile and supports A/B
  playback without changing notation unless explicitly requested.
- Existing Guitar Pro, MusicXML, band MIDI and Ample Eclipse output capabilities
  remain available in the editor.
- Real task stages replace simulated progress, with worker recovery,
  cancellation and idempotent retry.

Acceptance:

- Current end-to-end fixtures match or improve every musical/export gate.
- Leaving, refreshing or disconnecting cannot lose a completed proposal.
- Reject changes no score state; Apply creates one validated revision and one
  undo step.
- Repeating a task or request cannot duplicate transformations or artifacts.
- Every existing documented output is produced from a pinned editor revision.

### E3 — collaboration and review (P0)

**Outcome:** invited musicians can safely edit and discuss one score in real
time.

Deliverables:

- Project invites and owner/editor/commenter/viewer permissions.
- Authenticated document WebSocket, accepted-command fan-out, reconnect and
  revision catch-up.
- Remote presence, viewport, caret and range selections with collaborator
  identity.
- Anchored comment threads, mentions/notifications where configured and
  resolution history.
- Version timeline with named checkpoints and read-only historical comparison.
- Explicit conflict UI for the small set of transactions that cannot rebase.

Acceptance:

- Two editors can change disjoint passages and converge on the same revision
  hash in all tested message orders.
- Same-field and delete-versus-edit conflicts are visible and never silently
  overwrite accepted work.
- Undo from one editor preserves another editor's unrelated transaction.
- Revoked access closes the live session and blocks REST/artifact access.
- No acknowledged command is lost across refresh, reconnect, API restart or
  worker restart.
- Accepted-command propagation is below 250 ms p95 in the primary-region load
  test; the supported concurrent-editor limit is documented.

### E4 — selected-range AI editing (P0)

**Outcome:** a musician can describe a change to a selected passage, inspect it
in notation and sound, then accept it safely.

Initial intents:

- clean or quantize rhythm;
- simplify density/difficulty;
- redistribute voices;
- transpose within instrument range;
- optimize fingering and playable chord shapes;
- adjust techniques or dynamics;
- humanize the performance layer.

Deliverables:

- Selection-aware assistant with prompt, supported-intent suggestions and clear
  scope.
- Durable proposal attempts pinned to base revision, model, prompt/schema,
  knowledge and settings.
- Strict operation-schema response, deterministic resolution, hard validation
  and stale proposal handling.
- Notation diff, semantic summary, warnings, A/B playback and Apply/Reject.
- Creative changes gated by `creative_rewrite`; BYOK credentials remain
  requester-owned.

Acceptance:

- No provider response can mutate a document without command validation and an
  authorized Apply action.
- Each supported intent has deterministic mocked-provider contract tests,
  invalid-operation tests and at least one musical regression fixture.
- Proposal Apply is atomic and undoable in one step; Reject is mutation-free.
- A changed base revision rebases only disjoint safe operations; otherwise the
  user sees a stale result.
- Provider timeout/failure leaves manual editing and the current score intact.

### E5 — professional notation and workflow depth (P1)

**Outcome:** BandPilot covers the recurring professional arrangement workflow,
not merely basic note entry.

Order:

1. repeats/endings, markers, directions, dynamics, chords, lyrics and text;
2. complete guitar/bass technique and drum articulation palettes;
3. grace notes, rolls/flams, tremolo, piano fingering and sustain pedal;
4. advanced voices/beaming/stems, nested tuplets and special paste;
5. layout/stylesheet/design controls and print/PNG/SVG/PDF where justified;
6. audio-track synchronization and deeper practice workflows.

Each group starts with a feature matrix: required edit behavior, renderer
coverage, playback, undo, collaboration, import/export and round-trip. A feature
is not complete when it only draws correctly.

Acceptance:

- The curated professional editing scenarios complete without leaving the
  editor or hand-editing an export.
- Each notation object survives command history, collaboration, refresh and
  required format round-trip.
- Keyboard-only users can reach and edit all P0 notation controls.
- Large-score performance stays within the published support envelope.

### E6 — production hardening and controlled migration (P1)

**Outcome:** the editor can replace the old workbench for production users
without risking existing projects.

Deliverables:

- PostgreSQL, durable object storage, recoverable workers and multi-instance
  collaboration fan-out.
- Migration of existing projects to revision zero with hash/audit evidence.
- Rate limits, quotas, backups, restore rehearsal, observability, audit export
  and incident runbooks.
- Feature-flag rollout, usage funnel, error budgets and support diagnostics.
- Accessibility, browser compatibility and mobile review/comment hardening.
- Removal of old write paths only after export equivalence and adoption gates.

Acceptance:

- Migration and restore rehearsals preserve source files, SongIR artifacts and
  prior exports.
- A rollback disables new editor writes without losing committed revisions.
- Security tests cover role changes, revoked sockets, invitation tokens,
  artifact authorization, BYOK isolation and LLM SSRF boundaries.
- Editor activation, first edit, collaboration and first export are measurable
  without collecting score content.

## 5. Parallel music-quality tracks

These are ongoing quality tracks, not alternate product milestones. They use
ScoreDocument and the command/proposal boundary as those become available.

### Q1 — export trust and task reliability (P0)

- Persist artifact hash, exporter version, compatibility status and warnings.
- Make exports content-addressed by revision hash, format, exporter/profile and
  pinned versions.
- Automate the mixed-score PyGuitarPro + AlphaTab gate; retain Guitar Pro 8 as a
  release smoke test.
- Add recoverable workers, real stages, LLM attempt ledger, bounded retry,
  circuit breaker and idempotency.

### Q2 — tuning and professional fingering (P0)

- Top-K per-track tuning/capo inference with calibrated evidence and override.
- Phrase-global position optimization by movement, continuity, chord shape,
  stretch, tempo, role and approved priors.
- First gates: guitar recall >=99%; rhythm regression <=0.5 percentage point;
  exact string position >=65%; chord-shape agreement >=65%; zero accepted hard
  playability errors.

### Q3 — evidence-based techniques (P0)

- Recover let ring, staccato, palm mute, hammer/pull and slide before more
  ambiguous bend/vibrato/grace behavior.
- First gates: overall precision >=30%, recall >=10%, F1 >=15%, with no note,
  rhythm, fingering or hard-validation regression.

### Q4 — instrument depth (P1)

1. Bass-specific position, articulation and performance behavior.
2. Drum family-equivalent evaluation, cymbal/tom roles, sticking, accents,
   ghost notes, flams and open/closed hi-hat without regressing the fixed gate.
3. Keys pedal, voice-leading, crossing and hand/finger behavior.
4. Generic instrument plugins only when a typed physical/notation model exists.

### Q5 — governed self-learning (P1)

- Complete rights, review, hash and leakage-safe split inventory.
- Add candidate diff/evidence and promotion decisions to an admin workspace.
- Promote only independent non-regressing snapshots; preserve rollback.

### Q6 — performance and sound profiles (P2)

- Version and validate performance/sound-profile schemas.
- Learn timing/dynamics/gate profiles by style and instrument.
- Add a sound library only through the registry and mapping test harness after
  editor and score gates are stable.

## 6. Immediate development batch

E0-A through E0-C, E1-A/E1-B, the expanded E1-C musical editing surface and
the E1-D typed track-surface foundation are complete locally. Do not reopen
those contracts through ad hoc UI state or renderer objects. The active
reviewable batch is **E1 qualification and remaining professional notation**.

**Outcome:** a musician can select a deterministic score range, edit a complete
beat or measure without leaving the editor, and export the exact committed
result in every currently supported interchange format.

Completed in the current foundation slice:

- deterministic beat navigation, shift-extended range selection, selection
  restoration after authoritative rerender and atomic range operations;
- typed add/delete chord-note, last-note-to-rest and rest-to-note conversion,
  duration/voice changes and selected-note/range transpose;
- direct multi-digit fret entry for guitar/bass with string-caret movement and
  physical fret/tuning validation;
- typed palm mute, let ring, staccato, accent and ghost-note toggles with
  forward/reverse reference validation;
- atomic aligned measure insert/duplicate/delete across every track, including
  notation/performance/global-map timeline shifts and exact inverse undo;
- contextual drum-kit input with conventional hand/foot voices, chromatic
  keys/generic input and family-specific input validation;
- bend, natural harmonic and vibrato controls plus same-string, ordered
  hammer-on, pull-off and slide links, with AlphaTab projection and GP5
  parse-back coverage;
- persistent AlphaTab renderer/player lifecycle so accepted edits rerender the
  score without reloading the soundfont.
- exact dot/triplet duration editing, validated paired same-lane ties and
  dynamics that atomically update notation plus performance velocity;
- AlphaTab/GP5/MusicXML projection for the supported semantics, tie-aware
  humanized MIDI playback/export, and GP5/MusicXML/MIDI exports pinned to the
  visible committed revision with an explicit exported-revision receipt.
- typed aligned track creation, safe empty-track deletion and exact reorder
  undo; editable name, MIDI program and notation mode; playable pitch-preserving
  tuning/capo changes; and persisted mute/solo/volume/pan projected into
  AlphaTab, GP5 and humanized MIDI where the format supports them.
- production-browser qualification of the 104-measure/five-track fixture with
  lazy SVG rendering, last-system stable-ID selection, end playback and
  variable-tempo cursor synchronization.
- exact selected-passage loop ticks, relative playback speed and metronome state
  that persist through an accepted edit and rerender; changing tracks clears the
  selection and disables its loop without resetting the other transport state.
- searchable command execution for editing, navigation, transport and export;
  count-in, direct bar-number navigation and notation zoom that preserves the
  current selection and transport state through a renderer-only update.
- page and continuous horizontal notation layout switching without changing
  the canonical score or rebuilding the player.
- same-track beat cut now copies the typed beat to the editor clipboard and
  deletes it as one revision; undo restores the exact committed beat.

Remaining implementation order:

1. **Performance closure:** profile the foreground local-feedback path on the
   reference device and reduce the 104-measure accepted-save acknowledgement
   from the current five-save median of 883.7 ms (741.0–997.5 ms range) toward
   the 500 ms objective without weakening immutable revision guarantees. Narrow
   field commands already use an equivalence-tested incremental validator;
   canonical serialization and durable storage of the roughly 2 MB snapshot
   are now the primary optimization target.
2. **Notation depth:** add double dots/custom and nested tuplets, partial-chord
   ties, grace notes, beam controls and score-level clef/key/time editing as
   typed operations, prioritized by real musician workflows and corpus evidence.

E1-C acceptance:

- refresh restores the committed musical content and a valid selection anchor;
- one transaction can edit a chord or measure atomically and one undo restores
  the previous canonical document hash;
- illegal overlaps, impossible frets and invalid drum voices are rejected
  before persistence with an actionable inspector message;
- guitar, bass, drums, keys and generic notation all pass click-to-stable-ID and
  input-to-rerender tests;
- GP5, MusicXML and MIDI exports identify and use the same active revision;
- the 104-measure browser fixture has recorded interaction timings and no
  renderer error for the supported notation subset.

The E1-D command/UI foundation, functional desktop-browser track matrix,
five-family pointer identity matrix and 104-measure renderer/playback scale gate
are complete. The remaining E1 claim is blocked by release-latency qualification
and advanced professional notation depth. Existing repair, humanize and LLM
advice remain available through the legacy workbench, but
collaboration and natural-language score mutation do not begin until the
single-user E1 command surface and revision-pinned exports are complete.

Each item remains a separate reviewable change with contract tests, failure
behavior and rollback. Visual polish accompanies a real workflow and does not
become an independent redesign stream.

## 7. Work deliberately deferred

- End-to-end neural score generation.
- Automatic promotion from the private desktop corpus.
- Full offline concurrent editing.
- Full phone/tablet notation editor.
- Public marketplace, social feed and team billing.
- Supporting legacy `.gtp` 2.21 through an unverified parser.
- Native modern Guitar Pro writing before the canonical editor/export gates.
- More decorative UI before editor state, saving, tasks and conflicts are true.

## 8. Task intake template

Every roadmap task starts with:

```text
Outcome:
User-visible acceptance:
Musical invariant:
Document/command impact:
Collaboration and permission impact:
Affected API/export/migration contracts:
Failure, offline and degraded behavior:
Regression fixture and metric:
Observability:
Non-goals:
Rollout and rollback:
```

A milestone is complete only when acceptance runs through the real product path,
not a benchmark-only or renderer-only demonstration.
