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

**Attendance integration does not exist yet.** This repository currently
implements infrastructure, a database foundation, and a Moodle ingestion
pipeline for students/courses/enrollments only.

## Current phase: Phase 2 — Moodle Ingestion

Phase 0 built the project skeleton and shipped a validated production
deployment (`GET /health` only). Phase 1 added the database foundation —
schemas and canonical tables, no source connections yet. Phase 2 adds a
working Moodle ingestion pipeline (students, courses, enrollments only):
read-only extraction → `raw_moodle` → `staging` → validation → a
transactional merge into `academic`. It is invoked manually, as a
separate command — never scheduled, and never triggered by the API.

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

| Schema | Purpose | Status in Phase 2 |
|---|---|---|
| `raw_moodle` | Landing representation of selected Moodle source entities, as extracted — faithful, append-only, never validated. | `students`, `courses`, `enrollments` |
| `raw_attendance` | Landing representation of selected Attendance source entities, as extracted. | Empty — no tables yet |
| `staging` | Normalized/validated candidate rows for one batch, rebuilt on every run. Not a system of record. | `students`, `courses`, `enrollments` |
| `academic` | Curated canonical data. The only schema the Academic API reads from. | `students`, `courses`, `enrollments` |
| `integration` | Source-identity mappings and pipeline observability (never business data). | `student_sources`, `course_sources`, `enrollment_sources`, `sync_runs`, `sync_state` |
| `auth` | Reserved for future API authentication. | Empty — no tables yet |

`raw_attendance` and `auth` remain empty — established now only for
architectural boundaries. Entity-specific tables for Attendance are
intentionally **not** invented before its real source model is studied in
a later phase.

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

### Moodle ingestion pipeline

```
Moodle (read-only)
        ↓  one REPEATABLE READ, READ ONLY transaction
  extraction              app.integration.moodle.source
        ↓
  raw_moodle.*             faithful landing copy, append-only, never validated
        ↓
  staging.*                normalized candidates, rebuilt every run
        ↓
  validation               batch-wide checks (duplicates, dangling references)
        ↓  only if zero issues
  canonical merge           one transaction: academic.* + integration.*_sources
        ↓
  integration.sync_runs / sync_state
```

Implemented in `app/integration/moodle/` (`source.py`, `raw_writer.py`,
`staging_writer.py`, `validation.py`, `merge.py`, `runs.py`, `sync.py`).

**Source contract.** The account number is a Moodle custom profile field
(`mdl_user_info_field.shortname = 'cuenta'`, joined to
`mdl_user_info_data`) — never a hardcoded `fieldid`, and never
`mdl_user.idnumber`. A student is only extracted if `mdl_user.deleted =
0`; an enrollment is only extracted if both `mdl_user_enrolments.status =
0` and `mdl_enrol.status = 0`. Course scope is `MOODLE_COURSE_ID`
(configuration, not a hardcoded id in SQL). If the same account number
resolves to more than one non-deleted Moodle user, extraction raises
immediately (`MoodleSourceIntegrityError`) rather than silently picking
one.

**Consistent snapshot.** All three extraction queries (students, courses,
enrollments) run inside one `SET TRANSACTION ISOLATION LEVEL REPEATABLE
READ READ ONLY` transaction, so they see one coherent view of Moodle even
if something else commits a change to Moodle mid-extraction. The
connection is always cleanly committed (read-only, so this just releases
the snapshot) or rolled back, and closed.

**Full extraction, on purpose.** Phase 2 re-extracts the whole configured
course scope on every run rather than tracking an incremental
cursor/watermark. Current data volume is small, so the simplicity is
worth more than the optimization; `integration.sync_state` already
records the last successful batch's id/snapshot time so a later phase can
add incremental extraction without a schema change.

**Idempotency.** Change detection is by `source_hash` (a documented,
deterministic SHA-256 over business-relevant fields only — never
`batch_id`/`ingested_at`/`source_updated_at`; see
`app/integration/moodle/hashing.py`). Re-running the same source state
produces `rows_inserted=0, rows_updated=0, rows_unchanged=N` — no
duplicate canonical rows, no duplicate `integration.*_sources` mappings.
A student enrolled in the same course through more than one Moodle enrol
method resolves to one canonical enrollment (`academic.enrollments` has
`UNIQUE(student_id, course_id)`); the merge reuses the existing row
instead of trying to insert a second one.

**Transaction and failure behavior.** RAW and staging writes commit on
their own (RAW must survive even if a later stage fails; staging is
disposable but still worth inspecting after a failed run). Validation
runs read-only. The canonical merge — `academic.*` writes, the
`integration.*_sources` mapping updates, and advancing
`integration.sync_state` — all happen in one transaction; a `sync_runs`
row only ever reads SUCCESS once that transaction has actually committed.
Any blocking validation issue, or any exception during the merge, aborts
before or rolls back the merge entirely: existing academic data is never
partially updated, and the failed run is recorded with `status=FAILED`
and an `error_message`. The watermark in `sync_state` is only touched
inside the merge transaction, so it never advances on a failed run.

**Timestamps.** Per the Phase 1 invariant, the merge always sets
`updated_at`/`last_seen_at`/`synced_at` explicitly (never relies on ORM
`onupdate`) — including on the unchanged path, where `last_seen_at`/
`synced_at` still advance because the source was observed again even
though nothing about it changed, while `updated_at` on the canonical row
stays put.

**Missing records.** A student/enrollment absent from one extraction
(e.g. unenrolled) is not touched — never physically deleted and never
inferred as inactive. It simply isn't in that batch; a future phase can
add explicit logic for "expected vs. unexpected disappearance."

**Source identity.** Uses the Phase 1 mapping tables
(`integration.student_sources`/`course_sources`/`enrollment_sources`) —
Moodle ids are never canonical primary keys. The stable source identity
for an enrollment is Moodle's `mdl_user_enrolments.id`.

**Security boundary.** The sync command needs its own read-only Moodle
credential (production user `academic_sync_moodle`, `SELECT` only) — the
application never creates that user or grants privileges; that's done by
Moodle's own administrators outside this codebase. `MOODLE_DB_URL`/
`MOODLE_COURSE_ID` are only ever read by `app.integration.moodle.config`,
loaded only by `app.integration.moodle.sync`'s `main()`. The public API
(`app.core.config.Settings`) has no such fields and never receives these
variables. In production the sync runs natively on the CANUMPE host, not
in a container — see "Host-native operational integration jobs" below
for the full execution model, and `docker compose run --rm moodle-sync`
further down for the development/testing-only Docker path.

### What Phase 2 does not implement yet

- No connection to Attendance, and no real student data anywhere
- No cron — scheduling is `deploy/systemd/academic-moodle-sync.timer`,
  but it is example material, not installed/enabled anywhere yet, and
  production cadence is not decided by this repository
- No incremental extraction (full course-scope re-extraction every run)
- No `raw_attendance`/`staging` entity tables for Attendance
- No `auth` tables and no API authentication/API keys
- No academic API endpoints, grades, assignments, attendance, or participation
- `GET /health` is unchanged from Phase 0; the API still never queries Moodle

## Developer workstation vs. production host

These are deliberately different environments. Note the one deliberate
exception in the production column — the Moodle sync — explained in full
in "Host-native operational integration jobs" right below this table.

| | Developer workstation | Production (CANUMPE server) |
|---|---|---|
| Python | Optional local venv, or Docker | Never installed for the API; an isolated venv exists only for the Moodle sync |
| Dependencies | `pip install .[dev]` (optional) | API: baked into the Docker image. Moodle sync: pinned into its own venv |
| Source code | Full git checkout | API: not required (image only). Moodle sync: an approved tagged checkout, installed into its venv — never edited in place |
| Build | `docker build` allowed | Never builds Docker images |
| Runs | `pytest`, `ruff`, `mypy`, `uvicorn --reload`, or Docker | API/DB: `docker compose pull && docker compose up -d`. Moodle sync: a systemd oneshot service/timer running the venv's Python natively |

Production deployment model — the API/database side:

```
GitHub source → GitHub Actions CI → Docker image build → GHCR → CANUMPE server
                                                                    → docker compose pull
                                                                    → docker compose up -d
```

The production server needs Docker, Docker Compose, `compose.prod.yml`
(see below), and a `.env` file for the API/database side — nothing else.
It never runs `pip`, `pytest`, `ruff`, `mypy`, or `alembic` directly from
a host Python installation for the API, and it never builds Docker images
itself. `.github/workflows/release.yml` builds and publishes the
`runtime` image to GHCR on version tags; the CANUMPE server pulls it with
`docker compose pull && docker compose up -d`. Migrations still run from
a container (`docker compose run --rm migrate`), never from host Alembic.

## Host-native operational integration jobs

CANUMPE distinguishes two kinds of production workload:

- **Applications** — normally Docker/GHCR, per the model above. The
  Academic API and the Academic Database.
- **Operational integration jobs** — may run natively on the host when
  they need direct access to a *local* source system. The Moodle sync,
  today; a future Attendance sync, potentially.

**Why the Moodle sync runs on the host, not in Docker.** Moodle's
PostgreSQL listens on `127.0.0.1` only, by design — it is not reachable
from anywhere else, including from inside a Docker network, without
either exposing it publicly or building a Docker-to-host networking
workaround. Neither is acceptable. Running the sync as a native process
on the same host as Moodle lets it reach `127.0.0.1:5432` exactly like
any other local client, with zero change to Moodle's network exposure:

```
Moodle PostgreSQL (127.0.0.1:5432, read-only)
        ↓
   host-native Python sync job (systemd oneshot)
        ↓
Academic PostgreSQL (127.0.0.1:5434, dedicated ingest credential)
        ↓
   Academic API (Docker, internal network only)
```

The Academic API and Academic Database stay exactly as Dockerized as
before — this only changes how the *sync job* runs, not the pipeline
logic itself (extraction, RAW, staging, validation, merge, idempotency,
and `integration.sync_runs`/`sync_state` are unchanged from Phase 2's
implementation).

### Production directory layout

```
/opt/canumpe/
├── apps/
│   └── academic-platform/
│       ├── compose.prod.yml        # from this repo, copied at deploy time
│       └── .env                    # API/DB secrets — never in Git
│
├── integrations/
│   └── academic-platform/
│       └── moodle-sync/
│           ├── .venv/              # isolated virtualenv (see below)
│           └── src/                # approved tagged checkout, pip-installed into .venv
│
├── config/
│   └── academic-platform/
│       └── moodle-sync.env         # chmod 600, owned by academic-sync — never in Git
│
└── logs/
    └── academic-platform/          # reserved; the sync itself logs to stdout/stderr (see below)
```

No secrets live in this repository at any of these paths — `.env` and
`moodle-sync.env` are created on the host from `.env.example` /
`deploy/systemd/moodle-sync.env.example`.

### Virtual environment (Moodle sync only)

Planned location: `/opt/canumpe/integrations/academic-platform/moodle-sync/.venv`.

The sync module is installed into this venv, not run from a source
checkout in place, and never with `pip install -e`. There is no lock
file in this project yet, so "reproducible" here means: pin an exact
approved Git tag/ref, and `pyproject.toml`'s version ranges at that ref
are what gets installed — a stricter lock (e.g. `pip-compile`/`uv lock`)
can be added later without changing this deployment shape.

```bash
# As root or via sudo, once per deployed version:
python3.12 -m venv /opt/canumpe/integrations/academic-platform/moodle-sync/.venv

git clone --branch v0.3.0 --depth 1 \
    https://github.com/ulisesvar/canumpe-academic-platform.git \
    /opt/canumpe/integrations/academic-platform/moodle-sync/src

/opt/canumpe/integrations/academic-platform/moodle-sync/.venv/bin/pip install \
    --no-cache-dir \
    /opt/canumpe/integrations/academic-platform/moodle-sync/src

chown -R academic-sync:academic-sync /opt/canumpe/integrations/academic-platform/moodle-sync
```

No global `pip install` anywhere — everything above installs into the
dedicated venv. Updating to a new approved version repeats this (new
tag, fresh `git clone`, `pip install` into the same venv path, or a
fresh venv if preferred) — the running systemd unit is unaffected until
its next scheduled/manual run.

### Dedicated system user

Production uses a dedicated Linux account, `academic-sync`:

- no interactive login, no SSH access, not root
- can read the approved sync code and the protected environment file
- can execute the sync job
- writes only where explicitly necessary (nowhere, in practice — the
  sync only talks to PostgreSQL over the network)

```bash
useradd --system --no-create-home --shell /usr/sbin/nologin academic-sync
```

### Database access model

**Moodle source** (`academic_sync_moodle`): created manually in
production PostgreSQL by Moodle's administrators, `SELECT`-only, never
by application code. `MOODLE_DB_URL` uses `127.0.0.1` because the sync
runs on the same host as Moodle:

```
postgresql+psycopg://academic_sync_moodle:<secret>@127.0.0.1:5432/moodle
```

**Academic Database**: exposed only on localhost, on a non-conflicting
port — Moodle already owns 5432 on this host, so the Academic Database
uses 5434 (`compose.prod.yml` publishes `127.0.0.1:5434:5432`; never
`0.0.0.0`, never reachable from the LAN or Internet). The sync uses a
dedicated, least-privilege ingest credential, `academic_ingest_moodle` —
not the database-owner credential the API/migrate services use, and not
created by application code (see
`deploy/sql/academic_ingest_moodle_grants.example.sql` for the exact,
minimal grants: `raw_moodle`, `staging`, `integration`, and only
`academic.students`/`academic.courses`/`academic.enrollments` — no
`CREATE`, no ownership, no superuser, no `DELETE` on `academic`).

```
postgresql+psycopg://academic_ingest_moodle:<secret>@127.0.0.1:5434/canumpe
```

The public API continues to reach the Academic Database over the
internal Docker network (`compose.prod.yml`'s `db` service) — the
localhost port above exists for host-native integration jobs, not for
the API.

### systemd: oneshot service + timer

No cron. Example unit files live in `deploy/systemd/`:
[`academic-moodle-sync.service`](deploy/systemd/academic-moodle-sync.service),
[`academic-moodle-sync.timer`](deploy/systemd/academic-moodle-sync.timer),
and a template for the protected environment file,
[`moodle-sync.env.example`](deploy/systemd/moodle-sync.env.example).

The service is `Type=oneshot`, runs as `User=academic-sync`, reads
`EnvironmentFile=/opt/canumpe/config/academic-platform/moodle-sync.env`,
and executes the venv's `python -m app.integration.moodle.sync` directly
(no shell). A non-zero exit code — see `main()` in
`app/integration/moodle/sync.py` — marks the systemd run failed. The
timer's `OnCalendar=` in the example is illustrative only; actual
production cadence is an operational decision the repository does not
fix. `Persistent=true` lets a run missed during a reboot/outage catch up
automatically instead of silently waiting for the next scheduled time.

Application code never enables, starts, or otherwise touches these
units — installing and enabling them is a manual operator action (see
the comments at the top of the `.service` file).

### Logs: journald vs. integration.sync_runs

Two different, complementary views:

- **`journalctl -u academic-moodle-sync.service`** / **`systemctl status
  academic-moodle-sync.service`** — system-level execution status: did
  the process run, when, did it exit non-zero, and its stdout/stderr.
  The sync logs cleanly to stdout/stderr for exactly this — no custom
  log file handling is needed for core operation.
- **`integration.sync_runs`** — pipeline-level operational detail: row
  counters, `status`, `error_message`, `snapshot_time`, per batch. This
  is unchanged from Phase 2 and lives in the Academic Database regardless
  of how the job was invoked.

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

Tests never touch a real Moodle or Attendance instance, or any production
database/credentials. Moodle-sourced tests run against a minimal fake
Moodle schema (`tests/integration/moodle/fake_moodle.py`) created in the
same disposable test database.

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

- Attendance integration (no source connection exists)
- Actually enabling/installing the systemd timer and deciding its
  production cadence — example units exist (`deploy/systemd/`), but
  nothing runs them yet and the schedule is an operational decision
- Incremental Moodle extraction (Phase 2 is full-extraction only)
- `raw_attendance` / `staging` entity tables for Attendance
- `auth` tables and API authentication / API keys
- Academic API endpoints, grades, assignments, attendance, participation
