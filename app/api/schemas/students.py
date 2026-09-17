"""Response models for the student read API (Phase 5).

Every field here comes from academic.* only — never a source-system id,
integration mapping, raw hash, or sync-observability field. Numeric
grade fields are plain `float`, converted explicitly from the
underlying PostgreSQL NUMERIC in app.services.student_read_service, so
a Decimal never reaches JSON serialization directly.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class StudentIdentityResponse(BaseModel):
    student_id: int
    account_number: str


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
    score_100: float | None = Field(
        description=(
            "(grade / max_grade) * 100, rounded to 2 decimals; null exactly when grade is null."
        )
    )
    category_id: int | None = Field(
        default=None,
        description="null when this grade item has no evaluation category configured yet.",
    )
    category_name: str | None = None
    category_weight_percent: float | None = None
    counts_toward_current_grade: bool = Field(
        default=False,
        description=(
            "Explicit evaluation configuration — false (never inferred) when no "
            "category is configured for this item yet."
        ),
    )


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
