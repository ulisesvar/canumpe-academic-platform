"""Transactional canonical merge: staging.grade_items/student_grades ->
academic.grade_items/student_grades + integration.*_sources.

Must only ever be called after validate_staged_grades_batch reports zero
issues, and must run inside a single transaction the caller controls
(grades_sync.py) so a failure partway through rolls back every academic/
integration write from this batch — never a partial merge.

Grade items use the same hash-based insert/update/unchanged pattern as
the rest of the platform. Student grades never create a canonical
student or a new entry in integration.student_sources — they only ever
look up the *existing* mapping created by the Moodle students sync
(source_system='moodle'); see _resolve_student and the README's grade
student-resolution section. grade is copied through exactly as staged —
NULL stays NULL, 0 stays a real zero — never coerced.
"""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Connection

from app.academic.models import GradeItem, StudentGrade
from app.integration.issues import open_issue, resolve_issue
from app.integration.models import GradeItemSource, StudentGradeSource, StudentSource
from app.integration.moodle.grades_staging_writer import SOURCE_SYSTEM
from app.integration.moodle.grades_validation import resolve_moodle_course_id
from app.integration.moodle.models.grades_staging import StagingGradeItem, StagingStudentGrade

#: integration.sync_issues identity for a Moodle student grade whose
#: student_source_id doesn't resolve to any academic student yet.
UNRESOLVED_GRADE_STUDENT_ISSUE_TYPE = "UNRESOLVED_GRADE_STUDENT"
STUDENT_GRADE_SOURCE_ENTITY = "student_grade"


@dataclass
class MergeCounters:
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_unchanged: int = 0
    rows_skipped: int = 0


@dataclass
class MergeResult:
    counters: MergeCounters = field(default_factory=MergeCounters)
    grade_item_academic_id_by_source_id: dict[str, int] = field(default_factory=dict)


def _merge_grade_items(
    connection: Connection, now: datetime, counters: MergeCounters, course_id: int
) -> dict[str, int]:
    academic_id_by_source_id: dict[str, int] = {}

    staged = connection.execute(
        select(StagingGradeItem).where(StagingGradeItem.source_system == SOURCE_SYSTEM)
    ).all()

    for row in staged:
        existing = connection.execute(
            select(
                GradeItemSource.id, GradeItemSource.grade_item_id, GradeItemSource.source_hash
            ).where(
                GradeItemSource.source_system == SOURCE_SYSTEM,
                GradeItemSource.source_id == row.source_id,
            )
        ).one_or_none()

        if existing is None:
            grade_item_id = connection.execute(
                insert(GradeItem)
                .values(
                    course_id=course_id,
                    name=row.name,
                    max_grade=row.max_grade,
                    activity_type=row.itemmodule,
                )
                .returning(GradeItem.id)
            ).scalar_one()
            connection.execute(
                insert(GradeItemSource).values(
                    grade_item_id=grade_item_id,
                    source_system=SOURCE_SYSTEM,
                    source_id=row.source_id,
                    source_hash=row.source_hash,
                    last_seen_at=now,
                    synced_at=now,
                )
            )
            counters.rows_inserted += 1
            academic_id_by_source_id[row.source_id] = grade_item_id
            continue

        academic_id_by_source_id[row.source_id] = existing.grade_item_id

        if existing.source_hash != row.source_hash:
            connection.execute(
                update(GradeItem)
                .where(GradeItem.id == existing.grade_item_id)
                .values(
                    name=row.name,
                    max_grade=row.max_grade,
                    activity_type=row.itemmodule,
                    updated_at=now,
                )
            )
            connection.execute(
                update(GradeItemSource)
                .where(GradeItemSource.id == existing.id)
                .values(source_hash=row.source_hash, last_seen_at=now, synced_at=now)
            )
            counters.rows_updated += 1
        else:
            connection.execute(
                update(GradeItemSource)
                .where(GradeItemSource.id == existing.id)
                .values(last_seen_at=now, synced_at=now)
            )
            counters.rows_unchanged += 1

    return academic_id_by_source_id


def _resolve_student(connection: Connection, moodle_user_id: str) -> int | None:
    """Looks up the canonical student through the *existing* Moodle
    student mapping — never creates one. See the module docstring.
    """
    return connection.execute(
        select(StudentSource.student_id).where(
            StudentSource.source_system == SOURCE_SYSTEM,
            StudentSource.source_id == moodle_user_id,
        )
    ).scalar_one_or_none()


def _merge_student_grades(
    connection: Connection,
    now: datetime,
    counters: MergeCounters,
    grade_item_academic_id_by_source_id: dict[str, int],
) -> None:
    staged = connection.execute(
        select(StagingStudentGrade).where(StagingStudentGrade.source_system == SOURCE_SYSTEM)
    ).all()

    for row in staged:
        student_id = _resolve_student(connection, row.student_source_id)

        if student_id is None:
            counters.rows_skipped += 1
            open_issue(
                connection,
                source_system=SOURCE_SYSTEM,
                issue_type=UNRESOLVED_GRADE_STUDENT_ISSUE_TYPE,
                source_entity=STUDENT_GRADE_SOURCE_ENTITY,
                source_id=row.source_id,
                reference_value=row.student_source_id,
                message=(
                    f"moodle student_source_id {row.student_source_id!r} "
                    f"(grade source_id={row.source_id!r}) does not resolve to any "
                    "academic student yet"
                ),
                now=now,
            )
            continue

        grade_item_id = grade_item_academic_id_by_source_id[row.grade_item_source_id]

        existing = connection.execute(
            select(
                StudentGradeSource.id,
                StudentGradeSource.student_grade_id,
                StudentGradeSource.source_hash,
            ).where(
                StudentGradeSource.source_system == SOURCE_SYSTEM,
                StudentGradeSource.source_id == row.source_id,
            )
        ).one_or_none()

        if existing is None:
            student_grade_id = connection.execute(
                insert(StudentGrade)
                .values(grade_item_id=grade_item_id, student_id=student_id, grade=row.grade)
                .returning(StudentGrade.id)
            ).scalar_one()
            connection.execute(
                insert(StudentGradeSource).values(
                    student_grade_id=student_grade_id,
                    source_system=SOURCE_SYSTEM,
                    source_id=row.source_id,
                    source_hash=row.source_hash,
                    last_seen_at=now,
                    synced_at=now,
                )
            )
            resolve_issue(
                connection,
                source_system=SOURCE_SYSTEM,
                issue_type=UNRESOLVED_GRADE_STUDENT_ISSUE_TYPE,
                source_entity=STUDENT_GRADE_SOURCE_ENTITY,
                source_id=row.source_id,
                now=now,
            )
            counters.rows_inserted += 1
            continue

        if existing.source_hash != row.source_hash:
            connection.execute(
                update(StudentGrade)
                .where(StudentGrade.id == existing.student_grade_id)
                .values(grade=row.grade, updated_at=now)
            )
            connection.execute(
                update(StudentGradeSource)
                .where(StudentGradeSource.id == existing.id)
                .values(source_hash=row.source_hash, last_seen_at=now, synced_at=now)
            )
            counters.rows_updated += 1
        else:
            connection.execute(
                update(StudentGradeSource)
                .where(StudentGradeSource.id == existing.id)
                .values(last_seen_at=now, synced_at=now)
            )
            counters.rows_unchanged += 1


def merge_grades_batch(
    connection: Connection, now: datetime, moodle_course_id: int
) -> MergeResult:
    result = MergeResult()

    course_id = resolve_moodle_course_id(connection, moodle_course_id)
    if course_id is None:
        # validate_staged_grades_batch must have already caught this —
        # reaching here means it was skipped, which is a programming error.
        raise RuntimeError(
            f"no course mapping for moodle course_id={moodle_course_id!r}; "
            "merge_grades_batch must only run after successful validation"
        )

    result.grade_item_academic_id_by_source_id = _merge_grade_items(
        connection, now, result.counters, course_id
    )
    _merge_student_grades(
        connection, now, result.counters, result.grade_item_academic_id_by_source_id
    )

    return result
