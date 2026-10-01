"""Admin-only course roster and gradebook models (Phase 8.4) —
GET /admin/courses/{course_id}/students and
GET /admin/courses/{course_id}/gradebook.

Every number is presentation-rounded `float`, converted from
full-precision Decimal in app.services.gradebook_service — never
rounded and then fed back into arithmetic. `None` always means "not
currently calculable" (a NULL grade, no CLOSED attendance sessions, zero
evaluated weight) — never coerced to 0. (Participation without observations
is not one of them: it is 0.) There is deliberately no final grade: only the current grade
(current_score_100 / current_grade_10) exists in this system.
"""

from pydantic import BaseModel, Field


class CourseRosterStudent(BaseModel):
    student_id: int
    account_number: str
    first_name: str
    last_name: str
    full_name: str = Field(description='Derived: first_name + " " + last_name.')


class CourseRosterResponse(BaseModel):
    course_id: int
    students: list[CourseRosterStudent]


class GradebookCourse(BaseModel):
    course_id: int
    name: str


class GradebookCategoryScheme(BaseModel):
    category_id: int
    name: str
    calculation_type: str
    weight_percent: float
    sort_order: int


class GradebookColumn(BaseModel):
    """One course grade item (an activity column). category_* and
    counts_toward_current_grade are null for an item not assigned to
    any evaluation category — it isn't part of the evaluation.
    """

    activity_id: int
    name: str
    activity_type: str | None
    max_grade: float
    category_id: int | None
    category_name: str | None
    counts_toward_current_grade: bool | None


class GradebookGradeCell(GradebookColumn):
    grade: float | None = Field(
        description="Raw grade; null when not graded, a real 0.0 when graded as zero."
    )
    score_100: float | None = Field(
        description="(grade / max_grade) * 100; null exactly when grade is null."
    )


class GradebookAttendance(BaseModel):
    closed_sessions: int
    present_sessions: int
    absent_sessions: int
    score_100: float | None = Field(
        description="present / closed * 100; null when the course has no CLOSED sessions."
    )


class GradebookParticipation(BaseModel):
    participation_count: int
    participation_average: float | None
    participation_score_100: float | None


class GradebookAttendanceParticipationDetail(BaseModel):
    """How the attendance/participation category score was built. Only
    present when the course has an ATTENDANCE_PARTICIPATION category.
    *_contribution_points are the component's share of the 0-100
    category score (score * internal weight / 100), shown whenever that
    component exists; category_score_100 is null unless BOTH do.
    """

    attendance_score_100: float | None
    attendance_weight_percent: float
    attendance_contribution_points: float | None
    participation_score_100: float | None
    participation_weight_percent: float
    participation_contribution_points: float | None
    category_score_100: float | None
    category_weight_percent: float
    category_contribution_points: float | None


class GradebookCategoryResult(BaseModel):
    category_id: int
    name: str
    calculation_type: str
    weight_percent: float
    category_score_100: float | None
    contribution_points: float | None


class GradebookStudent(BaseModel):
    student_id: int
    account_number: str
    first_name: str
    last_name: str
    full_name: str
    grades: list[GradebookGradeCell] = Field(
        description="One cell per course grade item, in the same order as `columns`."
    )
    attendance: GradebookAttendance
    participation: GradebookParticipation
    attendance_participation: GradebookAttendanceParticipationDetail | None
    categories: list[GradebookCategoryResult]
    weighted_points_earned: float
    evaluated_weight_percent: float
    current_score_100: float | None
    current_grade_10: float | None


class GradebookResponse(BaseModel):
    course: GradebookCourse
    scheme: list[GradebookCategoryScheme]
    columns: list[GradebookColumn] = Field(
        description=(
            "Every course grade item. Assigned items come first, ordered by their category's "
            "sort_order then GradeItem.id; unassigned items follow, by GradeItem.id. GradeItem.id "
            "reflects ingestion order, not necessarily Moodle's display order."
        )
    )
    students: list[GradebookStudent]
