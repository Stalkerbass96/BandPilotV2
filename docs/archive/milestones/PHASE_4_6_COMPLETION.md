# Phase 4–6 completion record

This record defines the implemented and tested product boundary after the
SongIR 2.0 / governed-learning foundation. All new output still comes from one
canonical score; no instrument or exporter introduced a parallel truth model.

## Phase 4 — professional multi-instrument notation

### Independent instrument plugins

- Added BassPilot, KeysPilot, and GenericPilot to the explicit plugin registry.
- Each plugin produces a typed transient pitched working IR and enters SongIR
  through one adapter. None is routed through the guitar repair pipeline.
- Keys-only, bass-only, generic-only, and mixed projects now reach `repaired`
  when their score passes validation instead of being reported as passthrough.
- Impossible physical realizations are preserved as `unresolved_events`; the
  source note is never silently deleted or assigned a fake position.

### Bass realization

- Supports ascending 4-, 5-, and 6-string tuning definitions, with standard
  four-string E–A–D–G as the default and a standard five-string profile exposed
  in code for later UI selection.
- Assigns unique strings for simultaneous notes, enforces fret count and chord
  span, keeps tied fragments on one physical position, and minimizes phrase
  hand shifts/string movement.
- Position weights and span policy come from the approved,
  versioned `bass_kb2_performance` knowledge asset.
- Hard validation independently checks realization kind, tuning, string, fret,
  sounding pitch, finger range, chord string collisions, and chord span.

### Keyboard and generic realization

- KeysPilot quantizes/splits notation, partitions chords between two hands,
  assigns fingers 1–5, keeps each hand within an approved one-octave policy,
  and maps left/right hands to score voices and grand staff.
- Hand limits, split pitch, span, and balance weights come from the approved
  `keys_kb2_performance` knowledge asset.
- GenericPilot preserves quantized standard-notation pitch/timing and source
  performance for instrument families without a physical realization model.
- Validation checks keyboard realization, hand/finger presence, simultaneous
  finger uniqueness, note count per hand, and hand span.

### GP5 behavior

- Bass is emitted with its real tuning/string/fret realization and bass MIDI
  program.
- Keys and generic pitched tracks are retained in GP5 with a read-only,
  pitch-preserving virtual-string serialization view. This is a GP5 container
  limitation, not a second score model; the exporter emits a warning and
  MusicXML is the preferred native grand-staff interchange format.
- Parse-back regression verifies the produced multi-instrument `.gp5` is
  readable and retains every supported track.

## Phase 5 — MusicXML 4.0 interchange

- Added a strict `musicxml` SongIR exporter and API/UI export option.
- Emits score parts, measure/time data, exact duration divisions, rests,
  voices, chords, ties, pitch spelling, MIDI instrument metadata, drum
  unpitched notation, keyboard staves/clefs, and technical string/fret/finger
  information.
- Guitar/bass techniques supported by SongIR are serialized as technical,
  articulation, slide, hammer/pull, or ornament notation where applicable.
- The exporter validates SongIR before writing and does not quantize, repair,
  transpose, or invent score events.
- XML parse-back and structural assertions cover part count, note count,
  fretted technical data, and keyboard fingering.

## Phase 6 — humanized performance and sound-profile output

### Generic humanized MIDI

- Added multi-track type-1 MIDI export with a conductor track, tempo/time
  signatures, per-part GM programs, percussion channel handling, stable note
  ordering, and no retriggering of notation-only tie continuations.
- Humanization blends bounded source deviation with score timing, then applies
  chord-coherent microtiming, metrical accents, bounded velocity variation,
  and duration gate shaping.
- The approved `natural-band-v1` profile is a versioned knowledge asset rather
  than a code-only set of musical priors.
- Hash-based variation makes output byte-for-byte reproducible for the same
  SongIR, knowledge snapshot, and profile seed.

### Ample Guitar Eclipse

- Retained the source-preserved `ample_eclipse_midi` path.
- Added `humanized_ample_eclipse_midi`: it derives a temporary performance
  layer with `natural-band-v1`, then applies the existing Eclipse keyswitch and
  controller profile. Canonical SongIR is never mutated.
- Both source-preserved and humanized variants are exposed in the export UI.

## Product/API surface

The canonical export format IDs are:

- `gp5`
- `musicxml`
- `humanized_midi`
- `ample_eclipse_midi` (`ample_midi` remains the public compatibility alias)
- `humanized_ample_eclipse_midi`

The export page now presents notation, interchange, band-performance, and
Eclipse-specific choices and uses format-correct filenames/media types.

## Verification snapshot

- Backend Ruff: passed.
- Backend test suite: 533 passed, 6 opt-in external-corpus tests skipped.
- Backend statement coverage: 81.19%; the 80% gate passed.
- New Phase 4–6 modules have focused coverage between 87% and 100%.
- MusicXML, humanized MIDI, and GP5 outputs pass real parser round trips.
- Frontend tests: 3 passed.
- Frontend TypeScript and Vite production build: passed; existing bundle-size
  advisory remains non-blocking.

## Deliberate next research boundaries

These are not represented as completed product capabilities:

- Pedal inference and advanced keyboard articulation learning.
- Corpus-derived bass/keyboard fingering priors replacing the conservative
  approved seed policies.
- Sound profiles beyond Ample Guitar Eclipse and a governed UI/API for learning
  and promoting new sound-profile mappings.
- Distributed repair workers/cancellation and a learned neural fingering model.

They must use the same candidate/evaluation/promotion governance, strict SongIR
validation, deterministic regression fixtures, and rollback requirements.
