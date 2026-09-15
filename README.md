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
implements infrastructure only.

## Current phase: Phase 0 — Bootstrap

Phase 0 sets up the project skeleton, tooling, and infrastructure needed for
every later phase. It intentionally contains **no business logic**:

- No Moodle integration
- No Attendance integration
- No synchronization jobs
- No academic domain tables (students, courses, enrollments, attendance,
  grades, assignments)
- No API authentication
- No real API endpoints beyond `GET /health`

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
images itself. Image publishing to GHCR is not wired up yet; that is
deferred to a later phase.

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
empty database to `head` (see `tests/integration/test_alembic_migration.py`).
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

- Moodle integration
- Attendance integration
- Synchronization jobs
- Academic Database schema (students, courses, enrollments, attendance,
  grades, assignments)
- API authentication / API keys
- Publishing images to GHCR and pulling them on the production server
