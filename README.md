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
foundation, two ingestion pipelines — Moodle (students, courses,
enrollments, and — since Phase 4 — grade items/student grades) and
Attendance (attendance sessions/records only — Attendance never creates
students or courses of its own; see below) — a read-only Academic API
over the resulting canonical data (Phase 5), API-key
authentication/authorization protecting it (Phase 6), and, since
Phase 7, a weighted evaluation engine that explains a student's current
grade — evaluation categories, weights, and the calculation itself are
owned by this platform, never by Moodle.

## Current phase: Phase 7 — Weighted Evaluation Engine

Phase 0 built the project skeleton and shipped a validated production
deployment (`GET /health` only). Phase 1 added the database foundation.
Phase 2 added the Moodle ingestion pipeline, now running in production
every 30 minutes. Phase 3 added a working Attendance ingestion pipeline:
read-only extraction → `raw_attendance` → `staging` → validation/
reconciliation → a transactional merge into `academic`. Phase 4 added
grade ingestion — grade items and student grades — as part of the same
Moodle sync process, only for real, module-backed activities (never the
course total or any category aggregate). Phase 5 added the first
product read API: four read-only endpoints over `academic.*` (courses,
attendance, grades, and a conservative summary) — internal/unauthenticated,
explicit canonical `student_id`s. Phase 6 closes that gap: every request
now needs an `X-API-Key`, resolved to either a STUDENT identity (scoped
to `/me/*`, their own data only) or an ADMIN identity (scoped to
`/students/{student_id}/*`, any student) — see "API key authentication
(Phase 6)" below for the full model. Phase 7 adds a weighted evaluation
engine on top of that authenticated API: evaluation categories, their
weights, and which grade items count toward the current grade are
configuration this platform owns (never inferred from Moodle, never
written back to it), and a new calculation layer turns that
configuration plus the canonical grades already ingested into a fully
transparent, reconstructable "current grade" — see "Weighted evaluation
engine (Phase 7)" below.

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

The Academic API queries **only** `academic` (since Phase 5, for the
four read endpoints below). RAW and staging are internal pipeline
concerns and are never queried by the API.

### PostgreSQL schemas

| Schema | Purpose | Status in Phase 4 |
|---|---|---|
| `raw_moodle` | Landing representation of selected Moodle source entities, as extracted — faithful, append-only, never validated. | `students`, `courses`, `enrollments`, `grade_items`, `student_grades` |
| `raw_attendance` | Landing representation of selected Attendance source entities, as extracted — faithful, append-only, never validated. Never coordinates/distance. | `students`, `sessions`, `attendances` |
| `staging` | Normalized/validated candidate rows for one batch, rebuilt on every run. Not a system of record. | `students`, `courses`, `enrollments`, `attendance_students`, `attendance_sessions`, `attendance_records`, `grade_items`, `student_grades` |
| `academic` | Curated canonical data. The only schema the Academic API reads from. | `students`, `courses`, `enrollments`, `attendance_sessions`, `attendance_records`, `grade_items`, `student_grades` |
| `integration` | Source-identity mappings and pipeline observability (never business data). | `student_sources`, `course_sources`, `enrollment_sources`, `attendance_session_sources`, `attendance_record_sources`, `grade_item_sources`, `student_grade_sources`, `sync_runs`, `sync_state`, `sync_issues` |
| `auth` | Reserved for future API authentication. | Empty — no tables yet |

`auth` remains empty — established only for architectural boundaries;
API authentication is a later phase. Attendance students reconcile into
the *existing* `integration.student_sources` table (just another
`source_system`) rather than a new mapping table; Moodle grades resolve
students and courses through the *existing* `student_sources`/
`course_sources` mappings too, creating neither a new student mapping
table nor any canonical students of their own — see below.

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

### Moodle grades ingestion pipeline

```
Moodle (read-only, same credential as students/courses/enrollments)
        ↓  one REPEATABLE READ, READ ONLY transaction (its own snapshot)
  extraction              app.integration.moodle.grades_source
        ↓
  raw_moodle.grade_items / student_grades   faithful landing copy, hidden included
        ↓
  staging.grade_items / student_grades      normalized candidates, hidden excluded
        ↓
  validation               batch checks + course resolution — only if zero issues
        ↓
  canonical merge           one transaction: academic.* + integration.*_sources
        ↓
  integration.sync_runs / sync_state
```

Implemented in `app/integration/moodle/` alongside the primary pipeline:
`grades_source.py`, `grades_hashing.py`, `grades_raw_writer.py`,
`grades_staging_writer.py`, `grades_validation.py`, `grades_merge.py`,
`grades_runs.py`, `grades_sync.py` — same shape as the rest of the
platform, kept in separate `grades_*` modules (rather than folded into
the existing `source.py`/`merge.py`/etc.) because grades get their own
`integration.sync_runs` row/entity_type (`grade_items_student_grades`,
distinct from `students_courses_enrollments`) and depend on — rather
than create — the mappings the primary sync maintains.

**Grade-item filter: only real activities.** Moodle's gradebook has one
`mdl_grade_items` row per course for the course total
(`itemtype='course'`, `itemname` `NULL`/empty) plus one row per category
aggregate, in addition to one row per actual gradable activity
(`itemtype='mod'`, e.g. `itemmodule='assign'` with a real `itemname`).
Only `itemtype='mod'` rows are ever selected — the extraction query's
`WHERE itemtype = 'mod'` clause excludes the course total and any
category totals before they ever reach `raw_moodle`, not by later
filtering. Grades are joined back through `mdl_grade_items` scoped the
same way, so a grade can never be extracted for an item outside the
configured course or outside `itemtype='mod'` either.

**`finalgrade` is the canonical grade — never `rawgrade`.** Moodle
computes `finalgrade` from `rawgrade` after any adjustments/overrides;
it is the value a student would actually see, and the only one this
platform ingests. `finalgrade IS NULL` means "not graded yet"; `0` means
"graded, with a real score of zero." These are never conflated: `grade`
in `academic.student_grades` is nullable specifically so `NULL` can flow
through untouched end-to-end (extraction → RAW → staging → canonical),
and `app.integration.moodle.grades_hashing.student_grade_hash` treats
`None` and `0` as distinct content, so a transition between them is
never silently absorbed as "unchanged." Proven directly in
`tests/integration/moodle/test_grades_merge.py` and
`tests/unit/test_moodle_grades_hashing.py`.

**Minimal-data principle.** Only what "activity name, grade received,
maximum grade" actually needs is ingested:
`mdl_grade_items.id`/`itemname`/`itemmodule`/`grademax`/`hidden`/
`timemodified`, and `mdl_grade_grades.id`/`itemid`/`userid`/
`finalgrade`/`hidden`/`timemodified`. Never `rawgrade`/`rawgrademin`/
`rawgrademax`, `feedback`/`information`, `overridden`/`excluded`,
aggregation weights or category calculations, grade history, letters,
outcomes, or scales — none of that is needed for the current product and
none of it is ever ingested, at any pipeline stage. `itemmodule` is kept
only as `academic.grade_items.activity_type`, for traceability — the
Moodle gradebook itself is never modeled beyond that.

**Hidden data: excluded from canonical, not just flagged.** A hidden
grade item, or an individual hidden grade, must never reach
`academic` without an explicit product decision to expose it — Phase 4
has no API yet, so the simpler and safer choice is exclusion, not a
`hidden` column threaded through staging/canonical that a future change
could accidentally start reading. `hidden` is preserved faithfully in
`raw_moodle` (a complete, faithful record of what extraction observed),
but `app.integration.moodle.grades_staging_writer.write_staging_grades_batch`
never stages a hidden grade item, and never stages a grade that is
itself hidden *or* whose parent item is hidden — Moodle's own semantics
make a hidden item hide every grade under it regardless of any per-grade
override, so both conditions are checked. Exclusion for being hidden is
silent (no `issues` entry, no blocking failure, no `sync_issues` row) —
it is a deliberate design choice, not a data-quality problem. Tested in
`tests/integration/moodle/test_grades_staging_quality.py`.

**Student resolution: through the existing Moodle mapping, never a new
one.** A grade's `userid` is the same Moodle user id the primary sync
already maps via `integration.student_sources`
(`source_system='moodle'`). Grades resolution is a read-only lookup
against that *existing* mapping — `app.integration.moodle.grades_merge`
creates zero new `student_sources` rows and zero new canonical students;
if `userid` doesn't resolve, this is deliberately **not** a blocking
error, following the same operationally-safe pattern
`app.integration.attendance.merge` established for unresolved Attendance
students: the specific grade is skipped (`rows_skipped` counts it) and
an `integration.sync_issues` row is opened/refreshed
(`source_system='moodle'`, `issue_type='UNRESOLVED_GRADE_STUDENT'`,
`source_entity='student_grade'`, `source_id` = the Moodle grade row id,
`reference_value` = the Moodle user id) instead of failing the whole
batch — see `app.integration.issues` and
`tests/integration/moodle/test_grades_issues.py` for the full
open/resolve lifecycle. Because Phase 4 always does a full extraction,
the very next sync re-attempts resolution from scratch: once the primary
sync creates that student's mapping, the grade imports automatically,
nothing lost. Unlike Attendance's `account_number` reconciliation, a
grade's `userid` can never resolve to *more than one* academic student —
`integration.student_sources` has `UNIQUE(source_system, source_id)` —
so there is no ambiguous case to guard against.

**Course resolution: through the existing Moodle mapping, never
hardcoded, and blocking if missing.** Same pattern as Attendance:
`MOODLE_COURSE_ID` is resolved through `integration.course_sources`
(`source_system='moodle'`) by
`app.integration.moodle.grades_validation.resolve_moodle_course_id` —
never a hardcoded `academic.courses.id`. Unlike an unresolved student,
a missing course mapping **fails the whole batch**: without it, a grade
item has nowhere to point in `academic.grade_items.course_id`, which is
`NOT NULL`. In production this mapping is never actually missing by the
time grades run — the primary students/courses/enrollments sync (which
creates it) always runs first, in the same process invocation.

**Full extraction, on purpose.** Same rationale as Phase 2/3: current
grade volume is tiny, so Phase 4 re-extracts the whole configured
course's grade items/grades on every run rather than tracking an
incremental cursor. `integration.sync_state`
(`entity_type='grade_items_student_grades'`) still records the last
successful batch's id/snapshot time for a later phase to build on.

**Consistent snapshot.** Both extraction queries (grade items, grades)
run inside their own `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ
READ ONLY` transaction — same isolation strategy as Phase 2/3 — so grade
items and the grades that reference them represent one coherent
snapshot of Moodle's gradebook, independent of (and not sharing a
transaction with) the primary sync's own snapshot.

**Idempotency.** Change detection is by `source_hash`, same deterministic
SHA-256-over-business-fields approach as everywhere else in this
platform (`app/integration/moodle/grades_hashing.py`) — never
`batch_id`/`ingested_at`/`source_updated_at`. Re-running identical
source state yields `rows_inserted=0, rows_updated=0, rows_unchanged=N`.
A grade change (e.g. `30 → 80`) updates the same canonical
`academic.student_grades` row (matched via
`integration.student_grade_sources`) — never a duplicate row; a grade
item's name change updates the same canonical `academic.grade_items`
row the same way.

**Grades integrated into the existing Moodle sync — no second
scheduler.** `app.integration.moodle.sync.main()` (the same
`academic-moodle-sync.service` one-shot systemd unit, and the same
`python -m app.integration.moodle.sync` command) runs the primary
students/courses/enrollments sync, then `run_moodle_grades_sync`, in one
process invocation — exactly the operational model this phase called
for: one coherent Moodle sync execution, not a second timer/service.
Grades run even if the primary sync failed (they resolve through
whatever mappings already exist from the last successful run, and
withholding otherwise-mergeable grade data on a transient primary
failure has no benefit); each stage gets its own `integration.sync_runs`
row and is independently observable, and the process exits non-zero if
either stage failed. See `deploy/systemd/academic-moodle-sync.service`
and `deploy/systemd/moodle-sync.env.example` — unchanged, since grades
need no new environment variables or credentials.

**Failure behavior.** Same as the rest of the platform: a blocking
validation issue (missing course mapping, missing grade-item name,
invalid `max_grade`, an unknown `grade_item_source_id` reference, a
duplicate grade for the same item+student, or a duplicate source
identity) or any merge exception leaves `academic` and the `sync_state`
watermark exactly as they were, and records the run as `FAILED` with an
`error_message`.

**Security boundary.** No new credentials or environment variables:
grades are extracted with the same `academic_sync_moodle` (now also
granted `SELECT` on `mdl_grade_items`/`mdl_grade_grades`) and merged
with the same `academic_ingest_moodle` (now also granted on
`academic.grade_items`/`academic.student_grades` — see
`deploy/sql/academic_ingest_moodle_grants.example.sql`) as the primary
sync. The public API never receives Moodle credentials; it reads grade
data only from `academic.*`, via the Phase 5 read API below.

### Academic read API (Phase 5)

The first product-facing endpoints, over canonical `academic.*` only.
Implemented in `app/api/routes/students.py` (HTTP layer) →
`app/services/student_read_service.py` (the one business rule this
phase owns: "student doesn't exist" vs. "student exists, no records") →
`app/repositories/student_read_repository.py` (explicit SQLAlchemy
queries, one per endpoint, no ORM relationship traversal so there's no
N+1 to worry about) → the Academic PostgreSQL. Response shapes are
explicit Pydantic models (`app/api/schemas/students.py`) — an ORM
object is never returned directly, so a column can never leak into the
API contract by accident.

**No authentication yet — internal/testing use only.** Phase 5
deliberately has no JWT, API keys, OAuth, Telegram auth, `/me`
endpoint, or role-based access control; those are Phase 6. Until then,
`student_id` in the URL is the literal canonical `academic.students.id`
— acceptable only because the API remains localhost/internal, never
exposed publicly (same posture as every other phase so far).

**Canonical-data-only.** Every query in
`student_read_repository.py` reads `academic.*` exclusively — never
`integration.*` (source mappings, `sync_runs`/`sync_state`/
`sync_issues`), never `raw_moodle.*`/`raw_attendance.*`/`staging.*`, and
the API process never imports a Moodle/Attendance source adapter at
all (`tests/unit/test_api_architecture_isolation.py` asserts this by
inspecting the actual import statements). A source-system id, a raw
hash, or any sync-observability field is never present in a response.

**Endpoints** (all `GET`, all read-only, all under `/students/{id}`):

| Endpoint | Reads | Returns |
|---|---|---|
| `/courses` | `students`, `enrollments`, `courses` | enrolled courses |
| `/attendance` | `attendance_sessions`, `attendance_records`, `courses` | recorded attendance events |
| `/grades` | `grade_items`, `student_grades`, `courses` | canonical grades |
| `/summary` | all of the above | conservative aggregate counts |

Sample `GET /students/1/grades`:

```json
{
  "student_id": 1,
  "grades": [
    {
      "course_id": 1,
      "grade_item_id": 1,
      "name": "Tarea 01 — Identificación de Configuration Items",
      "activity_type": "assign",
      "grade": 30.0,
      "max_grade": 100.0
    }
  ]
}
```

**Unknown vs. empty — the one rule every endpoint follows the same
way.** An unknown `student_id` (no matching `academic.students` row)
returns **404** with a consistent body, `{"detail": "Student not
found"}`, from a single `StudentNotFoundError` exception raised by the
service layer and caught by one FastAPI exception handler in
`app/main.py` — never a per-route try/except, never a `200` with an
empty/null object standing in for "doesn't exist". A student who
*exists* but has no enrollments/attendance/grades yet is not an error
at all: **200**, with empty lists and zeroed counts. Distinguishing
these two cases is the one piece of business logic
`student_read_service.py` owns; the repository layer only ever answers
"what rows match", never "does this id mean something."

**`grade`: `null` vs. `0`, never conflated.** Exactly the Phase 4
invariant, preserved through the API: `null` means not graded yet; `0`
is a real grade of zero. The repository passes
`academic.student_grades.grade` through untouched (still nullable);
the service layer converts `Decimal` → `float` explicitly (`float(x) if
x is not None else None`) before constructing the response model, so a
`Decimal` never reaches JSON serialization directly and a `NULL` can
never be silently coerced to `0.0` by an implicit conversion.

**Attendance semantics — recorded presence only, never inferred
absence.** `academic.attendance_records` only ever represents a
positive event: "this student was recorded present at this session."
There is no absence record and no reliable way, from this schema alone,
to reconstruct which sessions a student *should* have attended but
didn't — that would require a full expected-roster/expected-session
model this phase does not build. Accordingly, `present` in every
`/attendance` entry is always `true` (included for shape stability, not
because it varies), and a session the student has no record for simply
does not appear in the response — it is never synthesized as an
`"absent"` entry. Consumers must not treat "N events returned" as "N
out of some total" without an external source of the expected total.

**No invented aggregates.** `/summary` reports only counts a `COUNT`
query already answers correctly: `courses_count`, `sessions_recorded`,
`graded_items`/`ungraded_items`. It deliberately does **not** compute a
GPA, a course average, an attendance percentage, a pass/fail status, or
a risk score. A course average needs Moodle gradebook aggregation
semantics (category weights, extra credit, drop-lowest rules) that
Phase 4 explicitly did not model; an attendance percentage needs a
correct denominator (the number of sessions a student was *expected* to
attend), which the canonical schema cannot currently answer safely.
Both are deferred, not forgotten — see "What Phase 5 does not implement
yet" below.

**Deterministic ordering.** Every list is ordered explicitly, never left
to incidental DB/insertion order: courses by `course_id`, attendance
chronologically by the session's `opened_at` (with `session_id` as a
tiebreaker), grades by `grade_item_id`. Two identical requests always
return identical JSON.

**No migration.** Phase 5 is a read layer over the schema
`0006_grades_ingestion` already delivered — every column every endpoint
needs already exists. No new table, column, or index was added.

**No write path.** Every repository function issues a `SELECT` only;
nothing in this phase ever calls `INSERT`/`UPDATE`/`DELETE`, triggers a
sync, or has any side effect —
`tests/api/test_read_only.py` proves canonical row counts are unchanged
across a full round of requests, including a 404 path.

### API key authentication (Phase 6)

Every route except `GET /health` now requires an `X-API-Key` header.
Implemented in `app/auth/`: `models.py` (the `auth.api_keys` ORM model),
`api_keys.py` (generation, hashing, issue/rotate/revoke/list —
persistence, no HTTP), `dependencies.py` (the FastAPI security
dependencies that authenticate a request), and `manage_api_keys.py`
(the administrative provisioning CLI — the *only* way a key is ever
created; there is no endpoint for it).

```
HTTP request -> X-API-Key -> SHA-256 -> auth.api_keys lookup (read-only)
    -> role/student resolution -> route-level role check
```

**Two roles, two audiences.** A **STUDENT** key belongs to exactly one
canonical `academic.students` row and may only ever call `/me/*` — it
carries no way to specify *whose* data to return, because `student_id`
is resolved from the credential itself
(`app.auth.dependencies.require_student`), never accepted as a path
parameter, query parameter, or body field. An **ADMIN** key is not tied
to any student and may call `/students/{student_id}/*` for any
canonical id (`app.auth.dependencies.require_admin`), intended for
instructor/administrative use. A key is exactly one role, forever — a
role is never upgraded or shared between the two endpoint families.

**Header only — never a query parameter, URL, or path segment**, so a
key never ends up in a server access log or shared/bookmarked URL:

```bash
curl -H "X-API-Key: canumpe_stu_EXAMPLE_NOT_REAL" http://127.0.0.1:8080/me/grades
```

**`/me/*` endpoints** — identical product semantics to their `/students/{student_id}/*`
counterparts (same service/repository code, see "Reuse, not
duplication" below), scoped to the caller's own identity:

| Endpoint | Returns |
|---|---|
| `GET /me` | `{"student_id": 7, "account_number": "423090349"}` — nothing else, never an API key hash/id, integration mapping, or Moodle/Attendance id |
| `GET /me/courses` | the caller's own enrolled courses |
| `GET /me/attendance` | the caller's own recorded attendance events |
| `GET /me/grades` | the caller's own canonical grades |
| `GET /me/summary` | the caller's own conservative summary |

**Reuse, not duplication.** `/me/*` calls the exact same
`app.services.student_read_service` functions Phase 5's
`/students/{student_id}/*` routes use — the only new code is `GET /me`
itself (a small `get_student_identity` addition to that same service/
repository, since Phase 5 never needed to expose `account_number`). The
NULL-vs-zero grade rule, the no-absence-inference attendance rule, and
the no-invented-aggregates summary rule from Phase 5 therefore apply to
`/me/*` automatically, not by re-implementation.

**Key format: `canumpe_stu_<random>` / `canumpe_adm_<random>`.**
Generated by `secrets.token_urlsafe(32)` — 256 bits of
cryptographically secure randomness, never `random`, a bare UUID, a
timestamp, an account number, a Telegram id, or a student id (see
`app.auth.api_keys.generate_student_key`/`generate_admin_key`).

**Plaintext is never stored — shown exactly once.** `auth.api_keys`
stores only `key_hash` (`SHA-256(plaintext)`, hex, `UNIQUE NOT NULL`)
and `key_prefix` (a short, non-secret slice of the plaintext — enough
to recognize a credential in a listing, never enough to reconstruct the
secret). The plaintext is returned to the operator's terminal exactly
once, at `issue-*`/`rotate-student` time, by the provisioning CLI — it
is never logged, never re-derivable from the database, and never
recoverable if lost. If lost: rotate, don't try to recover it.

**Schema** (migration `0007_api_key_auth`, `auth.api_keys`): `id`,
`key_hash`, `key_prefix`, `role` (`'student'`/`'admin'`, `CHECK`
enforced), `student_id` (nullable FK to `academic.students.id`,
`RESTRICT`), `label`, `created_at`, `revoked_at`. Two constraints do the
real work, at the database level, not just in application code:
- `ck_api_keys_role_student_id_consistency`: `role='student'` rows
  always have a `student_id`; `role='admin'` rows never do.
- `uq_api_keys_active_student`: a **partial unique index** on
  `student_id` where `role='student' AND revoked_at IS NULL` — at most
  one *active* student key per student, at any time. Rotation (not a
  second `issue-student`) is the supported way to replace one. Admin
  rows are unaffected (multiple `NULL`s never conflict in a unique
  index), so several admin keys may coexist.

**Provisioning is CLI-only — there is no endpoint that creates a key.**
Run with the existing application image, never a host-native Python
install:

```bash
docker compose -f compose.prod.yml run --rm api \
    python -m app.auth.manage_api_keys issue-student --account-number 423090349

python -m app.auth.manage_api_keys issue-admin --label "Ulises"
python -m app.auth.manage_api_keys rotate-student --account-number 423090349
python -m app.auth.manage_api_keys revoke --id 3
python -m app.auth.manage_api_keys list
```

`issue-student` resolves the account number, fails clearly if it
doesn't exist (`StudentNotFoundError`) or if the student already has an
active key (`ActiveStudentKeyExistsError` — use `rotate-student`
instead), then prints the plaintext key and its id/prefix once.
`rotate-student` revokes every currently-active key for that student
and issues a new one in the same transaction, so a failure partway
through never leaves the student locked out with no key at all.
`revoke` sets `revoked_at`; it never deletes the row — credential
history is permanent. `list` prints only safe metadata (id, prefix,
role, the associated account number or label, status, `created_at`) —
never a plaintext key, never a full `key_hash`.

**HTTP semantics — every authentication failure looks identical.**
Missing, malformed, unknown, and revoked keys all return the exact same
generic `401` (`{"detail": "Invalid or missing API key"}`) — a caller
can never learn whether a specific key exists by observing a different
error. A *valid* key used against the wrong endpoint family (a STUDENT
key on `/students/{student_id}/*`, or an ADMIN key on `/me/*`) returns
`403` naming the role that *was* required (`"Admin API key required"` /
`"Student API key required"`) — the credential is real, just not
authorized for that route. An admin key against an unknown
`student_id` still returns the Phase 5 `404`.

**Authentication is read-only.** `get_active_key_by_hash` (used on
every request) only ever does a `SELECT` — there is no `last_used_at`
column and no per-request write of any kind; usage telemetry, if ever
needed, is a later phase's problem, not this one's.

**Manual, out-of-band distribution — no Telegram integration yet.**
Keys are issued by an instructor/admin running the CLI directly and
handed to the student through Moodle, email, paper, or another trusted
channel. A future Attendance-bot `/apikey` command *may* eventually
wrap this same provisioning capability, but Phase 6 does not touch the
bot, its Telegram handlers, its database, or any Telegram identity
mapping — that integration is explicitly out of scope here.

**No public exposure yet.** The API is still localhost/internal only —
authentication had to exist and be accepted in production *before* any
future Nginx/Cloudflare Tunnel exposure, which is a separate
operational step this phase does not perform.

### What Phase 6 does not implement yet

- Public exposure of the API — still localhost/internal only; that's a
  separate later operational step, after production acceptance of
  authentication itself
- A Telegram `/apikey` command or any other bot/Telegram change — keys
  are distributed manually (Moodle, email, paper) for now
- Usage/audit telemetry (e.g. `last_used_at`) — authentication stays a
  pure read on every request
- Key expiration or scheduled rotation — a key is active until
  explicitly revoked or rotated
- Any endpoint that creates, lists, or revokes a key over HTTP —
  provisioning is CLI-only, run against the application image
- GPA, course averages, attendance percentages, pass/fail status, or
  risk scores — unchanged from Phase 5; see "No invented aggregates"
  further up
- Absence tracking or any session/roster model that would make an
  attendance percentage safe to compute
- CRUD or write endpoints of any kind — every route remains strictly
  read-only
- CACEI evidence generation or any other downstream reporting
- No weighted categories, course-total/aggregate grades, or the complete
  Moodle gradebook — only real `itemtype='mod'` activities, exactly
  "activity name, grade received, maximum grade"
- No historical grade tracking — a grade change updates the existing
  canonical row in place; there is no audit trail of prior values yet
- No cron — scheduling is `deploy/systemd/academic-attendance-sync.timer`
  and `academic-moodle-sync.timer`, example material; production cadence
  is not decided by this repository
- No incremental extraction (full source re-extraction every run —
  current volume is tiny)
- `GET /health` is unchanged from Phase 0 and remains unauthenticated —
  the API still never queries Moodle or Attendance and never receives
  their credentials

### Weighted evaluation engine (Phase 7)

Phase 5 gave students their raw, atomic grades. Phase 7 answers the
question those raw numbers can't answer on their own: *"why do I
currently have a 7.2?"* It does this without ever replacing the atomic
data — `GET /me/grades` and `GET /me/attendance` remain first-class,
unabridged endpoints; Phase 7 only enriches the grades response and
adds new, purely additive endpoints on top.

**This platform, not Moodle, owns evaluation configuration.** Moodle
remains the system of record for students, courses, grade items, and
recorded grades. It has never been asked, and is never consulted, for
category weights, the grade-item-to-category mapping, or whether an
item currently counts toward a grade — those are configuration this
platform defines and stores itself (`academic.grade_categories`,
`academic.grade_item_evaluation`), and they are never written back to
Moodle. The evaluation engine also never touches Attendance or
Telegram data; "current grade" is a Moodle-grades-only concept.

**0–100 normalization, computed, never stored raw.** Every grade item
has its own `max_grade` (20, 100, whatever the instructor set in
Moodle); comparing or averaging across items only makes sense on a
common scale. `score_100 = (grade / max_grade) * 100` is computed in
the calculation layer (`app/services/grade_normalization.py`) on every
read — the original `grade`/`max_grade` are never overwritten or
dropped, so a client always has both the source numbers and the
normalized one. Example: `grade=75, max_grade=100` → `score_100=75.0`;
`grade=18, max_grade=20` → `score_100=90.0`.

**`null` is not `0` — enforced from the database up through the API.**
An ungraded item (`academic.student_grades.grade IS NULL`) means "not
graded yet," not "earned zero." `score_100` for such an item is `null`,
never `0.0`; a `null`-grade item is excluded from its category's
average entirely (see below) rather than counted as a zero. A grade
that really is `0` is preserved as the number `0` at every layer and
included normally. This is the same rule Phase 5 already enforced for
raw grades ("No invented aggregates"); Phase 7 extends it through
normalization and category averaging so it can never be reintroduced
by a later calculation.

**Evaluation categories** (`academic.grade_categories`): a course's
grading scheme is a flat list of named categories, each with a
`weight_percent` (`NUMERIC(5,2)`, never a float — so `12.50 + 87.50`
is exactly `100.00`, not `99.99999999999999`) and a `sort_order` for
display. **A course's category weights must sum to exactly 100** —
90 or 110 is rejected, decimals like `25.00`/`12.50` are fine. This is
a cross-row invariant (the sum of every row for a course), so it can't
be a single-row `CHECK` constraint; it's enforced in
`app.services.evaluation_service` before any write ever reaches the
database.

**Grade-item assignment** (`academic.grade_item_evaluation`): each
grade item maps to **at most one** category — enforced structurally by
making `grade_item_id` the table's primary key (and foreign key to
`academic.grade_items`), not just a unique index — plus an explicit
`counts_toward_current_grade` boolean. That boolean is the *only* thing
that decides whether an item is included in a current-grade
calculation. It is never inferred from whether the item has a due
date, whether "enough time" has passed, whether another student
already has a grade for it, or from the grade being `NULL` — an
instructor (via the future admin app; Phase 7 ships the API only, see
below) sets it explicitly, and a not-yet-due assignment with
`counts_toward_current_grade=false` stays visible in `/me/grades` with
its real `null` grade, it simply doesn't participate in the current
grade yet.

**Real Moodle activity types, never relabeled.** An item's
`activity_type` (`assign`, `quiz`, ...) already comes straight from
Moodle since Phase 4 and is passed through unchanged — Phase 7 never
assumes `quiz` means "exam" or `assign` means "homework." Meaning comes
from the *category* an instructor assigns the item to (its `name`,
freely chosen), combined with the real activity type, not from
guessing at Moodle's internal module names. This is also why Phase 7
deliberately does **not** add `/me/tasks` or `/me/exams` — a client
that wants "just the exams" filters the enriched `/me/grades` list by
`category_name`/`activity_type` itself; the API stays one general
endpoint, not one per possible grouping.

**`GET /me/grades` — enriched, not replaced.** The existing atomic
response gains five fields per item; nothing already there was removed
or renamed:

```json
{
  "course_id": 1,
  "grade_item_id": 12,
  "name": "Tarea 01",
  "activity_type": "assign",
  "grade": 75.0,
  "max_grade": 100.0,
  "score_100": 75.0,
  "category_id": 3,
  "category_name": "Tasks",
  "category_weight_percent": 30.0,
  "counts_toward_current_grade": true
}
```

An item Moodle hasn't graded yet, and/or one an instructor hasn't
configured a category for, still appears — `score_100`/`category_id`/
`category_name`/`category_weight_percent` are simply `null`, and
`counts_toward_current_grade` is `false`:

```json
{
  "course_id": 1,
  "grade_item_id": 13,
  "name": "Tarea 02",
  "activity_type": "assign",
  "grade": null,
  "max_grade": 100.0,
  "score_100": null,
  "category_id": null,
  "category_name": null,
  "category_weight_percent": null,
  "counts_toward_current_grade": false
}
```

**`GET /me/attendance` is untouched.** Phase 7 does not use attendance
for anything — no course grade ever depends on it, and the endpoint
still returns the same atomic, never-summarized event list Phase 5
defined.

**Category score: an equal-weight average of graded, counted items
only.** Within a category, Phase 7 does not model per-item weights
(a future phase might); every currently-counted, actually-graded item
in the category contributes equally to that category's `score_100`.
`null`-graded items are excluded from the average, not treated as `0`.
Example: `Tarea01=80, Tarea02=100, Tarea03=70` (all counted, all
graded) → category score `= (80 + 100 + 70) / 3 = 83.33`.

**Category contribution: how many of the course's 100 points this
category is worth so far.**
`category_contribution = category_score_100 × category_weight_percent / 100`.
Continuing the example, if Tasks is weighted 30%:
`83.33 × 30 / 100 = 25.00` points toward the course's eventual 100.

**A category with nothing gradable yet simply doesn't participate —
it is never treated as a zero.** A category counts toward the overall
calculation only if it has at least one grade item with
`counts_toward_current_grade=true` **and** an actual non-`null` grade
recorded for the student. A category with no items yet, or whose only
items are still ungraded, is "not currently calculable" for that
student; it contributes nothing to either side of the current-grade
ratio below — not a `0` score, not a `0` weight.

**Current grade: weighted points earned *of the portion evaluated so
far* — two different numbers, never confused.** This is the part most
prone to being computed wrong, so the engine reports all four
quantities that go into it, not just the final answer:

| Field | Meaning |
|---|---|
| `weighted_points_earned` | sum of every calculable category's `contribution_points` — literal points toward the course's 100, earned so far |
| `evaluated_weight_percent` | sum of `weight_percent` across only the calculable categories — how much of the 100% the course has actually been graded on so far |
| `current_score_100` | `weighted_points_earned / evaluated_weight_percent × 100` — performance *over the evaluated portion*, not over the whole course |
| `current_grade_10` | `current_score_100 / 10` — the same figure on the familiar 0–10 scale |

The worked example from the spec, verified end-to-end (service-level
unit test and a live smoke test against a running container):

```
Tasks:         weight=30%, score=80  → contribution=24
Exams:         weight=20%, score=60  → contribution=12
Project:       weight=30%, not yet gradable → excluded
Participation: weight=20%, no items yet     → excluded

weighted_points_earned    = 24 + 12 = 36
evaluated_weight_percent  = 30 + 20 = 50
current_score_100         = 36 / 50 × 100 = 72.0
current_grade_10          = 72.0 / 10 = 7.2
```

`36` is *not* "the current grade" — it's raw points earned toward a
100-point course where only half the weight has been evaluated so far.
`72.0`/`7.2` is the actual answer to "how am I doing," and the API
returns both, plus every category-level number needed to reconstruct
either one by hand.

**If nothing is calculable yet, the grade is `null` — never `0`.** If
`evaluated_weight_percent` would be `0` (no category has any counted,
graded item), `current_score_100` and `current_grade_10` are both
`null`. Dividing by zero is never attempted, and an empty course is
never reported as a failing `0.0`.

**Decimal throughout, rounded only at the boundary.** Every
intermediate value — normalized scores, category averages, weights,
contributions, the running `weighted_points_earned`/
`evaluated_weight_percent` totals — is `Decimal` arithmetic
(`app/services/evaluation_service.py`), never `float`, and never
rounded until the final Pydantic response model is built. Displayed
figures (`score_100`, `weight_percent`, `contribution_points`,
`current_score_100`, `current_grade_10`) are rounded to 2 decimal
places (`round()`, half-up) only at that last step, so a chain of
category averages can't drift from repeated intermediate rounding.

**`GET /me/evaluation`** — the full, transparent breakdown for the
caller's own current grade (student key only; `course_id` is optional
when the student is enrolled in exactly one course):

```json
{
  "student_id": 1,
  "course_id": 1,
  "weighted_points_earned": 36.0,
  "evaluated_weight_percent": 50.0,
  "current_score_100": 72.0,
  "current_grade_10": 7.2,
  "categories": [
    {
      "category_id": 1,
      "name": "Tasks",
      "weight_percent": 30.0,
      "category_score_100": 80.0,
      "contribution_points": 24.0,
      "counted_items": 1,
      "graded_items": 1,
      "ungraded_items": 0,
      "items": [
        {
          "grade_item_id": 10,
          "name": "Tarea 01",
          "activity_type": "assign",
          "grade": 80.0,
          "max_grade": 100.0,
          "score_100": 80.0
        }
      ]
    }
  ]
}
```

Every number above the `categories` list is reconstructable from the
numbers inside it — nothing in the response depends on a calculation
the caller can't reproduce.

**`GET /students/{student_id}/evaluation`** — the identical breakdown,
admin-only, for instructor use investigating a specific student. A
student key gets `403`; an unknown `student_id` gets `404`; the
underlying calculation is the exact same `evaluation_service` function
Phase 7's `/me/evaluation` uses.

**`GET/PUT /admin/courses/{course_id}/evaluation-scheme`** — admin-only
configuration of a course's categories and grade-item assignments.
`GET` returns the current scheme plus any canonical grade items not
yet assigned to a category (useful for building an admin UI later —
none is built in Phase 7 itself). `PUT` replaces the **entire** scheme
atomically: the full category list (with their grade-item assignments)
is validated as a whole — weights sum to exactly 100, no grade item
assigned twice, every referenced grade item exists and belongs to this
course — and only if the whole payload is valid does anything get
written; an invalid `PUT` changes nothing (`InvalidEvaluationSchemeError`
→ `400`, with no partial category/assignment rows left behind). This
is deliberately whole-scheme replacement rather than small per-category
CRUD endpoints, matching the reality that categories and weights are
edited together, not one field at a time.

**Migration `0008_evaluation_engine`** adds exactly the two tables
above (`academic.grade_categories`, `academic.grade_item_evaluation`)
— no UI-specific table, no change to any existing table.

**Authorization, unchanged in shape from Phase 6.** A student key
reads its own atomic grades/attendance/evaluation and nothing else; it
can never read another student's evaluation and never call any
`/admin/*` route (`403`). An admin key can read any student's
evaluation and read/replace any course's scheme, but has no `/me/*`
identity of its own (`403` on `/me/evaluation`, same as every other
`/me/*` route since Phase 6).

**No UI.** Phase 7 is API-only, on purpose — no Streamlit page, no
React app, no professor dashboard ships in this repository. The API is
designed so a future, separate application (a student-facing dashboard,
an instructor tool, anything else) can be built entirely against it;
students are not expected to compute their own current grade by hand,
but nothing in this response *requires* a client to trust the final
number without being able to check it.

### What Phase 7 does not implement yet

- Any UI — no dashboard, no admin page for editing evaluation schemes;
  `PUT /admin/courses/{course_id}/evaluation-scheme` exists only as an
  API a future admin tool will call
- Per-item weights *within* a category (e.g. "this quiz counts double
  its neighbors") — Phase 7 is equal-weight averaging only within a
  category; the category itself already has its own weight
- Drop-lowest-score, extra-credit, or any other Moodle gradebook rule
  beyond plain weighted averaging
- What-if / projected-grade calculations ("what do I need on the final
  to get an 8.0?") — Phase 7 reports the current grade only
- Historical tracking of how a category's or course's current grade
  changed over time — every call recomputes from the latest canonical
  grades, there is no snapshot/history table
- Bulk/CSV import of an evaluation scheme — `PUT` takes one course's
  full scheme as JSON; there is no multi-course or spreadsheet path
- A course with no configured scheme at all still returns `null`
  current-grade fields correctly, but there's no endpoint yet that
  lists which courses are missing a scheme entirely

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
by application code — see
`deploy/sql/academic_sync_moodle_grants.example.sql` for the exact
grants (`mdl_user`/`mdl_user_info_field`/`mdl_user_info_data`,
`mdl_course`/`mdl_enrol`/`mdl_user_enrolments`, and, since Phase 4,
`mdl_grade_items`/`mdl_grade_grades` — grades are extracted by the same
credential, in the same sync process, as students/courses/enrollments).
`MOODLE_DB_URL` uses `127.0.0.1` because the sync runs on the same host
as Moodle:

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
`academic.students`/`academic.courses`/`academic.enrollments`/
`academic.grade_items`/`academic.student_grades` — no `CREATE`, no
ownership, no superuser, no `DELETE` on `academic`). The same credential
merges grades since Phase 4 — no second role, no second grants file.

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
- Deploying the Attendance sync at all (Moodle's — students/courses/
  enrollments and, since Phase 4, grades — is in production; Attendance's
  is reference material only)
- Incremental extraction for any pipeline (all are full-extraction only)
- Public exposure of the API — still localhost/internal only; Phase 6
  added authentication specifically so this can happen safely later,
  but the Nginx/Cloudflare Tunnel step itself hasn't happened yet
- A Telegram `/apikey` command or any other bot/Telegram integration
  with key provisioning — keys are distributed manually for now
- Usage/audit telemetry (`last_used_at`) and key expiration/scheduled
  rotation — a key is active until explicitly revoked or rotated
- Any HTTP endpoint for creating/listing/revoking keys — provisioning
  is CLI-only (`python -m app.auth.manage_api_keys`)
- GPA, course averages, attendance percentages, pass/fail status, or risk
  scores — the read API deliberately reports only counts a `COUNT`
  query can answer correctly; see the README's "No invented aggregates"
- Absence tracking / an expected-session-roster model
- The complete Moodle gradebook beyond weighted category averaging —
  drop-lowest, extra credit, per-item weights within a category, and
  what-if/projected-grade calculations are all still deferred; see
  "What Phase 7 does not implement yet" above for the current state of
  weighted evaluation
- Historical grade tracking (including of a calculated current grade)
  and CACEI evidence generation
- Any UI for editing an evaluation scheme, or any other admin/student
  dashboard — `PUT /admin/courses/{course_id}/evaluation-scheme`
  (Phase 7) is the only write endpoint that exists, and it has no UI
  in front of it yet
