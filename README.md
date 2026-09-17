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

This repository currently implements infrastructure, a database
foundation, and two ingestion pipelines: Moodle (students, courses,
enrollments) and Attendance (attendance sessions/records only —
Attendance never creates students or courses of its own; see below).

## Current phase: Phase 3 — Attendance Ingestion

Phase 0 built the project skeleton and shipped a validated production
deployment (`GET /health` only). Phase 1 added the database foundation.
Phase 2 added the Moodle ingestion pipeline, now running in production
every 30 minutes. Phase 3 adds a working Attendance ingestion pipeline:
read-only extraction → `raw_attendance` → `staging` → validation/
reconciliation → a transactional merge into `academic`. Like the Moodle
sync, it is invoked manually, as a separate command — never scheduled,
never triggered by the API.

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

| Schema | Purpose | Status in Phase 3 |
|---|---|---|
| `raw_moodle` | Landing representation of selected Moodle source entities, as extracted — faithful, append-only, never validated. | `students`, `courses`, `enrollments` |
| `raw_attendance` | Landing representation of selected Attendance source entities, as extracted — faithful, append-only, never validated. Never coordinates/distance. | `students`, `sessions`, `attendances` |
| `staging` | Normalized/validated candidate rows for one batch, rebuilt on every run. Not a system of record. | `students`, `courses`, `enrollments`, `attendance_students`, `attendance_sessions`, `attendance_records` |
| `academic` | Curated canonical data. The only schema the Academic API reads from. | `students`, `courses`, `enrollments`, `attendance_sessions`, `attendance_records` |
| `integration` | Source-identity mappings and pipeline observability (never business data). | `student_sources`, `course_sources`, `enrollment_sources`, `attendance_session_sources`, `attendance_record_sources`, `sync_runs`, `sync_state`, `sync_issues` |
| `auth` | Reserved for future API authentication. | Empty — no tables yet |

`auth` remains empty — established only for architectural boundaries;
API authentication is a later phase. Attendance students reconcile into
the *existing* `integration.student_sources` table (just another
`source_system`) rather than a new mapping table — see below.

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

### Attendance ingestion pipeline

```
Attendance (read-only)
        ↓  one REPEATABLE READ, READ ONLY transaction
  extraction              app.integration.attendance.source
        ↓
  raw_attendance.*         faithful landing copy — no coordinates, ever
        ↓
  staging.attendance_*     normalized candidates, rebuilt every run
        ↓
  validation               batch checks + account_number reconciliation
        ↓                  + course resolution — only if zero issues
  canonical merge           one transaction: academic.* + integration.*_sources
        ↓
  integration.sync_runs / sync_state
```

Implemented in `app/integration/attendance/` (`source.py`, `raw_writer.py`,
`staging_writer.py`, `validation.py`, `merge.py`, `runs.py`, `sync.py`),
mirroring the Moodle pipeline's structure closely.

**Minimal-data principle.** The Attendance source schema also carries
`telegram_id`, `telegram_username`, and per-attendance `latitude`/
`longitude`/`distance_meters`. None of that is ever ingested — not into
`raw_attendance`, not into `staging`, not into `academic`. Only what
academic attendance actually needs is extracted: student id + account
number; session id + `opened_at`/`closed_at`/`status`; attendance id +
student/session ids + `created_at`. `raw_attendance.attendances` has no
location columns at all — this is enforced at the schema level, not just
by the extraction query, so a future change can't silently start
collecting them by accident.

**Attendance creates no canonical students or courses.** The canonical
student population comes from Moodle. An Attendance student reconciles
to an *existing* `academic.students` row by `account_number` — this
pipeline never runs `INSERT INTO academic.students`. The mapping itself
reuses the existing `integration.student_sources` table with
`source_system='attendance'` — exactly the "moodle / 137 and attendance
/ 25 both map to `academic.students.id = 8`" example from the Phase 1
design. `account_number` resolution has three possible outcomes, and
only one of them blocks the batch:

| Matches in `academic.students` | Outcome |
|---|---|
| Exactly 1 | Normal reconciliation — mapping created/refreshed, that student's attendance records merge. |
| 0 | **Skip**, not a failure — see below. |
| More than 1 | Blocking — structurally prevented by `academic.students`' own `UNIQUE(account_number)`, but checked anyway (`app.integration.attendance.validation._reconciliation_issue`). |

**Unresolved students are skipped, not fatal.** An Attendance student
whose `account_number` doesn't exist in Moodle *yet* must not fail the
whole batch — that was Phase 3's original behavior and production
acceptance testing rejected it (one real student existed in Attendance
before being added to Moodle). Instead, `merge.py`'s
`_reconcile_students` skips that specific student — no canonical student
created, no source mapping created — and `_merge_records` skips every
attendance record belonging to them (`rows_skipped` counts both). Every
other student/session/record in the batch still merges normally, and the
run is `SUCCESS`. Because Phase 3 always does a full extraction, the
very next sync re-attempts this exact reconciliation from scratch: once
Moodle sync creates that student, the next Attendance sync resolves
their `account_number`, creates the mapping, and imports their entire
attendance history — nothing is permanently lost, just delayed.

**Counter semantics** (`integration.sync_runs`, set in
`app.integration.attendance.sync.run_attendance_sync`):

- `rows_read` — every row extraction returned (students + sessions +
  attendances), before any check.
- `rows_valid` — equals `rows_read` whenever `validate_staged_batch`
  found zero blocking issues for the batch. Validity is a batch-wide,
  structural/referential judgment (would this batch be safe to attempt
  merging at all?), independent of whether an individual valid row was
  actually merged.
- `rows_skipped` — valid rows deliberately not merged because their
  canonical anchor doesn't exist yet: an unresolved Attendance student,
  plus every attendance record belonging to them. Not an error.
- `rows_inserted`/`rows_updated`/`rows_unchanged` — as in the Moodle
  pipeline, driven by `source_hash` comparison, counted across students,
  sessions, and records together.

**Blocking error vs. operational issue.** The platform now has two
distinct ways a sync can react to a problem:

- **Blocking error** — the whole batch fails (`sync_runs.status =
  'FAILED'`), `academic` is left exactly as it was, and nothing is
  learned from this batch. Reserved for things that indicate the source
  data or the batch itself can't be trusted: duplicate Attendance
  `account_number`, ambiguous canonical resolution (>1 academic match),
  duplicate source identity, a broken session/student reference, a
  duplicate student/session attendance, or a missing
  `ATTENDANCE_MOODLE_COURSE_ID` mapping.
- **Operational issue** — the batch still succeeds
  (`sync_runs.status = 'SUCCESS'`); the specific inconsistency is
  recorded as a row in `integration.sync_issues` instead of aborting
  everything. Currently the only such case is an unresolved Attendance
  student (0 academic matches) — expected, not a data problem, just
  "Moodle hasn't caught up yet."

**`integration.sync_issues`** (generic — see `app.integration.issues`;
not specific to Attendance or any one `source_system`) makes an
operational issue visible and queryable instead of it disappearing into
`rows_skipped`. Identity is `UNIQUE(source_system, issue_type,
source_entity, source_id)`, so reprocessing the same inconsistency every
30 minutes upserts the same row rather than inserting a new one each
time: `first_seen_at` is set once, on the initial insert;
`last_seen_at`/`reference_value`/`message` are refreshed explicitly on
every subsequent occurrence (never an ORM/Core `onupdate`, no triggers —
same invariant as everywhere else in this platform). `status` is
`OPEN`/`RESOLVED` (`CHECK` constraint); once the underlying student
resolves, `app.integration.attendance.merge` finds the matching `OPEN`
row and sets `status='RESOLVED'` with an explicit `resolved_at` — the
row is **never deleted**, so resolved issues remain as permanent
history.

**Reopen semantics.** The same row supports the full cycle indefinitely:
`OPEN → OPEN` (repeat occurrences while still unresolved: a no-op beyond
refreshing `last_seen_at`) → `RESOLVED` (`resolve_issue`) → `OPEN` again,
*if the identical inconsistency recurs* → `RESOLVED` again, and so on.
`open_issue`'s `ON CONFLICT DO UPDATE` unconditionally sets
`status='OPEN'` and `resolved_at=NULL` on every call, regardless of the
row's current status — so a previously `RESOLVED` row that reappears is
correctly reopened rather than incorrectly left `RESOLVED`.
`first_seen_at` and the row's `id` never change across any of this;
`reference_value`/`message` are refreshed each time. No new row is ever
inserted for an identity that already exists, in either direction. (The
current Attendance pipeline can't actually trigger a reopen — once a
student's source mapping is created it is never revisited — but the
generic mechanism supports it for any future caller; see
`tests/integration/test_sync_issues.py` for the lifecycle proven
directly against `open_issue`/`resolve_issue`.)

For the current unresolved-student case:
`source_system='attendance'`, `issue_type='UNRESOLVED_STUDENT'`,
`source_entity='student'`, `source_id` = the Attendance student's source
id, `reference_value` = their `account_number`.

*Transaction behavior*: both `open_issue` and `resolve_issue`
(`app/integration/issues.py`) take an open `connection` and are only
ever called from inside the same transaction as the canonical merge
(`app.integration.attendance.merge`, itself called from within
`sync.py`'s `with app_engine.begin()` block). An `OPEN` issue row —
like the canonical writes and the `sync_state` watermark it sits
alongside — therefore only becomes visible once that transaction
actually commits; if the merge rolls back for any reason, the issue
write rolls back with it. There is no separate transaction boundary for
issue tracking to reason about.

Example query — everything currently open, most recently seen first:

```sql
SELECT
    source_system,
    issue_type,
    source_id,
    reference_value,
    status,
    first_seen_at,
    last_seen_at,
    resolved_at
FROM integration.sync_issues
WHERE status = 'OPEN'
ORDER BY last_seen_at DESC;
```

Look up whether a specific student has ever had an issue, by account
number:

```sql
SELECT *
FROM integration.sync_issues
WHERE issue_type = 'UNRESOLVED_STUDENT'
  AND reference_value = '321167907';
```

**Course association through the Moodle mapping.** The Attendance
source has no course id of its own. `ATTENDANCE_MOODLE_COURSE_ID`
(config) is resolved through the *existing* Moodle course mapping —
`integration.course_sources` where `source_system='moodle'` and
`source_id` is that configured id — never a hardcoded
`academic.courses.id`. If that mapping doesn't exist (the Moodle course
hasn't been synced yet), the batch fails rather than guessing or
creating a course.

**RAW → staging → validation → merge**, same shape as Moodle: RAW and
staging commit independently of the merge outcome; validation (batch
duplicates, dangling `attendance` → `student`/`session` references,
account_number reconciliation, course resolution) runs read-only and,
if it finds anything, the whole batch fails before touching `academic`;
the canonical merge — sessions, records, source mapping updates, the
`sync_state` watermark — happens in one transaction, and a `sync_runs`
row only reads SUCCESS once that transaction commits.

**Idempotency.** Change detection is by `source_hash`, exactly like
Moodle. Re-running identical source state yields
`rows_inserted=0, rows_updated=0, rows_unchanged=N`. A session's
`OPEN → CLOSED` transition updates the same canonical
`academic.attendance_sessions` row (matched via
`integration.attendance_session_sources`) — never a duplicate. An
already-present attendance record is never duplicated
(`UNIQUE(attendance_session_id, student_id)` plus the source mapping's
own `UNIQUE(source_system, source_id)`).

**Absence is not calculated here.** Ingestion records only source facts:
a session existed, a student recorded attendance at it. Whether a
student who has *no* `academic.attendance_records` row for a session was
absent, and any percentage/summary built from that, is future API/
business logic — deliberately out of scope for this ingestion layer.

**Failure behavior.** Same as Moodle: a blocking validation issue or any
merge exception leaves `academic` and the `sync_state` watermark exactly
as they were, and records the run as `FAILED` with an `error_message`.

**Security boundary and host-native execution.** Same operational
pattern as the Moodle sync — its own read-only source credential
(production user `academic_sync_attendance`), a dedicated Academic
ingest credential (`academic_ingest_attendance`, least-privilege — see
`deploy/sql/academic_ingest_attendance_grants.example.sql`), and
`ATTENDANCE_DB_URL`/`ATTENDANCE_MOODLE_COURSE_ID` read only by
`app.integration.attendance.config`, never by the public API. The
Attendance PostgreSQL currently runs in the `asistencias-db-1` Docker
container (database `asistencia`) on the CANUMPE host; the sync reaches
it over whatever localhost port that container already publishes — no
public exposure, no Docker-to-Docker networking workaround. See
`deploy/systemd/academic-attendance-sync.{service,timer}` and
`deploy/systemd/attendance-sync.env.example` — reference material only,
not installed or enabled by this repository.

### What Phase 3 does not implement yet

- No academic API endpoints, grades, assignments, attendance
  percentages, or absence calculations — ingestion records source facts
  only
- No cron — scheduling is `deploy/systemd/academic-attendance-sync.timer`,
  example material, not installed/enabled anywhere, and production
  cadence is not decided by this repository
- No incremental extraction (full source re-extraction every run —
  current volume is tiny: 13 students, 7 sessions, 66 attendances)
- No `auth` tables and no API authentication/API keys
- `GET /health` is unchanged from Phase 0; the API still never queries
  Moodle or Attendance and never receives their credentials

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
  they need direct access to a *local* source system. The Moodle sync
  (running in production, every 30 minutes) and the Attendance sync
  (Phase 3 — reference deployment material only, not deployed yet).

**Why these syncs run on the host, not in Docker.** Moodle's PostgreSQL
listens on `127.0.0.1` only, by design; the Attendance PostgreSQL
currently runs in the `asistencias-db-1` Docker container, published to
a localhost port on the same host. Neither is reachable from inside a
different Docker network without either exposing it publicly or
building a Docker-to-host networking workaround — neither of which is
acceptable. Running each sync as a native process on the same host as
its source lets it reach `127.0.0.1:<port>` exactly like any other local
client, with zero change to the source's network exposure:

```
Moodle PostgreSQL (127.0.0.1:5432)  ──┐
                                       ├─→ host-native Python sync jobs (systemd oneshot)
Attendance PostgreSQL (127.0.0.1:<port>, Docker) ──┘
                                       ↓
                Academic PostgreSQL (127.0.0.1:5434, dedicated ingest credential per source)
                                       ↓
                        Academic API (Docker, internal network only)
```

The Academic API and Academic Database stay exactly as Dockerized as
before — this only changes how the *sync jobs* run, not the pipeline
logic itself (extraction, RAW, staging, validation, merge, idempotency,
and `integration.sync_runs`/`sync_state` are unchanged from how Phase 2
established them).

### Production port convention

All localhost-only, none ever bound to `0.0.0.0`, none reachable from
the LAN or Internet:

| Service | Host binding |
|---|---|
| Moodle PostgreSQL | `127.0.0.1:5432` (pre-existing, unowned by this repo) |
| Academic PostgreSQL | `127.0.0.1:5434` → container `5432` |
| Academic API | `127.0.0.1:8080` → container `8000` |

These are the established production values — `compose.prod.yml` is the
source of truth for the last two, and
[`tests/unit/test_production_compose.py`](tests/unit/test_production_compose.py)
asserts them so this contract can't drift silently. The API's container
port (`8000`) is unchanged from development; only the production host
side is `8080`, not `8000` — don't confuse the two when reading
`compose.prod.yml`'s `"127.0.0.1:8080:8000"`.

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
│       ├── moodle-sync/
│       │   ├── .venv/              # isolated virtualenv (see below)
│       │   └── src/                # approved tagged checkout, pip-installed into .venv
│       └── attendance-sync/
│           ├── .venv/              # its own isolated virtualenv
│           └── src/                # approved tagged checkout, pip-installed into .venv
│
├── config/
│   └── academic-platform/
│       ├── moodle-sync.env         # chmod 600, owned by academic-sync — never in Git
│       └── attendance-sync.env     # chmod 600, owned by academic-sync — never in Git
│
└── logs/
    └── academic-platform/          # reserved; the syncs log to stdout/stderr (see below)
```

No secrets live in this repository at any of these paths — `.env`,
`moodle-sync.env`, and `attendance-sync.env` are created on the host
from `.env.example` / `deploy/systemd/moodle-sync.env.example` /
`deploy/systemd/attendance-sync.env.example`.

### Virtual environments (one per sync)

Each sync gets its own isolated venv — planned locations:
`/opt/canumpe/integrations/academic-platform/moodle-sync/.venv` and
`/opt/canumpe/integrations/academic-platform/attendance-sync/.venv`.
The steps below use the Moodle sync as the example; the Attendance sync
follows the identical pattern at its own path.

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

Production uses one dedicated Linux account, `academic-sync`, for both
syncs:

- no interactive login, no SSH access, not root
- can read the approved sync code and each protected environment file
- can execute the sync jobs
- writes only where explicitly necessary (nowhere, in practice — each
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

**Attendance source** (`academic_sync_attendance`): created manually,
read-only, on the Attendance PostgreSQL running in the
`asistencias-db-1` Docker container — never by application code.

```
postgresql+psycopg://academic_sync_attendance:<secret>@127.0.0.1:<port>/asistencia
```

The Attendance sync uses its own dedicated, least-privilege ingest
credential, `academic_ingest_attendance` — see
`deploy/sql/academic_ingest_attendance_grants.example.sql`. It can
`SELECT` `academic.students`/`academic.courses` (to reconcile and to
satisfy foreign keys) but has no write access to them at all — only to
`academic.attendance_sessions`/`academic.attendance_records`,
`raw_attendance`, `staging`, and its own `integration.*` rows.

```
postgresql+psycopg://academic_ingest_attendance:<secret>@127.0.0.1:5434/canumpe
```

The public API continues to reach the Academic Database over the
internal Docker network (`compose.prod.yml`'s `db` service) — the
localhost port above exists for host-native integration jobs, not for
the API. The API's own production host binding is `127.0.0.1:8080`
(container port `8000`) — see the port convention table above.

### systemd: oneshot service + timer

No cron, for either sync. Example unit files live in `deploy/systemd/`:

- Moodle: [`academic-moodle-sync.service`](deploy/systemd/academic-moodle-sync.service),
  [`.timer`](deploy/systemd/academic-moodle-sync.timer),
  [`moodle-sync.env.example`](deploy/systemd/moodle-sync.env.example)
- Attendance: [`academic-attendance-sync.service`](deploy/systemd/academic-attendance-sync.service),
  [`.timer`](deploy/systemd/academic-attendance-sync.timer),
  [`attendance-sync.env.example`](deploy/systemd/attendance-sync.env.example)

Both services are `Type=oneshot`, run as `User=academic-sync`, read
their own `EnvironmentFile=`, and execute their venv's
`python -m app.integration.<moodle|attendance>.sync` directly (no
shell). A non-zero exit code — see each pipeline's `sync.py:main()` —
marks the systemd run failed. Each timer's `OnCalendar=` in the example
is illustrative only (the Moodle example mirrors its current 30-minute
production cadence; the Attendance example does the same, but neither
timer is installed/enabled anywhere by this repository, and actual
cadence is an operational decision). `Persistent=true` lets a missed run
catch up automatically after a reboot/outage instead of silently waiting
for the next scheduled time.

Application code never enables, starts, or otherwise touches these
units — installing and enabling them is a manual operator action (see
the comments at the top of each `.service` file).

### Logs: journald vs. integration.sync_runs

Two different, complementary views:

- **`journalctl -u academic-moodle-sync.service`** (or
  `academic-attendance-sync.service`) / **`systemctl status <unit>`** —
  system-level execution status: did the process run, when, did it exit
  non-zero, and its stdout/stderr. Each sync logs cleanly to
  stdout/stderr for exactly this — no custom log file handling is
  needed for core operation.
- **`integration.sync_runs`** — pipeline-level operational detail: row
  counters, `status`, `error_message`, `snapshot_time`, per batch, per
  `source_system` (`moodle` or `attendance`). Lives in the Academic
  Database regardless of how the job was invoked.

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
Moodle schema (`tests/integration/moodle/fake_moodle.py`); Attendance-
sourced tests run against a minimal fake Attendance schema
(`tests/integration/attendance/fake_attendance.py`) — both created in
the same disposable test database.

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

- Actually enabling/installing either systemd timer and deciding
  production cadence — example units exist (`deploy/systemd/`), but
  nothing runs them yet and the schedule is an operational decision
- Deploying the Attendance sync at all (Moodle's is in production;
  Attendance's is reference material only at the end of Phase 3)
- Incremental extraction for either pipeline (both are full-extraction
  only)
- `auth` tables and API authentication / API keys
- Academic API endpoints, grades, assignments, participation, absence
  calculations, and attendance percentages — ingestion records source
  facts only
