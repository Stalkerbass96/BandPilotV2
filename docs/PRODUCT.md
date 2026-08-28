# BandPilot product contract

This document is the current product source of truth. It replaces the separate
FretPilot, StickPilot, stream-separation, learning-loop and frontend PRDs. The
historical documents remain in `docs/archive/` for decision provenance.

## 1. Product definition

BandPilot is a cloud workspace for creating, repairing, editing and rehearsing
professional band scores. Its primary experience is a fast, keyboard-friendly
score editor with the practical depth musicians expect from Guitar Pro, plus
two cloud-native advantages:

1. several musicians can edit, review and comment on the same score;
2. a musician can select a passage and describe a change in natural language.

The existing MIDI-to-score system remains a differentiating engine inside the
editor. Import repair, instrument realization, knowledge retrieval,
humanization and export become reversible editor tools instead of a separate
conversion wizard.

The product promise is:

> Turn musical intent or an imperfect MIDI arrangement into one shared score
> that is readable, playable, editable and reproducible.

### Current and target states

- **Current baseline:** project-level MIDI import, track detection, asynchronous
  repair, SongIR 2.0 compatibility, ScoreDocument revision history, the first
  AlphaTab-backed beat-editing slice with note/rest input, duration,
  delete/copy/cut/paste and session undo/redo, playback practice controls,
  command palette, bar navigation, zoom and page/horizontal layout, pinned GP5
  plus legacy MusicXML/MIDI exports, humanization, Ample Eclipse mapping, BYOK
  LLM assistance and governed knowledge evaluation.
- **Target experience:** the project opens directly into an editable score;
  repair and AI changes are previewable command transactions; every accepted
  change is autosaved, versioned, collaborative and exportable.

The target state is a staged migration. The initial editor exists; descriptions
of complete Guitar Pro-level editing, proposals or collaboration do not imply
those later layers are implemented.

## 2. Target users and core jobs

### Primary users

- Guitarists and band musicians who need practical rehearsal parts from MIDI.
- Arrangers who create and maintain multi-instrument scores with TAB,
  conventional notation and performance detail.
- Producers who need repeatable Guitar Pro, MusicXML and humanized MIDI output.
- Bands and teachers who need shared editing, review, comments and version
  history without passing files around.

### Jobs to be done

- “Make this imported MIDI look and feel like a musician prepared the score.”
- “Let me correct notes, rhythm, fingering, techniques and layout without
  fighting the tool.”
- “Let the band work on the same authoritative arrangement.”
- “Change this passage from a written instruction, then let me hear and inspect
  the result before accepting it.”
- “Export the exact reviewed version in the format needed by the next tool.”

## 3. Primary product journey

1. The user creates a project, names it and chooses a blank score or MIDI
   import. The desktop-web experience is the primary editing target.
2. On MIDI import, BandPilot stores the original file immutably and creates an
   immediately editable import revision. Track detection runs automatically;
   the user is asked to correct instruments only when confidence is low or the
   detected band is wrong.
3. “Prepare score” applies the existing repair and knowledge pipeline in the
   background. It creates a proposed revision and a plain-language change
   summary; it never overwrites the source or blocks the editor.
4. The project opens and returns to the score editor, not a processing report.
   The user can edit manually, play a selection, compare/revert prepared
   changes, invoke humanization and resolve blocking score issues.
5. The user may invite collaborators as editor, commenter or viewer. Presence
   and selections are live; accepted score commands and comments are durable.
6. The user may select a note, beat, passage, measure range or track and ask AI
   for a bounded change. BandPilot validates the proposal, shows a notation
   diff and offers A/B playback before a single atomic Apply action.
7. The user exports a pinned score revision. Guitar Pro is the recommended
   rehearsal output; MusicXML, humanized MIDI and sound-library profiles are
   available without creating a second score truth.

### Journey rules

- Project creation and import are short entry flows; the editor is the product
  home after a project exists.
- No full-screen pipeline page is required for normal use. Long jobs appear as
  resumable tasks in the editor and survive refresh or disconnect.
- Every automated change is visible, attributable, reversible and applied to a
  named revision.
- The original upload is immutable and this reassurance is visible.
- The last opened project, score position, track focus and view mode are
  restored when practical.
- Errors state what happened, whether music is safe, and the next action.
- Advanced diagnostics and provenance are available, but never compete with
  the score for attention.

## 4. Editor experience contract

### Workspace anatomy

```text
Project bar: title · save/sync state · undo/redo · collaborators · share · export
Transport:   play/stop · count-in · metronome · loop · tempo · playback cursor
Track rail:  add/reorder · instrument · mute/solo · notation mode · mixer
Score:       notation/TAB canvas · caret · range selection · remote selections
Inspector:   context controls for the current note/beat/range/track
Assistant:   prompt, proposal diff, validation, A/B preview and Apply/Reject
```

The score is always the dominant surface. The inspector and assistant are
contextual panels, not permanent forms. Dense controls use toolbars, palettes
and shortcuts; uncommon options use progressive disclosure.

### Selection model

Selection is a first-class product object shared by manual editing, playback,
comments and AI:

- caret or insertion point;
- note or chord;
- beat/event;
- contiguous musical range;
- one or more measures;
- track, staff or whole score.

Selections remain anchored to stable score entity IDs and exact musical
positions rather than screen coordinates. When an edit removes an anchor, the
UI resolves it to the nearest valid musical boundary and tells the user when a
comment or AI proposal became stale.

### Interaction principles

- Direct score and TAB entry, arrow-key navigation, copy/cut/paste and undo/redo
  are first-class; a user should not need an inspector for routine note entry.
- Mouse, trackpad and keyboard workflows must be equivalent for core editing.
- A command palette exposes actions and teaches shortcuts.
- One user action produces one understandable undo step, including repair and
  AI batches.
- Autosave communicates `saving`, `saved`, `offline` and `conflict`; it
  never uses a false success state.
- Playback, loop and metronome work on the current selection and remain usable
  while inspecting the score.
- Mobile initially supports project access, playback, presence, comments and
  approval. Full notation editing is a desktop-browser goal, not an initial
  mobile promise.

## 5. Functional scope

“Align with Guitar Pro” means professional workflow and notation coverage; it
does not mean cloning every menu or proprietary sound engine in the first
release.

### Editor foundation

- Multi-track score with reorder, add/remove, instrument and notation view.
- Guitar and bass standard notation + TAB; five-line drum staff; keyboard grand
  staff; standard staff for other pitched instruments.
- Note/rest input, pitch, string/fret, durations, dots, ties, tuplets and voices.
- Insert/delete measures; time signature, key signature, clef and tempo.
- Copy, cut, paste, move, transpose, repeat, undo and redo.
- Track tuning, capo, mixer volume/pan, mute/solo and playback focus.
- Zoom, page/horizontal layout, measure navigation and command palette.
- Core techniques already represented by BandPilot, including hammer/pull,
  slide, bend, vibrato, palm mute, let ring, staccato, accent and ghost notes.
- Playback, count-in, metronome, loop and relative tempo.

### Professional depth after foundation

- Repeats/endings, rehearsal marks, directions, dynamics, text, chord names,
  diagrams and lyrics.
- Grace notes, tremolo, rolls/flams, drum articulation palette, piano fingering
  and sustain pedal.
- Nested tuplets, advanced beaming/stem control, stylesheet, design mode,
  print/graphic export and audio-track synchronization.
- The roadmap owns release order and acceptance gates.

## 6. Existing intelligence as editor tools

| Tool | Editor behavior |
|---|---|
| Import cleanup | Creates an editable import revision; source MIDI remains immutable. |
| Prepare score | Runs repair/realization and returns a reviewable batch transaction. |
| Make playable | Optimizes instrument-specific fingering, voices and techniques within the selection or track. |
| Humanize | Primarily changes the performance layer/profile, not visible notation. |
| Validate | Shows blocking musical errors at their score locations and offers bounded fixes. |
| Export | Uses a selected committed revision and performance profile. |
| Learn/evaluate | Improves governed knowledge offline; never silently changes an open project. |

Product modes remain available as intent presets:

| Mode | Meaning |
|---|---|
| `faithful` | Preserve source pitches and structure; repair notation and physical realization only. |
| `playable_arrangement` | Permit bounded changes needed for practical performance; recommended default. |
| `creative_rewrite` | Permit explicit, policy-bounded musical rewriting within the selected scope. |

No mode bypasses hard musical validation.

## 7. Collaboration contract

- A project has one owner and project-level roles: `editor`, `commenter` and
  `viewer`. The data model stays ready for team workspaces, but team billing and
  organization administration are not required for the first collaborative
  release.
- Editors can issue score commands. Commenters can anchor threads to score
  entities/ranges. Viewers can inspect, play and export only when allowed.
- Presence, cursors and transient selections are ephemeral. Score commands,
  comments, permissions, versions and audit events are durable.
- Concurrent non-overlapping edits merge. Conflicting edits to the same
  musical field are never silently resolved by last writer wins.
- Undo reverses the actor's accepted transaction against the current revision;
  it does not rewind another musician's unrelated work.
- Initial collaboration is online-first. Offline edits and automatic merge are
  a later feature; reconnect must still recover all server-accepted work.

## 8. Natural-language editing contract

The default flow is **preview, then apply**:

1. The user selects a scope and enters an instruction.
2. BandPilot pins the base revision and sends only the selected music, limited
   surrounding context, instrument constraints and relevant knowledge.
3. The model returns a typed edit proposal, never executable code or a raw
   replacement document.
4. Deterministic code applies the proposal to an isolated candidate, computes
   fingering/notation details and runs hard validation.
5. The editor shows changed measures, a semantic summary, warnings and A/B
   playback. Apply commits one transaction; Reject changes nothing.
6. If the score changed meanwhile, the proposal is rebased only when safe;
   otherwise it is marked stale and must be regenerated.

Initial supported intents are bounded and testable: clean rhythm, simplify a
passage, redistribute voices, transpose within range, optimize fingering,
adjust techniques/dynamics and humanize performance. Creative note generation
requires `creative_rewrite`, an explicit selection and the same review gate.

LLM failure never blocks manual editing. BYOK credentials and provider data
belong to the requesting user and are not shared with collaborators.

## 9. Canonical outputs

| Format ID | User value | Contract |
|---|---|---|
| `gp5` | Guitar Pro score and TAB | Must open in Guitar Pro 8 and parse in AlphaTab/PyGuitarPro. |
| `musicxml` | Native notation interchange | Preferred for keyboard grand staff and notation applications. |
| `humanized_midi` | Multi-track band performance | Deterministic for the same revision, knowledge and profile. |
| `ample_eclipse_midi` | Eclipse keyswitch performance | Source-preserved performance mapping. |
| `humanized_ample_eclipse_midi` | Humanized Eclipse performance | Humanized layer followed by Eclipse mapping. |

`ample_midi` remains an API compatibility alias for
`ample_eclipse_midi`. GP and MusicXML are interchange/export formats, not the
collaborative storage model.

## 10. Product invariants

- One versioned score document is the editable truth. SongIR 2.0 remains the
  current compatibility contract until the ScoreDocument 3.0 migration in
  `ARCHITECTURE.md` is complete; no feature may create a parallel score truth.
- Score time uses exact rational positions in the target editor model. Display
  pixels, MIDI floats and renderer object identity are not document identity.
- Every editable entity has a stable ID, and every accepted change records
  actor, origin, base revision, operations, validation and inverse behavior.
- Every source note is represented or explicitly unresolved; silent deletion
  and fabricated physical realization are forbidden outside an explicit
  creative operation.
- Guitar/bass pitch equals tuning plus fret on the assigned string. Simultaneous
  notes may not collide on a physical string or exceed approved hand/chord
  constraints.
- Drum parts use a five-line percussion staff without TAB. Hands/cymbals use
  voice 1/up-stems; kick and pedal hi-hat use voice 2/down-stems. Exact source
  GM pitches remain intact through score export.
- Drum note-off gates remain performance data. Written drum durations may not
  overlap the next onset in the same voice or cross the barline.
- Linked techniques reference valid, ordered and physically compatible notes.
- Exporters serialize a validated pinned revision; they do not repair it.
- Repair, humanization and LLM output are proposals. Deterministic policy and
  hard validation keep authority; acceptance always belongs to an authorized
  user or an explicitly configured automatic policy.
- Learned knowledge is traceable, licensed, split-safe, reversible and inactive
  until an independent no-regression gate passes.

## 11. Project and task states

Project rows identify the current document and latest committed revision.
Long-running import, preparation, AI, evaluation and export work uses durable
tasks with one shared state vocabulary:

- `queued`: accepted but not started;
- `running`: active and safe to leave;
- `needs_review`: produced a proposal requiring a user decision;
- `succeeded`: committed or produced its validated artifact;
- `partial`: useful output exists with explicit unresolved items;
- `failed`: no acceptable output was produced;
- `cancelled`: cancellation was acknowledged before commit.

Current repair API compatibility statuses (`processing`, `repaired`, `partial`,
`failed`) remain until clients migrate. The architecture defines their mapping.

## 12. Success metrics

Metrics are evaluated separately; one composite score must not hide a musical
or collaboration regression.

- **Activation:** project-created-to-score-opened completion, MIDI import
  success, time to first editable score and first meaningful edit.
- **Editing:** command success, input-to-render latency, undo success, autosave
  acknowledgement, validation recovery and crash-free editing sessions.
- **Collaboration:** invite acceptance, shared sessions, propagation latency,
  conflict rate, reconnect recovery and comment resolution.
- **AI editing:** proposal completion, validation pass, apply/reject rate,
  stale-proposal rate, undo-after-apply and time saved by supported intent.
- **Score quality:** note/onset/duration fidelity, playability, string/fret and
  chord-shape agreement, techniques and family-specific notation quality.
- **Export trust:** reproducible artifact hash, parser/application
  compatibility, first-export success and warning recovery.
- **Performance:** humanization preference, deterministic profile output and
  sound-library controller correctness.
- **Learning governance:** rights-clear coverage, split leakage, candidate A/B
  evidence and rollback reproducibility.

Current baselines and milestone targets live only in
[`ROADMAP.md`](./ROADMAP.md).

## 13. Deliberate non-goals

- Rebuilding a complete engraving engine before the AlphaTab adapter spike
  proves it insufficient.
- Pixel-for-pixel or menu-for-menu cloning of Guitar Pro.
- End-to-end LLM document generation or allowing a model to bypass typed
  commands and validation.
- Full offline collaborative editing in the first collaboration release.
- Full professional score editing on phones in the first editor release.
- Public marketplace, social feed, team billing or rights-unknown score sharing.
- More sound-library profiles before editor, score and export gates are stable.

## 14. Confirmed product decisions

The product owner confirmed these decisions on 2026-08-26:

1. desktop browser is the primary editor; mobile is review/comment/playback;
2. AI shows a diff and requires Apply rather than mutating instantly;
3. collaboration starts with project invites and roles, while remaining
   workspace-ready in the schema;
4. the first editor release supports blank score and MIDI import; Guitar Pro and
   MusicXML import follow after the canonical editing model is stable.
