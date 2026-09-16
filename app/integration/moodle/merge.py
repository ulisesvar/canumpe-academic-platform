"""Transactional canonical merge: staging.* -> academic.* + integration.*_sources.

Must only ever be called after validate_staged_batch reports zero issues,
and must run inside a single transaction the caller controls (sync.py) so
that a failure partway through rolls back every academic/integration
write from this batch — never a partial merge.

Change detection is by source_hash: a mapping's stored hash is compared
to the freshly staged hash to decide insert vs. update vs. unchanged.
Per the Phase 1 timestamp invariant, updated_at/last_seen_at/synced_at
are always set explicitly here (never left to an ORM/Core `onupdate`) —
including on the "unchanged" path, where last_seen_at/synced_at still
advance because the source was observed again even though nothing about
it changed.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from app.academic.models import Course, Enrollment, Student
from app.integration.models import CourseSource, EnrollmentSource, StudentSource
from app.integration.moodle.models.staging import (
    StagingCourse,
    StagingEnrollment,
    StagingStudent,
)
from app.integration.moodle.staging_writer import SOURCE_SYSTEM


@dataclass
class MergeCounters:
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_unchanged: int = 0


@dataclass
class MergeResult:
    counters: MergeCounters = field(default_factory=MergeCounters)
    student_academic_id_by_source_id: dict[str, int] = field(default_factory=dict)
    course_academic_id_by_source_id: dict[str, int] = field(default_factory=dict)


def _merge_students(
    connection: Connection, now: datetime, counters: MergeCounters
) -> dict[str, int]:
    academic_id_by_source_id: dict[str, int] = {}

    staged = connection.execute(
        select(StagingStudent).where(StagingStudent.source_system == SOURCE_SYSTEM)
    ).all()

    for row in staged:
        existing = connection.execute(
            select(StudentSource.id, StudentSource.student_id, StudentSource.source_hash).where(
                StudentSource.source_system == SOURCE_SYSTEM,
                StudentSource.source_id == row.source_id,
            )
        ).one_or_none()

        if existing is None:
            student_id = connection.execute(
                insert(Student).values(
                    account_number=row.account_number,
                    first_name=row.first_name,
                    last_name=row.last_name,
                    email=row.email,
                ).returning(Student.id)
            ).scalar_one()
            connection.execute(
                insert(StudentSource).values(
                    student_id=student_id,
                    source_system=SOURCE_SYSTEM,
                    source_id=row.source_id,
                    source_updated_at=row.source_updated_at,
                    source_hash=row.source_hash,
                    last_seen_at=now,
                    synced_at=now,
                )
            )
            counters.rows_inserted += 1
            academic_id_by_source_id[row.source_id] = student_id
            continue

        academic_id_by_source_id[row.source_id] = existing.student_id

        if existing.source_hash != row.source_hash:
            connection.execute(
                update(Student)
                .where(Student.id == existing.student_id)
                .values(
                    account_number=row.account_number,
                    first_name=row.first_name,
                    last_name=row.last_name,
                    email=row.email,
                    updated_at=now,
                )
            )
            connection.execute(
                update(StudentSource)
                .where(StudentSource.id == existing.id)
                .values(
                    source_updated_at=row.source_updated_at,
                    source_hash=row.source_hash,
                    last_seen_at=now,
                    synced_at=now,
                )
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


def _merge_courses(
    connection: Connection, now: datetime, counters: MergeCounters
) -> dict[str, int]:
    academic_id_by_source_id: dict[str, int] = {}

    staged = connection.execute(
        select(StagingCourse).where(StagingCourse.source_system == SOURCE_SYSTEM)
    ).all()

    for row in staged:
        existing = connection.execute(
            select(CourseSource.id, CourseSource.course_id, CourseSource.source_hash).where(
                CourseSource.source_system == SOURCE_SYSTEM,
                CourseSource.source_id == row.source_id,
            )
        ).one_or_none()

        if existing is None:
            course_id = connection.execute(
                insert(Course)
                .values(code=row.code, name=row.name, active=row.active)
                .returning(Course.id)
            ).scalar_one()
            connection.execute(
                insert(CourseSource).values(
                    course_id=course_id,
                    source_system=SOURCE_SYSTEM,
                    source_id=row.source_id,
                    source_updated_at=row.source_updated_at,
                    source_hash=row.source_hash,
                    last_seen_at=now,
                    synced_at=now,
                )
            )
            counters.rows_inserted += 1
            academic_id_by_source_id[row.source_id] = course_id
            continue

        academic_id_by_source_id[row.source_id] = existing.course_id

        if existing.source_hash != row.source_hash:
            connection.execute(
                update(Course)
                .where(Course.id == existing.course_id)
                .values(code=row.code, name=row.name, active=row.active, updated_at=now)
            )
            connection.execute(
                update(CourseSource)
                .where(CourseSource.id == existing.id)
                .values(
                    source_updated_at=row.source_updated_at,
                    source_hash=row.source_hash,
                    last_seen_at=now,
                    synced_at=now,
                )
            )
            counters.rows_updated += 1
        else:
            connection.execute(
                update(CourseSource)
                .where(CourseSource.id == existing.id)
                .values(last_seen_at=now, synced_at=now)
            )
            counters.rows_unchanged += 1

    return academic_id_by_source_id


def _merge_enrollments(
    connection: Connection,
    now: datetime,
    counters: MergeCounters,
    student_academic_id_by_source_id: Mapping[str, int],
    course_academic_id_by_source_id: Mapping[str, int],
) -> None:
    staged = connection.execute(
        select(StagingEnrollment).where(StagingEnrollment.source_system == SOURCE_SYSTEM)
    ).all()

    for row in staged:
        student_id = student_academic_id_by_source_id[row.student_source_id]
        course_id = course_academic_id_by_source_id[row.course_source_id]

        existing = connection.execute(
            select(
                EnrollmentSource.id, EnrollmentSource.enrollment_id, EnrollmentSource.source_hash
            ).where(
                EnrollmentSource.source_system == SOURCE_SYSTEM,
                EnrollmentSource.source_id == row.source_id,
            )
        ).one_or_none()

        if existing is None:
            # A student can be enrolled in the same course through more than
            # one Moodle enrolment method, producing distinct source rows
            # for the same (student, course) pair. academic.enrollments has
            # a UNIQUE(student_id, course_id): reuse the existing canonical
            # row instead of trying to insert a duplicate.
            reused_enrollment_id = connection.execute(
                select(Enrollment.id).where(
                    Enrollment.student_id == student_id, Enrollment.course_id == course_id
                )
            ).scalar_one_or_none()

            if reused_enrollment_id is None:
                enrollment_id = connection.execute(
                    insert(Enrollment)
                    .values(student_id=student_id, course_id=course_id, status=row.status)
                    .returning(Enrollment.id)
                ).scalar_one()
            else:
                enrollment_id = reused_enrollment_id

            connection.execute(
                insert(EnrollmentSource).values(
                    enrollment_id=enrollment_id,
                    source_system=SOURCE_SYSTEM,
                    source_id=row.source_id,
                    source_updated_at=row.source_updated_at,
                    source_hash=row.source_hash,
                    last_seen_at=now,
                    synced_at=now,
                )
            )
            counters.rows_inserted += 1
            continue

        if existing.source_hash != row.source_hash:
            connection.execute(
                update(Enrollment)
                .where(Enrollment.id == existing.enrollment_id)
                .values(status=row.status, updated_at=now)
            )
            connection.execute(
                update(EnrollmentSource)
                .where(EnrollmentSource.id == existing.id)
                .values(
                    source_updated_at=row.source_updated_at,
                    source_hash=row.source_hash,
                    last_seen_at=now,
                    synced_at=now,
                )
            )
            counters.rows_updated += 1
        else:
            connection.execute(
                update(EnrollmentSource)
                .where(EnrollmentSource.id == existing.id)
                .values(last_seen_at=now, synced_at=now)
            )
            counters.rows_unchanged += 1


def merge_batch(connection: Connection, now: datetime) -> MergeResult:
    result = MergeResult()

    result.student_academic_id_by_source_id = _merge_students(connection, now, result.counters)
    result.course_academic_id_by_source_id = _merge_courses(connection, now, result.counters)
    _merge_enrollments(
        connection,
        now,
        result.counters,
        result.student_academic_id_by_source_id,
        result.course_academic_id_by_source_id,
    )

    return result
