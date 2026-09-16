"""Read-only extraction from the Moodle PostgreSQL database.

Queries only. No writes, no schema changes, no assumption that Moodle
grants anything beyond SELECT — see the README's security boundary
section. All entity queries run inside one REPEATABLE READ, READ ONLY
transaction so that students/courses/enrollments extracted for a batch
represent one coherent source snapshot.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

from app.integration.moodle.errors import MoodleSourceIntegrityError

#: Moodle custom profile field that actually holds the account number.
#: Never assume a fixed fieldid (e.g. 1) — it is an autoincrement id that
#: differs per Moodle installation and can change if fields are recreated.
ACCOUNT_NUMBER_FIELD_SHORTNAME = "cuenta"


def _epoch_to_datetime(value: int | None) -> datetime | None:
    """Moodle stores modification times as unix epoch seconds; 0/None means unset."""
    if not value:
        return None
    return datetime.fromtimestamp(value, tz=UTC)


@dataclass(frozen=True)
class ExtractedStudent:
    source_id: str
    account_number: str
    first_name: str
    last_name: str
    email: str | None
    source_updated_at: datetime | None


@dataclass(frozen=True)
class ExtractedCourse:
    source_id: str
    code: str | None
    name: str
    visible: bool
    source_updated_at: datetime | None


@dataclass(frozen=True)
class ExtractedEnrollment:
    source_id: str
    student_source_id: str
    course_source_id: str
    status: str
    source_updated_at: datetime | None


@dataclass(frozen=True)
class MoodleExtractionResult:
    snapshot_time: datetime
    students: Sequence[ExtractedStudent]
    courses: Sequence[ExtractedCourse]
    enrollments: Sequence[ExtractedEnrollment]


def _fetch_students(connection: Connection, course_id: int) -> list[ExtractedStudent]:
    rows = connection.execute(
        text("""
            SELECT DISTINCT
                u.id AS source_id,
                uid.data AS account_number,
                u.firstname AS first_name,
                u.lastname AS last_name,
                u.email AS email,
                u.timemodified AS timemodified
            FROM mdl_user u
            JOIN mdl_user_enrolments ue ON ue.userid = u.id
            JOIN mdl_enrol e ON e.id = ue.enrolid
            JOIN mdl_user_info_data uid ON uid.userid = u.id
            JOIN mdl_user_info_field uif
                ON uif.id = uid.fieldid AND uif.shortname = :field_shortname
            WHERE u.deleted = 0
              AND ue.status = 0
              AND e.status = 0
              AND e.courseid = :course_id
        """),
        {"field_shortname": ACCOUNT_NUMBER_FIELD_SHORTNAME, "course_id": course_id},
    ).all()

    by_account: dict[str, set[str]] = {}
    for row in rows:
        by_account.setdefault(row.account_number, set()).add(str(row.source_id))
    duplicates = {account: ids for account, ids in by_account.items() if len(ids) > 1}
    if duplicates:
        details = "; ".join(
            f"account_number={account!r} -> moodle user ids {sorted(ids)}"
            for account, ids in sorted(duplicates.items())
        )
        raise MoodleSourceIntegrityError(
            f"duplicate account_number maps to multiple non-deleted Moodle users: {details}"
        )

    return [
        ExtractedStudent(
            source_id=str(row.source_id),
            account_number=row.account_number,
            first_name=row.first_name,
            last_name=row.last_name,
            email=row.email,
            source_updated_at=_epoch_to_datetime(row.timemodified),
        )
        for row in rows
    ]


def _fetch_courses(connection: Connection, course_id: int) -> list[ExtractedCourse]:
    rows = connection.execute(
        text("""
            SELECT id AS source_id, shortname AS code, fullname AS name, visible, timemodified
            FROM mdl_course
            WHERE id = :course_id
        """),
        {"course_id": course_id},
    ).all()
    return [
        ExtractedCourse(
            source_id=str(row.source_id),
            code=row.code,
            name=row.name,
            visible=bool(row.visible),
            source_updated_at=_epoch_to_datetime(row.timemodified),
        )
        for row in rows
    ]


def _fetch_enrollments(connection: Connection, course_id: int) -> list[ExtractedEnrollment]:
    rows = connection.execute(
        text("""
            SELECT
                ue.id AS source_id,
                ue.userid AS student_source_id,
                e.courseid AS course_source_id,
                ue.timemodified AS timemodified
            FROM mdl_user_enrolments ue
            JOIN mdl_enrol e ON e.id = ue.enrolid
            JOIN mdl_user u ON u.id = ue.userid
            WHERE e.courseid = :course_id
              AND e.status = 0
              AND ue.status = 0
              AND u.deleted = 0
        """),
        {"course_id": course_id},
    ).all()
    return [
        ExtractedEnrollment(
            source_id=str(row.source_id),
            student_source_id=str(row.student_source_id),
            course_source_id=str(row.course_source_id),
            status="active",
            source_updated_at=_epoch_to_datetime(row.timemodified),
        )
        for row in rows
    ]


def extract_moodle_batch(moodle_engine: Engine, course_id: int) -> MoodleExtractionResult:
    """Extract students/courses/enrollments for one course from Moodle.

    Runs entirely inside a single REPEATABLE READ, READ ONLY transaction:
    the three queries below therefore see one consistent snapshot of
    Moodle, not three independently-timed reads. The transaction is
    always committed (read-only, so this just releases the snapshot) or
    rolled back on error, and the connection is always closed.
    """
    with moodle_engine.connect() as connection, connection.begin():
        connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        snapshot_time = connection.execute(text("SELECT now()")).scalar_one()

        students = _fetch_students(connection, course_id)
        courses = _fetch_courses(connection, course_id)
        enrollments = _fetch_enrollments(connection, course_id)

    return MoodleExtractionResult(
        snapshot_time=snapshot_time, students=students, courses=courses, enrollments=enrollments
    )
