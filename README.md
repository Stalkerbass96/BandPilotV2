# BandPilot v2

BandPilot turns a multi-track MIDI file into a professional, playable band
score. The first product goal is a trustworthy Guitar Pro score: correct
instrument separation, practical guitar/bass fingering, coherent techniques,
and notation a musician can rehearse without repairing the file by hand.

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
| Governed GP corpus evaluation and candidate knowledge snapshots | Implemented baseline |
| Production queue workers, cancellation and automatic corpus promotion | Not implemented |
| Native GP keyboard grand staff and sound profiles beyond Eclipse | Not implemented |

The current professional-quality baseline and the next milestones are in
[the roadmap](docs/ROADMAP.md). “Implemented” means the path exists and is
covered by automated tests; it does not mean every instrument has reached the
final musical-quality target.

## Product flow

```text
MIDI upload
  -> track detection and user correction
  -> async repair job
  -> instrument plugins
  -> canonical SongIR 2.0
  -> hard validation
  -> GP5 / MusicXML / humanized MIDI / Eclipse MIDI
  -> corpus round-trip evaluation
  -> governed knowledge candidate and A/B gate
```

The LLM is advisory. It may classify style or propose bounded decisions, but
deterministic code owns pitch, rhythm, string/fret truth, policy enforcement,
validation and export.

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

The latest verified snapshot is 551 backend tests passed, 6 opt-in tests
skipped, 8 frontend tests passed, and a successful frontend production build.
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
