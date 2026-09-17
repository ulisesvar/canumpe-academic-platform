"""Response models for the student read API (Phase 5).

Every field here comes from academic.* only — never a source-system id,
integration mapping, raw hash, or sync-observability field. Numeric
grade fields are plain `float`, converted explicitly from the
underlying PostgreSQL NUMERIC in app.services.student_read_service, so
a Decimal never reaches JSON serialization directly.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class CourseEnrollment(BaseModel):
    course_id: int
    name: str
    active: bool


class StudentCourseResponse(BaseModel):
    student_id: int
    courses: list[CourseEnrollment]


class AttendanceEvent(BaseModel):
    course_id: int
    session_id: int
    session_date: datetime
    present: bool = Field(
        default=True,
        description=(
            "Always true under the current canonical schema: a row here means "
            "a presence event was recorded, not that absence is tracked. A "
            "missing record must never be read as 'absent'."
        ),
    )


class StudentAttendanceResponse(BaseModel):
    student_id: int
    attendance: list[AttendanceEvent]


class GradeEntry(BaseModel):
    course_id: int
    grade_item_id: int
    name: str
    activity_type: str | None
    grade: float | None = Field(
        description="null means not graded yet; 0 means a real grade of zero. Never conflated."
    )
    max_grade: float


class StudentGradeResponse(BaseModel):
    student_id: int
    grades: list[GradeEntry]


class AttendanceSummary(BaseModel):
    sessions_recorded: int


class GradesSummary(BaseModel):
    graded_items: int
    ungraded_items: int


class StudentSummaryResponse(BaseModel):
    student_id: int
    courses_count: int
    attendance: AttendanceSummary
    grades: GradesSummary
