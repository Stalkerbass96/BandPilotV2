# FretPilot v2

Repair AI-generated guitar MIDI into playable, notatable professional output.

FretPilot takes messy AI-generated guitar MIDI and produces two outputs:
1. **Guitar Pro 5 (.gp5)** — a clean, notatable score
2. **Ample Guitar Eclipse MIDI (.mid)** — a playable MIDI with keyswitches

## Architecture

```
backend/          Python FastAPI + 7-stage repair pipeline
  src/fretpilot/
    api/          FastAPI routes (auth, byok, projects, exports, tunings)
    ai/           LLM decision layer (shadow advisor, BYOK encryption)
    db/           SQLAlchemy ORM (User, ByokConfig, Project, ExportRecord)
    detection/    3-layer guitar track classifier
    engine/
      cleanup.py    Pre-processing: tempo dedup, velocity remap, overlap truncation, tuning detect
      stages/       7-stage pipeline (quantize → assemble)
    exporters/    GP5 + Ample MIDI exporters (read-only IR consumers)
    guitar/       Fretboard physics (tuning, candidate positions)
    ir/           IR Schema 1.0 (frozen dataclass contract)
    knowledge/
      tunings.py    Guitar tuning registry + auto-detect + preference logic
      registry.py   KB1-4 snapshot loading + query
      engine.py     Rule engine (priors application)
      assets/
        guitar_tunings.json  12 tuning profiles (standard, Drop variants, open tunings)
        kb1_arrangement.json — kb4_instruments.json (KB1-4 priors)
    midi/         SMF parser + GM program lookup
frontend/         Vite + React 18 + TypeScript + MUI 5 + Tailwind CSS
```

### Dependency Graph (static, no cycles)

```
api → engine → ir / knowledge / midi
         ↘     ↗
          guitar
exporters → ir (read-only)
```

### IR Schema 1.0

The IR is the frozen core contract. All dataclasses use `slots=True`.
ScoreTiming (notation) and PerformanceTiming (source MIDI) are separated.

### 7-Stage Pipeline

| Stage | Name         | Responsibility                                      |
|-------|-------------|------------------------------------------------------|
| S1    | Quantize     | Snap note onsets/durations to a rhythmic grid       |
| S2    | MeasureSplit | Split notes at measure boundaries (tie flags)       |
| S3    | Tie          | Identify legato candidates (same-pitch consecutive) |
| S4    | Voice        | Promote unequal chord releases to voice 2           |
| S5    | Fingering    | Assign string/fret/hand-position via KB2 scoring    |
| S6    | Articulation | Infer palm_mute/staccato/let_ring/hammer_on/pull_off|
| S7    | Assemble     | Build the final GuitarProjectIR                     |

Each stage is ≤80 lines, independently testable, and connected via `PipelineContext`.

### Cleanup & Pre-Processing

Runs before the repair pipeline (`engine/cleanup.py`). Every action is traceable via `CleanupAction`:

- **Tempo deduplication**: Merges redundant tempo events (BPM diff < 0.1) into a single event. Tokyo Midnight Highway: 195 → 1.
- **Auto-detect tuning**: Matches note pitch ranges against 12 guitar tuning profiles via `TuningRegistry.best_match()`, preferring fewer strings and fewer deviations from standard tuning when coverage is similar.
- **Velocity remap**: When all velocities are identical (zero variance, < 5.0), generates a dynamic curve based on beat position — strong beat (+20) > weak beat (+10) > even beat (base) > off-beat (−10).
- **Overlap truncation**: Truncates overlapping same-channel same-pitch notes; preserves chord overlaps (different pitches) for voice separation.
- **Out-of-range pitch handling**: Notes outside the detected tuning's range are flagged for GP5 voice 2 separation, enabling easy batch-select and delete in Guitar Pro.

### Tuning System

- 12 tuning profiles stored as JSON (`knowledge/assets/guitar_tunings.json`): Standard 6/7/8-string, Drop D/A/C/B, DADGAD, Open G/D, half/full step down.
- `TuningRegistry.best_match(notes, coverage_tolerance=0.005)` selects the tuning with the highest pitch coverage; ties are broken by `(string_count, deviation_count, -coverage)` — fewer strings and fewer deviations win.
- Users can override auto-detected tuning via the `tuning_id` parameter in the repair API (`POST /api/projects/:id/repair`).
- `GET /api/tunings` exposes the full catalog for the frontend selector.
- Frontend tuning selector on WorkbenchPage (defaults to "Auto-detect").

### Adaptive Quantize

- `_shortest_significant_duration()` finds the shortest duration above a noise threshold (0.06 beats), ignoring notes that make up < 1% of the total.
- `_grid_step_for_duration()` ensures the grid step is not coarser than the shortest significant duration (selects from 1.0 / 0.5 / 0.25 / 0.125 beats).
- `QuantizeStage.run()` refines the style-selected grid if the required step is finer, emitting a warning. This prevents 16th notes from being swallowed by 8th-note grids in rock/metal style detection.

### GP5 Export Enhancements

- **Placeholder fingering** (`_placeholder_fingering()`): out-of-range pitches get a placeholder (string, fret) for voice 2 display — negative frets are clamped to 0, >24 fret preserved with warning.
- **Same-string dedup** (`_chord_fingerings()`): when chord notes resolve to the same string, the first is kept and duplicates are dropped with a warning — guarantees a valid .gp5 that Guitar Pro can always read.
- **Tie layering** (`_populate_beat_group()`): same-onset chords with different durations use parallel tie beats grouped by distinct duration (not serial sequential beats), preventing measure overflow (red measures in GTP).

### Knowledge Base (Data-as-Code)

All priors are stored as versioned JSON assets (not Python dicts):
- `kb1_arrangement.json` — style priors (metal/rock/pop/funk)
- `kb2_performance.json` — fingering priors per style + role
- `kb3_notation.json` — GP5 and MIDI notation conventions
- `kb4_instruments.json` — Ample Eclipse + SC instrument profiles

`KnowledgeRegistry` loads and validates; `KnowledgeEngine` applies rules.

### LLM Decision-Only Pattern

The LLM only outputs decisions (style label, rewrite suggestions).
Deterministic code validates every decision via `validate_decisions()`.
If no LLM is configured, `ShadowRewriteAdvisor` falls back to rule-based inference (degraded mode).

## Setup

### Backend

```bash
cd backend
pip install -e ".[dev]"

# Set environment variables (or create .env)
export FRETPILOR_DEBUG=true
export FRETPILOR_JWT_SECRET="your-secret-here"
# Optional: generate a Fernet master key for BYOK encryption
python -c "from fretpilot.ai.crypto import KeyVault; print(KeyVault.generate_master_key())"

# Run the server (PYTHONPATH=src is required; --reload is intentionally
# omitted — restart manually after code changes)
PYTHONPATH=src uvicorn fretpilot.app:create_app --factory --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev    # starts on http://localhost:5173
```

The Vite dev server proxies `/api` requests to `http://localhost:8000`.

## Testing

```bash
cd backend
python -m pytest tests/ -v
```

289 tests across 17 test files:

- `test_ir_roundtrip.py` — IR serialization/deserialization consistency
- `test_ir_schema.py` — IR schema field validation
- `test_pipeline_stages.py` — each of the 7 stages tested independently
- `test_midi_parser.py` — SMF parsing, note resolution, diagnostics
- `test_detection.py` — 3-layer guitar track classifier
- `test_exporters.py` — GP5 parse-back + Ample MIDI output verification
- `test_api.py` — auth, BYOK, projects, exports endpoints
- `test_dirty_midi.py` — dirty MIDI edge cases (illegal key signatures, etc.)
- `test_tokyo_midnight.py` — Tokyo Midnight Highway sample pipeline verification
- `test_pipeline_tokyo_midnight.py` — full pipeline integration test on Tokyo Midnight
- `test_tuning_preference.py` — tuning auto-detect + preference logic (fewer strings/deviations)
- `test_multivoice.py` — out-of-range notes separated to voice 2
- `test_quantize_adaptive_grid.py` — adaptive quantize grid preserves 16th notes
- `test_gp5_tie_layering.py` — GP5 tie layering for chord unequal durations
- `test_qa_incremental.py` — QA regression suite for incremental features
- `test_qa_boundary.py` — QA boundary condition tests
- `golden/test_golden.py` — golden sample tests (SoD)

All tests use mock LLM advisors — no real API calls are made.

## Key Design Decisions

1. **No god functions** — every function is ≤80 lines
2. **No compatibility shims** — clean v2 codebase
3. **Data-as-code** — all priors are JSON assets, not Python dicts
4. **Static dependency graph** — no import cycles
5. **IR Schema 1.0 frozen** — changes require explicit version bump
6. **LLM only decides** — deterministic code validates + executes
7. **Exporters read-only** — never modify the IR
8. **BYOK encryption** — Fernet symmetric encryption for API keys
