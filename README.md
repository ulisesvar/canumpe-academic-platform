# CANUMPE Academic Platform

## Purpose

CANUMPE Academic Platform is the future curated academic system for CANUMPE:
a database and API that will eventually expose a consistent, reliable view of
academic data — independent of the day-to-day systems that produce it.

## Long-term architecture

```
Moodle ───────────┐
                   ├── Sync / Integration Layer
Attendance ───────┘
                          ↓
                   Academic Database
                          ↓
                   Academic API
                          ↓
                        Students
```

- Moodle and Attendance remain independent systems of record.
- A sync/integration layer will extract data from them into a curated
  Academic Database.
- The public Academic API will read only from that curated database, so it
  never depends on Moodle or Attendance being available.

**None of that integration exists yet.** This repository currently
implements infrastructure and a database foundation only.

## Current phase: Phase 1 — Academic Data Foundation

Phase 0 built the project skeleton and shipped a validated production
deployment (`GET /health` only). Phase 1 adds the **database foundation**
for the pipeline above — schemas and canonical tables, no source
connections and no synchronization logic yet.

### Data flow (target architecture)

```
Source (Moodle / Attendance)
        ↓
      RAW               landing copy of selected source entities, as-is
        ↓
    STAGING             normalized/validated, not yet merged
        ↓
    ACADEMIC            curated, canonical — the only system of record
        ↓                for the Academic API
       API
```

The Academic API will eventually query **only** `academic`. RAW and
staging are internal pipeline concerns and must never be queried by the
API.

### PostgreSQL schemas

| Schema | Purpose | Status in Phase 1 |
|---|---|---|
| `raw_moodle` | Landing representation of selected Moodle source entities, as extracted. | Empty — no tables yet |
| `raw_attendance` | Landing representation of selected Attendance source entities, as extracted. | Empty — no tables yet |
| `staging` | Temporary normalized/validated representation before canonical merge. Not a system of record. | Empty — no tables yet |
| `academic` | Curated canonical data. The only schema the Academic API reads from. | `students`, `courses`, `enrollments` |
| `integration` | Source-identity mappings and pipeline observability (never business data). | `student_sources`, `course_sources`, `enrollment_sources`, `sync_runs`, `sync_state` |
| `auth` | Reserved for future API authentication. | Empty — no tables yet |

`raw_moodle`, `raw_attendance`, `staging`, and `auth` are created now only
to establish architectural boundaries. Entity-specific tables in them are
intentionally **not** invented before the real Moodle/Attendance source
models are studied in a later phase.

### Architectural invariants

These are load-bearing rules for every later phase, not just Phase 1:

1. Moodle and Attendance are systems of record; source access will be read-only.
2. The Academic API reads only from `academic` and must never require Moodle
   or Attendance to be available during a request.
3. Canonical academic ids are internally generated and independent of
   source-system ids (a Moodle user id and an Attendance student id may both
   map to the same `academic.students.id`). Source identifiers are stored as
   `TEXT`, never assumed to be integers — this includes `account_number`, so
   leading zeros are preserved.
4. Future extraction uses a consistent snapshot where appropriate; future
   synchronization is idempotent — reprocessing the same source data must
   never create duplicates.
5. A failed batch must not leave `academic` partially updated. A sync
   watermark (`integration.sync_state`) advances only after the academic
   merge for that batch has committed successfully.
6. A record missing from a source extraction is not automatically a
   deletion. Physical deletion of academic records is avoided in favor of
   `active`/`status` fields; future sync logic explicitly decides whether a
   record is unchanged, updated, inactive, invalid, or unexpectedly missing.
7. Every future ingestion batch is observable and auditable via
   `integration.sync_runs`.
8. RAW, staging, and academic have different responsibilities and are never
   mixed in the same table.

Foreign keys between canonical tables use `ON DELETE RESTRICT`: accidental
deletion of a referenced student, course, or enrollment fails loudly rather
than cascading.

### Timestamp maintenance

`created_at` (and `first_seen_at`) may rely on a database default —
they're set once, at insert, and a `server_default=now()` is a reasonable
place for that.

`updated_at` and `last_seen_at` are different: they get a DB default on
insert too (so they start out equal to `created_at`/`first_seen_at`), but
nothing keeps them current after that. There is deliberately no ORM/Core
`onupdate` default and no database trigger. Future synchronization
pipelines will use bulk operations, SQLAlchemy Core statements, and
PostgreSQL `INSERT ... ON CONFLICT DO UPDATE` upserts — an `onupdate`
default is silently skipped by upserts and by some bulk/Core execution
paths, so correctness must not depend on it. Any code that updates a row —
including the future sync implementation — **must set `updated_at`/
`last_seen_at` explicitly** as part of that write. The same applies to
`integration.sync_state.updated_at`: advancing the watermark's `state`
column must set `updated_at` in the same write, not rely on it happening
automatically.

### What Phase 1 does not implement yet

- No connection to Moodle or Attendance, and no real student data
- No extraction or synchronization jobs (no schedulers, no timers)
- No `raw_*`/`staging` entity tables — only the empty schemas
- No `auth` tables and no API authentication/API keys
- No academic API endpoints, grades, assignments, attendance, or participation
- `GET /health` is unchanged from Phase 0

## Developer workstation vs. production host

These are deliberately different environments:

| | Developer workstation | Production (CANUMPE server) |
|---|---|---|
| Python | Optional local venv, or Docker | Never installed for this app |
| Dependencies | `pip install .[dev]` (optional) | Baked into the Docker image only |
| Source code | Full git checkout | Not required |
| Build | `docker build` allowed | Never builds images |
| Runs | `pytest`, `ruff`, `mypy`, `uvicorn --reload`, or Docker | `docker compose pull && docker compose up -d` only |

Production deployment model:

```
GitHub source → GitHub Actions CI → Docker image build → GHCR → CANUMPE server
                                                                    → docker compose pull
                                                                    → docker compose up -d
```

The production server needs Docker, Docker Compose, `compose.yml`, and a
`.env` file — nothing else. It never runs `pip`, `pytest`, `ruff`, `mypy`,
or `alembic` directly from a host Python installation, and it never builds
images itself. `.github/workflows/release.yml` builds and publishes the
`runtime` image to GHCR on version tags; the CANUMPE server pulls it with
`docker compose pull && docker compose up -d`. Migrations still run from a
container (`docker compose run --rm migrate`), never from host Alembic.

## Prerequisites

- Docker and Docker Compose (required for the database, and for
  container-based development/testing)
- Python 3.12+ (optional, only if you want to run tooling directly on your
  workstation instead of in containers)

## Local development setup

```bash
cp .env.example .env

python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Start PostgreSQL (development)

```bash
docker compose up -d db
```

This starts PostgreSQL 16 with a named volume (`canumpe_pg_data`) for
persistent local data. The port is published only on `127.0.0.1:5432` — it
is never exposed publicly.

## Run Alembic migrations (development)

Against the development database, containerized (no host Alembic needed):

```bash
docker compose run --rm migrate
```

Or, if you're using a local virtualenv against the same database:

```bash
alembic upgrade head
```

## Start the app

Containerized:

```bash
docker compose up -d db migrate api
curl http://127.0.0.1:8000/health
```

Locally, against a running `db` container:

```bash
uvicorn app.main:app --reload
```

## Run tests

Tests need a disposable PostgreSQL test database, provided by
`compose.test.yml` (ephemeral storage, bound only to `127.0.0.1:5433`,
never a production-like volume):

```bash
docker compose -f compose.test.yml up -d
pytest
docker compose -f compose.test.yml down
```

Tests never touch Moodle, Attendance, or any production database/credentials.

## Run Ruff

```bash
ruff check .
```

## Run mypy

```bash
mypy app
```

## Validate migrations

The integration test suite already proves Alembic can upgrade a fresh,
empty database to `head`, that the resulting schemas/tables/constraints are
correct, that downgrade-then-upgrade is clean, and that running
`alembic upgrade head` twice is safe (see `tests/integration/test_migrations.py`).
To check it manually:

```bash
docker compose -f compose.test.yml up -d
DATABASE_URL=postgresql+psycopg://canumpe_test:canumpe_test@127.0.0.1:5433/canumpe_test alembic upgrade head
```

## Build the Docker image

```bash
docker build -t canumpe-academic-platform:local .
```

This builds the production `runtime` target (the default, final stage in
the `Dockerfile`). A separate `test` build target exists with dev tooling
included, used for CI and optional container-based test runs:

```bash
docker build --target test -t canumpe-academic-platform:test .
```

## Stop the environment

```bash
docker compose down
docker compose -f compose.test.yml down
```

Add `-v` to also remove the named development volume if you want a
completely clean slate.

## Deferred to later phases

- Moodle integration and Attendance integration (no source connections exist)
- Extraction and synchronization jobs (schedulers, timers, watermark advancement)
- `raw_moodle` / `raw_attendance` / `staging` entity tables
- `auth` tables and API authentication / API keys
- Academic API endpoints, grades, assignments, attendance, participation
