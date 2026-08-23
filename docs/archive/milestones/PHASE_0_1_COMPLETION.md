# Phase 0 and Phase 1 completion record

## Phase 0 — engineering baseline

- Reproducible Python dependency lock (`backend/uv.lock`) and clean package
  metadata with runtime dependencies declared.
- GitHub Actions gates for backend lint/tests/coverage/wheel install and frontend
  tests/build.
- Alembic-managed initial schema, fresh-database and unknown-schema tests, and a
  guarded adoption path for recognized pre-Alembic databases.
- Isolated tests with developer-local GP archives moved behind an explicit
  environment variable.
- Restart-stable development BYOK vault derived from the development secret;
  production requires separate JWT and Fernet master secrets.
- Authenticated BYOK connection tests and public-network-only provider URLs with
  redirects and environment proxies disabled.
- Admin-only global learning/version/rollback/diff APIs.
- Writable runtime knowledge store bootstrapped from immutable package assets;
  locked atomic version writes and candidate-first promotion.
- ZIP traversal, symlink, encryption, entry-count, expanded-size, and compression
  ratio controls.
- Explicit proprietary license and repository development rules.

## Phase 1 — unified repair workflow

- `RepairService` is the single API-facing repair path.
- `BandPilotOrchestrator` owns all track classification, routing, aggregation,
  warnings, and terminal status calculation.
- Each guitar track receives independent cleanup, tuning detection, style
  inference, validated rewrite decisions, and the eight-stage guitar pipeline.
- Every drum track receives the eight-stage drum pipeline; drum-only projects
  are supported.
- Multiple guitar and drum IRs are combined without dropping tracks.
- Bass, keys, and unknown tracks follow an explicit partial/passthrough policy
  recorded in `repair_manifest.json`.
- Pipeline exceptions are reported as failed tracks and can no longer be
  silently converted to successful passthrough.
- API/database/UI status recognizes `processing`, `repaired`, `partial`, and
  `failed`.
- Frontend drum visualization uses IR-derived statistics instead of random data.
- Regression coverage includes guitar-only, mixed guitar/drums, drum-only,
  multiple guitars, multiple drums, and unsupported-track partial results.

## Verification snapshot

- Backend: 516 tests passed, 6 opt-in external-corpus tests skipped, and 81.03%
  statement coverage (80% gate satisfied).
- Backend lint and frozen dependency-lock validation passed.
- Frontend: 3 status-policy tests passed, the TypeScript/Vite production build
  succeeded, and the high-severity dependency audit found no vulnerabilities.
- Python source distribution and wheel build/install/startup smoke checks passed.
