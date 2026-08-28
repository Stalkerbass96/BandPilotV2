# E0 AlphaTab editor spike evidence

Date: 2026-08-27

This is repeatable technical evidence, not a product or architecture source of
truth. The binding decisions remain in `ARCHITECTURE.md` and `ROADMAP.md`.

## Question

Can AlphaTab remain behind BandPilot's renderer/player adapter for the first
editor slice without becoming the persisted document or editing model?

## Probe

The isolated probe lives under `frontend/spikes/alphatab-editor/` and is not
part of the production app entry point. It builds an AlphaTab model directly;
it does not generate or load GP5.

Reference score:

- AlphaTab 1.8.4, MPL-2.0;
- 104 measures;
- five tracks and six staves: guitar standard+TAB, bass standard+TAB,
  five-line/two-voice drums, keyboard treble+bass and generic standard staff;
- 2,912 beats and 2,912 notes;
- external maps from AlphaTab numeric IDs to stable BandPilot beat/note IDs.

Repeatable commands:

```bash
cd frontend
pnpm run probe:alphatab
pnpm exec tsc -p spikes/alphatab-editor/tsconfig.json
pnpm exec vite --config spikes/alphatab-editor/vite.config.ts
```

The browser probe exposes note/beat mouse events, selected stable ID, note-bound
count, initial/rerender timing, MIDI/tick-cache readiness and a one-note mutation
followed by `renderScore`.

## Measured evidence

The headless AlphaTab model probe completed with:

| Signal | Result |
|---|---:|
| Master bars | 104 |
| Tracks / staves | 5 / 6 |
| Stable mapped beats / notes | 2,912 / 2,912 |
| Core model finish on this machine | 20.36 ms |
| Stable-ID mutation | guitar note changed from MIDI 64 to 65 |
| Probe production bundle | 1,153.28 kB / 276.38 kB gzip |

The timing is diagnostic, not a supported service objective. It measures model
finalization, not full SVG layout or browser paint.

Type declarations and the compiled package confirm:

- programmatic Score/Track/Staff/Bar/Voice/Beat/Note construction;
- standard/TAB, percussion and multiple staves;
- `boundsLookup` down to optional note-head bounds;
- beat and note mouse-down/move/up events;
- `renderScore`, range highlighting, player readiness, MIDI loading and tick
  lookup;
- mutable note/string/fret/pitch state followed by rerender.

The first browser run exposed an asset-path failure. A later production-browser
run exposed the deeper cause: hand-copying Bravura and SONiVOX allowed SVG
rendering but did not configure AlphaTab's Web Worker and AudioWorklet entry
points, so playback never became ready. The frontend now uses the official
`@coderline/alphatab-vite` integration documented by AlphaTab:
<https://www.alphatab.net/docs/getting-started/installation-vite>.

The repeatable desktop run against a blank guitar project then verified:

- the score shell and packaged Bravura font render without a GP5 round trip;
- creating the first note commits revision 1 with its required performance
  event and rerenders immediately;
- written-duration edit and explicit-rest insertion commit revisions 2 and 3;
- clicking the rendered TAB number resolves to the persisted stable note ID;
- the SONiVOX soundfont, worker and worklet initialize, Play transitions to
  Pause, and Stop remains available;
- a duration edit, compensating undo and semantic redo commit revisions 4–6;
- same-track beat copy/paste commits revision 7 with new stable beat/note and
  performance-event IDs;
- reloading the authoritative revision preserves both notes and the explicit
  rest.

The Editor Core Reset browser regression continued the same project through
revision 15 and verified:

- typing a fret updates the selected string, while moving the string caret and
  typing adds an individual chord tone with a matching performance event;
- a subsequent direct fret edit reached accepted revision and rerender in
  685 ms on this machine, including the intentional 420 ms multi-digit input
  buffer; this is an end-to-end diagnostic, not the local-feedback target;
- Shift+Arrow produces a deterministic two-beat range and one voice command
  commits the range atomically;
- typing `12` into an explicit rest converts it into a playable note, and one
  compensating undo restores the rest;
- palm mute persists as a typed technique and projects to AlphaTab notation;
- a +1 semitone transpose preserves the selected string, advances the fret and
  commits revision 15;
- Play remains ready after each document rerender because the renderer/player
  instance and soundfont are no longer recreated per edit;
- the full-screen two-row edition toolbar measured 1280 px client/scroll width
  and 92 px client/scroll height at the tested desktop viewport, so no command
  group was hidden by accidental toolbar overflow.

The production build contains separate hashed worker and worklet chunks plus
the packaged font and soundfont directories. Automated adapter tests cover
stable beat/note identity for guitar/TAB, drums and keys. The real-browser
five-family pointer matrix is recorded below; the 104-measure SVG paint matrix
remains a broader qualification gate.

The expanded E1-C automated gate also covers exact duration decomposition,
all-track measure insertion/duplication/deletion with inverse restoration,
drum hand/foot voice input, generic/keys pitch input, and AlphaTab projection
for bends, natural harmonics, vibrato and explicit hammer/slide links. GP5
parse-back verifies the newly exposed direct guitar effects and performance
dynamic bucket. Exact dot/triplet editing, paired ties and written dynamics now
round-trip through the canonical command layer; MusicXML verifies dot,
time-modification, tie and dynamic elements, while humanized MIDI verifies that
a valid tie chain produces one sustained note instead of duplicate attacks.
The track-surface gate additionally covers exact operation serialization/undo,
historical 3.0 hash compatibility, aligned empty-track factories, human-readable
tuning parsing, pitch-preserving capo/retune changes, AlphaTab mixer projection
and GP5 mixer/capo parse-back. The current gate is 616 backend tests (6
authorized-corpus tests skipped) and 50 frontend tests with successful backend
and frontend production builds. These automated checks do not replace the
production-browser evidence below.

## E1-D desktop browser qualification

The production Studio was exercised at a 1440 × 900 desktop viewport. The run
continued the existing guitar fixture from revision 15 through revision 32 and
created a separate five-track export fixture through revision 9. It verified:

- aligned bass, drums, keys and generic track creation alongside guitar;
- first-note input for all five families, direct two-digit bass fret input and
  same-onset drum kick/closed-hi-hat routing to voices 2 and 1 respectively;
- track name, MIDI program and capo changes as one accepted transaction;
- track reorder, semantic undo, redo and authoritative refresh persistence;
- mute and volume changes, while clicking an unchanged slider value no longer
  creates an empty revision;
- accessible names for track reorder and setup controls;
- a true full-height Studio surface rather than content-height collapse on
  sparse scores;
- a fresh five-track revision exporting GP5, MusicXML and humanized MIDI from
  one identical revision hash with five notes in each artifact;
- PyGuitarPro parse-back of all five GP5 tracks in the same order as the
  ScoreDocument, MusicXML with five parts and MIDI with one conductor plus five
  instrument tracks;
- playable default keyboard hand/finger identity, fixing the export-blocking
  missing-finger validation error exposed by the first run.
- direct rendered note-head clicks resolving the exact stable `note:*` ID for
  guitar, bass, drums, keyboard and generic notation. Keyboard grand staff
  needed a bounded fallback because AlphaTab's beat-first lookup can choose the
  bass-staff beat over a treble note at the same horizontal position.

This closes the E1-D functional track-surface and five-family pointer matrices.

## Production 104-measure scale qualification

On 2026-08-28 the production Studio, not the isolated spike, loaded a canonical
104-measure ScoreDocument with five tracks and 2,912 notes. The renderer used
AlphaTab lazy loading, produced a 9,314 px score surface and kept only four or
five nearby SVG systems mounted while scrolling.

Observed desktop diagnostics on this machine:

| Signal | Result |
|---|---:|
| Initial visible SVG render | 116.9–192.8 ms across clean reloads |
| One-note visible-system rerender | 93.3–112.5 ms |
| Bottom-system stable identity | `gate:note:1:104:8` at bar 104 |
| Accepted save acknowledgement, five consecutive saves | 728.2–984.0 ms API, median 866.8 ms / 741.0–997.5 ms total, median 883.7 ms |
| Renderer alerts | 0 |

The final system rendered after scrolling to the 8,807 px scroll limit. Direct
note selection resolved the persisted bar-104 ID, playback placed its cursor in
that final system and terminated normally at the end of the score.

The scale run also exposed and closed a real playback defect: the production
ScoreDocument adapter had ignored `tempo_map`. The adapter now projects every
tempo change to the exact AlphaTab master-bar ratio. A browser fixture rendered
480 BPM at score position 0, 240 BPM at position 2 and 360 BPM at position 4.
Starting from the third note, the visible beat cursor advanced from x=417.3 to
439.7, 518.1, 615.1 and 704.1 px at sampled elapsed times 40, 160, 330, 630 and
810 ms; the bar cursor moved to bar 2 after the second tempo boundary. No player
or renderer error appeared.

The save path now returns the exact accepted revision ID, promotes ordinary
optimistic commands without a redundant 2 MB document GET, verifies immutable
snapshot hashes directly from their canonical bytes, reuses the stored canonical
payload for candidate reconstruction and reuses the command engine's canonical
serialization for persistence. Narrow field-only commands now validate the
affected track and performance events while preserving unrelated diagnostics;
structural, add/delete and technique commands still use full-document
validation. Contract tests compare the incremental and complete diagnostic sets
for valid and invalid changes. The application-internal metric improved from
1,904.5 ms API / 1,918.7 ms total to a best confirmed 856.9 ms API / 870.5 ms
total on the same fixture. A later stabilized five-save sequence measured
728.2–984.0 ms API with an 866.8 ms median and 741.0–997.5 ms total with an
883.7 ms median. One preliminary save was a 1,813.7 ms API / 1,826.5 ms total
outlier. An attempted generic deep-copy replacement regressed to 1.3–1.5 s and
was removed.

The same production fixture now exposes musician-facing transport controls.
A Shift+Arrow three-beat selection produced the exact `0–1440` tick playback
range; 90% relative speed, metronome and looping were active together, and the
visible beat cursor repeatedly wrapped inside the selected passage. A real
string/fret edit committed revision 20 and rerendered in 106.1 ms while all
three transport settings remained active. The run also found an AlphaTab
failure when a stale highlighted Beat object survived a track change. Clearing
the old range highlight before every score render fixed the `realBounds` error;
Guitar -> Bass -> Guitar switching then completed without a stuck loading mask
or a new console error. Changing tracks clears the score selection and therefore
disables selection-looping truthfully, while speed and metronome remain intact.

The functional-priority follow-up added an initial production command palette
backed by the existing edit, navigation, transport, reload and revision-pinned
export handlers. `Command/Ctrl+K` opens the searchable list. Context-invalid
commands remain visible but disabled, while 104 generated bar-navigation
entries stay hidden until a search requires them. In the real browser,
searching `countoff` and pressing Enter enabled AlphaTab count-in, searching
`bar 104` selected the first editable beat of bar 104, and the status bar
reported the same location. The direct Space/Escape/L/M/Shift+M shortcuts
controlled play, stop, selection loop, metronome and count-in respectively.

Notation zoom now uses AlphaTab's settings/update/render path at bounded
75/90/100/110/125/150% presets. Zooming the 104-measure score from 100% to 110%
completed the renderer-only update in 33.4 ms; the bar-104 selection, exact
`395520–396000` loop ticks, count-in and metronome all survived. `Command+0`
restored 100% in 34.6 ms with no loading-mask leak, alert or new console error.

The same view boundary supports Page and Horizontal layout commands. The
104-measure guitar track changed from a 758 × 9,321 px lazy page surface to a
25,909.5 × 290 px continuous horizontal surface in 52.8 ms, then returned to
Page in 37.8 ms. Bar 104 stayed selected and the exact loop range, count-in,
metronome, playback engine and 100% zoom state survived both transitions. No
canonical revision was created because these are user-local view settings.

The same browser gate then exercised the new same-track cut path. Searching the
command palette for `cut selected beat` exposed an enabled `⌘X` action. Running
it deleted the selected bar-104 beat and committed revision 21 with no loading
spinner or alert; the session Undo restored the beat as revision 22, and a
second `bar 104` search resolved the original stable selection anchor. Cut is
implemented as clipboard capture plus one typed `delete_beat` transaction, so
the operation remains a single undo step. The browser runner cannot reliably
dispatch the OS-native Meta+X cut chord to the page, while the same handler is
reachable and verified through the command palette.

This passes the 104-measure renderer, bottom-hit and variable-tempo cursor
qualification for the currently supported notation subset. It does **not**
ratify the release latency objectives. The in-app browser's requestAnimationFrame
selection diagnostic was 118.8–140.9 ms, and the 870.5 ms best confirmed
large-document acknowledgement and 883.7 ms five-save median remain above the
500 ms primary-region objective. Selection is
applied synchronously before the deferred AlphaTab range highlight, but the
50 ms local-feedback target still needs foreground-browser profiling on the
reference device. The incremental validator removes an unconditional full-score
scan, but canonical serialization and durable writes of the roughly 2 MB
snapshot still dominate; asynchronous or incremental storage needs a dedicated
design before E1 performance can be called done.

## Decision

**Keep AlphaTab for E1 behind a strict adapter.** The functional browser gate
for the thin production slice passed. This is not permission to make AlphaTab
objects authoritative or to skip the broader scale/notation matrix.

Required boundaries:

- stable BandPilot IDs remain in an external identity map;
- BandPilot string numbering is explicitly inverted at the AlphaTab boundary;
- gestures emit typed BandPilot commands; they never persist model objects;
- ScoreDocument projects directly to AlphaTab without a GP5 round trip;
- AlphaTab remains dynamically loaded because the probe bundle is large;
- a renderer replacement must not change ScoreDocument or command history.

The E1-A/E1-B production adapter now enforces these boundaries. It maps stable IDs
externally, converts 1-based musician-facing notation voices to AlphaTab voices,
inverts guitar/bass string numbers only at the adapter, decomposes exact
non-atomic durations into tied notation, rejects overlaps instead of shifting
them, and dynamically loads AlphaTab. The official Vite plugin owns the
packaged assets and playback worker/worklet integration.

## Remaining renderer qualification for broader E1

The production scale gate now records range/stable-ID behavior, SVG/rerender
timing, end-of-score playback and variable-tempo cursor synchronization. Before
claiming full professional-editor renderer coverage, the remaining work is:

1. foreground reference-device profiling against the 50 ms local-feedback SLO;
2. percussion-variant, keyboard-grand-staff and complete supported-technique
   visual regression fixtures, rather than relying only on functional and
   adapter tests;
3. large-document persistence work sufficient to meet the 500 ms accepted
   command acknowledgement objective.

Failure of that gate changes the renderer decision to replace AlphaTab behind
the adapter; it does not reopen the canonical model decision.
