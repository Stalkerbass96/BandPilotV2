# BandPilot v2

BandPilot is evolving into a cloud workspace for creating, repairing, editing
and rehearsing professional band scores. Its target product experience is a
Guitar Pro-class browser editor with collaborative editing and safe,
selection-based natural-language changes.

The implemented MIDI-to-score system remains the musical intelligence inside
that editor: instrument separation, practical realization, techniques,
humanization, knowledge retrieval and reproducible export.

## Current product boundary

| Capability | Status |
|---|---|
| MIDI import, physical-track preservation, family detection and manual correction | Implemented |
| Guitar, drums, bass, keys and generic pitched repair | Implemented |
| Canonical SongIR 2.0 and hard playability validation | Implemented |
| GP5 multi-track export and AlphaTab preview | Implemented |
| MusicXML 4.0 export | Implemented |
| Humanized band MIDI | Implemented |
| Ample Guitar Eclipse MIDI, source-preserved and humanized | Implemented |
| BYOK LLM style/rewrite advice with deterministic validation and fallback | Implemented |
| Rights-aware source catalogue, GuitarSet seed priors, governed GP evaluation and candidate snapshots | Implemented baseline |
| ScoreDocument persistence, full-screen Studio, deterministic caret/range selection, all-family note input, chord/rest editing, duration/voice/transpose, dot/triplet/tie/dynamics, measure insert/duplicate/delete, common guitar techniques, track create/reorder/setup/mixer, optimistic autosave, undo/redo, playback/count-in/selection loop/relative speed/metronome, searchable command palette, bar navigation, notation zoom, page/horizontal layout, same-track copy/cut/paste and revision-pinned GP5/MusicXML/MIDI | Implemented locally — E1-A through E1-D foundation |
| Remaining advanced notation depth and release-latency qualification | In progress — E1 |
| Project collaboration, permissions, presence, comments and versions | Planned — E3 |
| Selection-based LLM edit proposal, notation diff and A/B Apply | Planned — E4 |
| Production queue workers, cancellation and automatic corpus promotion | Not implemented |
| Native GP keyboard grand staff and sound profiles beyond Eclipse | Not implemented |

The current professional-quality baseline and the next milestones are in
[the roadmap](docs/ROADMAP.md). “Implemented” means the path exists and is
covered by automated tests; it does not mean every instrument has reached the
final musical-quality target.

## Current implemented flow

```text
MIDI upload -> immutable source + raw ScoreDocument revision 0
  -> track detection and user correction
  -> async repair job
  -> instrument plugins
  -> SongIR 2.0 compatibility artifact
  -> hard validation
  -> first prepared ScoreDocument revision
  -> AlphaTab-backed score editor -> typed commands -> optimistic save/undo/redo
  -> active-revision GP5 / MusicXML / humanized MIDI export
  -> legacy Eclipse MIDI export
  -> corpus round-trip evaluation
  -> governed knowledge candidate and A/B gate
```

Blank guitar, drum, bass, keys and standard-notation projects enter the editor
without MIDI. The editor replaces the old linear flow incrementally; it does
not remove the existing engines. Manual, repair, humanize and LLM changes will
converge on one typed, validated and versioned command boundary. The LLM remains advisory:
deterministic code owns policy, musical validation and export, and the user
reviews a proposed change before it is applied.

## Local setup

Backend:

```bash
cd backend
uv sync --extra dev

export FRETPILOR_DEBUG=true
export FRETPILOR_JWT_SECRET="replace-with-at-least-32-random-bytes"
export FRETPILOR_MASTER_KEY="$(uv run python -c 'from fretpilot.ai.crypto import KeyVault; print(KeyVault.generate_master_key())')"
export FRETPILOR_ADMIN_EMAILS="admin@example.com"

uv run uvicorn fretpilot.app:create_app --factory --port 8000
```

Frontend:

```bash
cd frontend
npm ci
npm run dev
```

The browser application runs at `http://localhost:5173` and proxies `/api` to
`http://localhost:8000`.

## Quality gates

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

External GP corpus evaluation is opt-in and never part of the default unit
suite. Set `FRETPILOR_TEST_REFERENCE_ZIP` only for a local, authorized corpus.

The latest verified snapshot is 616 backend tests passed, 6 opt-in tests
skipped, 50 frontend tests passed, and successful backend/frontend production
builds.
Do not treat this number as a permanent contract; CI status and the current
test suite are authoritative.

## Documentation

- [Product contract](docs/PRODUCT.md) — goals, users, scope and success metrics
- [Architecture](docs/ARCHITECTURE.md) — ownership, data flow and invariants
- [Development rules](docs/DEVELOPMENT.md) — required workflow and quality gates
- [Roadmap](docs/ROADMAP.md) — current evidence, priorities and acceptance gates
- [Documentation index](docs/README.md) — authority rules and archive index

Historical PRDs, implementation proposals, phase snapshots and Mermaid sources
are retained under `docs/archive/`. They explain how decisions evolved but are
not current requirements.

## Repository

```text
backend/   FastAPI, repair pipelines, SongIR, validation, exporters, learning
frontend/  React, TypeScript, MUI/Tailwind, AlphaTab and async job UI
docs/      Current product, architecture, development and roadmap documents
```

Read [the development rules](docs/DEVELOPMENT.md) before changing architecture,
IR, database, security, exporter or learning-loop behavior.
