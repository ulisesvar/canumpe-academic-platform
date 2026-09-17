"""Transactional canonical merge: staging.attendance_* -> academic.* +
integration.*_sources.

Must only ever be called after validate_staged_batch reports zero
issues, and must run inside a single transaction the caller controls
(sync.py) so a failure partway through rolls back every academic/
integration write from this batch — never a partial merge.

Students are never created here — see _reconcile_students. Sessions and
records use the same hash-based insert/update/unchanged pattern as the
Moodle merge, and updated_at/last_seen_at/synced_at are always set
explicitly (never an ORM/Core `onupdate`).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from app.academic.models import AttendanceRecord, AttendanceSession, Student
from app.integration.attendance.models.staging import (
    StagingAttendanceRecord,
    StagingAttendanceSession,
    StagingAttendanceStudent,
)
from app.integration.attendance.staging_writer import SOURCE_SYSTEM
from app.integration.attendance.validation import resolve_moodle_course_id
from app.integration.models import AttendanceRecordSource, AttendanceSessionSource, StudentSource


@dataclass
class MergeCounters:
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_unchanged: int = 0
    rows_skipped: int = 0


@dataclass
class MergeResult:
    counters: MergeCounters = field(default_factory=MergeCounters)
    student_academic_id_by_source_id: dict[str, int] = field(default_factory=dict)
    session_academic_id_by_source_id: dict[str, int] = field(default_factory=dict)


def _reconcile_students(
    connection: Connection, now: datetime, counters: MergeCounters
) -> dict[str, int]:
    """Attendance never creates a canonical student. It only creates (or
    refreshes) a source mapping pointing at the existing academic.students
    row resolved by account_number.

    validate_staged_batch already ruled out ambiguous resolution (more
    than one academic match) — that would have failed the batch before
    reaching here. Zero matches is different: it is expected and not
    blocking. That student is skipped (rows_skipped += 1, no mapping
    created, not present in the returned map) rather than failing the
    batch — Moodle just hasn't created them yet. Because Phase 3 always
    does a full extraction, the very next sync re-attempts this same
    reconciliation from scratch, so once the student exists in
    academic.students, this mapping — and, via _merge_records, their
    entire attendance history — is created automatically with no data
    ever lost in between.
    """
    academic_id_by_source_id: dict[str, int] = {}

    staged = connection.execute(
        select(StagingAttendanceStudent).where(
            StagingAttendanceStudent.source_system == SOURCE_SYSTEM
        )
    ).all()

    for row in staged:
        existing = connection.execute(
            select(StudentSource.id, StudentSource.student_id, StudentSource.source_hash).where(
                StudentSource.source_system == SOURCE_SYSTEM,
                StudentSource.source_id == row.source_id,
            )
        ).one_or_none()

        if existing is None:
            academic_student_id = connection.execute(
                select(Student.id).where(Student.account_number == row.account_number)
            ).scalar_one_or_none()

            if academic_student_id is None:
                counters.rows_skipped += 1
                continue

            connection.execute(
                insert(StudentSource).values(
                    student_id=academic_student_id,
                    source_system=SOURCE_SYSTEM,
                    source_id=row.source_id,
                    source_hash=row.source_hash,
                    last_seen_at=now,
                    synced_at=now,
                )
            )
            counters.rows_inserted += 1
            academic_id_by_source_id[row.source_id] = academic_student_id
            continue

        academic_id_by_source_id[row.source_id] = existing.student_id

        if existing.source_hash != row.source_hash:
            connection.execute(
                update(StudentSource)
                .where(StudentSource.id == existing.id)
                .values(source_hash=row.source_hash, last_seen_at=now, synced_at=now)
            )
            counters.rows_updated += 1
        else:
            connection.execute(
                update(StudentSource)
                .where(StudentSource.id == existing.id)
                .values(last_seen_at=now, synced_at=now)
            )
            counters.rows_unchanged += 1

    return academic_id_by_source_id


def _merge_sessions(
    connection: Connection, now: datetime, counters: MergeCounters, course_id: int
) -> dict[str, int]:
    academic_id_by_source_id: dict[str, int] = {}

    staged = connection.execute(
        select(StagingAttendanceSession).where(
            StagingAttendanceSession.source_system == SOURCE_SYSTEM
        )
    ).all()

    for row in staged:
        existing = connection.execute(
            select(
                AttendanceSessionSource.id,
                AttendanceSessionSource.attendance_session_id,
                AttendanceSessionSource.source_hash,
            ).where(
                AttendanceSessionSource.source_system == SOURCE_SYSTEM,
                AttendanceSessionSource.source_id == row.source_id,
            )
        ).one_or_none()

        if existing is None:
            session_id = connection.execute(
                insert(AttendanceSession)
                .values(
                    course_id=course_id,
                    opened_at=row.opened_at,
                    closed_at=row.closed_at,
                    status=row.status,
                )
                .returning(AttendanceSession.id)
            ).scalar_one()
            connection.execute(
                insert(AttendanceSessionSource).values(
                    attendance_session_id=session_id,
                    source_system=SOURCE_SYSTEM,
                    source_id=row.source_id,
                    source_hash=row.source_hash,
                    last_seen_at=now,
                    synced_at=now,
                )
            )
            counters.rows_inserted += 1
            academic_id_by_source_id[row.source_id] = session_id
            continue

        academic_id_by_source_id[row.source_id] = existing.attendance_session_id

        if existing.source_hash != row.source_hash:
            connection.execute(
                update(AttendanceSession)
                .where(AttendanceSession.id == existing.attendance_session_id)
                .values(
                    opened_at=row.opened_at,
                    closed_at=row.closed_at,
                    status=row.status,
                    updated_at=now,
                )
            )
            connection.execute(
                update(AttendanceSessionSource)
                .where(AttendanceSessionSource.id == existing.id)
                .values(source_hash=row.source_hash, last_seen_at=now, synced_at=now)
            )
            counters.rows_updated += 1
        else:
            connection.execute(
                update(AttendanceSessionSource)
                .where(AttendanceSessionSource.id == existing.id)
                .values(last_seen_at=now, synced_at=now)
            )
            counters.rows_unchanged += 1

    return academic_id_by_source_id


def _merge_records(
    connection: Connection,
    now: datetime,
    counters: MergeCounters,
    student_academic_id_by_source_id: Mapping[str, int],
    session_academic_id_by_source_id: Mapping[str, int],
) -> None:
    """A record whose student_source_id isn't in
    student_academic_id_by_source_id belongs to a student
    _reconcile_students skipped (unresolved account_number) — skip it
    too (rows_skipped += 1), not a KeyError, not a failure. It becomes
    mergeable automatically on a later sync once that student exists in
    academic.students.
    """
    staged = connection.execute(
        select(StagingAttendanceRecord).where(
            StagingAttendanceRecord.source_system == SOURCE_SYSTEM
        )
    ).all()

    for row in staged:
        if row.student_source_id not in student_academic_id_by_source_id:
            counters.rows_skipped += 1
            continue

        student_id = student_academic_id_by_source_id[row.student_source_id]
        attendance_session_id = session_academic_id_by_source_id[row.session_source_id]

        existing = connection.execute(
            select(
                AttendanceRecordSource.id,
                AttendanceRecordSource.attendance_record_id,
                AttendanceRecordSource.source_hash,
            ).where(
                AttendanceRecordSource.source_system == SOURCE_SYSTEM,
                AttendanceRecordSource.source_id == row.source_id,
            )
        ).one_or_none()

        if existing is None:
            record_id = connection.execute(
                insert(AttendanceRecord)
                .values(
                    attendance_session_id=attendance_session_id,
                    student_id=student_id,
                    recorded_at=row.recorded_at,
                )
                .returning(AttendanceRecord.id)
            ).scalar_one()
            connection.execute(
                insert(AttendanceRecordSource).values(
                    attendance_record_id=record_id,
                    source_system=SOURCE_SYSTEM,
                    source_id=row.source_id,
                    source_hash=row.source_hash,
                    last_seen_at=now,
                    synced_at=now,
                )
            )
            counters.rows_inserted += 1
            continue

        if existing.source_hash != row.source_hash:
            connection.execute(
                update(AttendanceRecord)
                .where(AttendanceRecord.id == existing.attendance_record_id)
                .values(recorded_at=row.recorded_at, updated_at=now)
            )
            connection.execute(
                update(AttendanceRecordSource)
                .where(AttendanceRecordSource.id == existing.id)
                .values(source_hash=row.source_hash, last_seen_at=now, synced_at=now)
            )
            counters.rows_updated += 1
        else:
            connection.execute(
                update(AttendanceRecordSource)
                .where(AttendanceRecordSource.id == existing.id)
                .values(last_seen_at=now, synced_at=now)
            )
            counters.rows_unchanged += 1


def merge_batch(connection: Connection, now: datetime, moodle_course_id: int) -> MergeResult:
    result = MergeResult()

    course_id = resolve_moodle_course_id(connection, moodle_course_id)
    if course_id is None:
        # validate_staged_batch must have already caught this — reaching
        # here means it was skipped, which is a programming error.
        raise RuntimeError(
            f"no course mapping for moodle course_id={moodle_course_id!r}; "
            "merge_batch must only run after successful validation"
        )

    result.student_academic_id_by_source_id = _reconcile_students(connection, now, result.counters)
    result.session_academic_id_by_source_id = _merge_sessions(
        connection, now, result.counters, course_id
    )
    _merge_records(
        connection,
        now,
        result.counters,
        result.student_academic_id_by_source_id,
        result.session_academic_id_by_source_id,
    )

    return result
