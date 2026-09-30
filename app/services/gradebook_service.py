"""Course roster and bulk gradebook (Phase 8.4).

The gradebook loads the whole course with a constant number of queries
(app.repositories.gradebook_repository) and then evaluates every
student IN MEMORY with the very same pure calculation
get_student_evaluation uses
(app.services.evaluation_service.calculate_student_evaluation), so its
numbers always match GET /students/{id}/evaluation. It never calls
get_student_evaluation, and introduces no formula of its own:
attendance comes from attendance_score_service.compute_attendance_score,
participation from participation_service.summarize_participation, and
the 33/67 blend from evaluation_service.blend_attendance_participation.

Attendance/participation detail: an internal contribution is a
component's share of the 0-100 category score (score * internal weight),
shown whenever that component exists; the category score itself stays
None unless both components do. There is no final grade — only the
current grade exists.

Eligibility limitation (accepted for now, see attendance_score_service):
every CLOSED session counts for every student.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.academic.models.grade_category import CALCULATION_ATTENDANCE_PARTICIPATION
from app.api.schemas.evaluation import CategoryEvaluation
from app.api.schemas.gradebook import (
    CourseRosterResponse,
    CourseRosterStudent,
    GradebookAttendance,
    GradebookAttendanceParticipationDetail,
    GradebookCategoryResult,
    GradebookCategoryScheme,
    GradebookColumn,
    GradebookCourse,
    GradebookGradeCell,
    GradebookParticipation,
    GradebookResponse,
    GradebookStudent,
)
from app.repositories import evaluation_repository as evaluation_repo
from app.repositories import gradebook_repository as repo
from app.services.attendance_score_service import compute_attendance_score
from app.services.errors import CourseNotFoundError
from app.services.evaluation_service import (
    ATTENDANCE_WEIGHT,
    PARTICIPATION_WEIGHT,
    blend_attendance_participation,
    calculate_student_evaluation,
)
from app.services.grade_normalization import normalize_score, round2, round2_or_none
from app.services.participation_service import summarize_participation

_HUNDRED = Decimal(100)


def _full_name(first_name: str, last_name: str) -> str:
    return f"{first_name} {last_name}"


def _ensure_course(db: Session, course_id: int) -> Mapping[Any, Any]:
    course = evaluation_repo.get_course(db, course_id)
    if course is None:
        raise CourseNotFoundError(course_id)
    return course


def get_course_roster(db: Session, course_id: int) -> CourseRosterResponse:
    _ensure_course(db, course_id)
    return CourseRosterResponse(
        course_id=course_id,
        students=[
            CourseRosterStudent(
                student_id=row["student_id"],
                account_number=row["account_number"],
                first_name=row["first_name"],
                last_name=row["last_name"],
                full_name=_full_name(row["first_name"], row["last_name"]),
            )
            for row in repo.list_roster(db, course_id)
        ],
    )


def get_course_gradebook(db: Session, course_id: int) -> GradebookResponse:
    course = _ensure_course(db, course_id)

    # -- bulk loads: a constant number of queries, whatever the class size --
    roster = repo.list_roster(db, course_id)
    category_rows = evaluation_repo.list_categories_for_course(db, course_id)
    item_rows = repo.list_course_grade_items(db, course_id)
    grade_by_student_item: dict[tuple[int, int], Decimal | None] = {
        (row["student_id"], row["grade_item_id"]): row["grade"]
        for row in repo.list_course_grades(db, course_id)
    }
    closed_sessions = repo.count_closed_sessions(db, course_id)
    present_by_student = repo.present_closed_sessions_by_student(db, course_id)
    participation_by_student = repo.participation_values_by_student(db, course_id)

    category_by_id = {row["id"]: row for row in category_rows}
    category_position = {row["id"]: index for index, row in enumerate(category_rows)}
    attendance_participation_category_id = next(
        (
            row["id"]
            for row in category_rows
            if row["calculation_type"] == CALCULATION_ATTENDANCE_PARTICIPATION
        ),
        None,
    )

    # -- columns: assigned items by (category sort order, item id), then
    #    unassigned items by item id. item_rows is already ordered by id. --
    assigned_items = sorted(
        (row for row in item_rows if row["category_id"] is not None),
        key=lambda row: (category_position[row["category_id"]], row["grade_item_id"]),
    )
    unassigned_items = [row for row in item_rows if row["category_id"] is None]
    column_rows = [*assigned_items, *unassigned_items]

    columns = [
        GradebookColumn(
            activity_id=row["grade_item_id"],
            name=row["name"],
            activity_type=row["activity_type"],
            max_grade=float(row["max_grade"]),
            category_id=row["category_id"],
            category_name=(
                category_by_id[row["category_id"]]["name"]
                if row["category_id"] is not None
                else None
            ),
            counts_toward_current_grade=row["counts_toward_current_grade"],
        )
        for row in column_rows
    ]

    students: list[GradebookStudent] = []
    for student in roster:
        student_id = student["student_id"]

        attendance = compute_attendance_score(
            closed_sessions, present_by_student.get(student_id, 0)
        )
        participation = summarize_participation(participation_by_student.get(student_id, []))

        evaluation = calculate_student_evaluation(
            student_id,
            course_id,
            category_rows,
            [
                {**row, "grade": grade_by_student_item.get((student_id, row["grade_item_id"]))}
                for row in item_rows
                if row["category_id"] is not None
            ],
            blend_attendance_participation(attendance.score_100, participation.score_100),
        )
        category_results_by_id = {c.category_id: c for c in evaluation.categories}

        grades: list[GradebookGradeCell] = []
        for column, row in zip(columns, column_rows, strict=True):
            grade = grade_by_student_item.get((student_id, row["grade_item_id"]))
            grades.append(
                GradebookGradeCell(
                    **column.model_dump(),
                    grade=float(grade) if grade is not None else None,
                    score_100=round2_or_none(normalize_score(grade, row["max_grade"])),
                )
            )

        students.append(
            GradebookStudent(
                student_id=student_id,
                account_number=student["account_number"],
                first_name=student["first_name"],
                last_name=student["last_name"],
                full_name=_full_name(student["first_name"], student["last_name"]),
                grades=grades,
                attendance=GradebookAttendance(
                    closed_sessions=attendance.closed_sessions,
                    present_sessions=attendance.present_sessions,
                    absent_sessions=attendance.absent_sessions,
                    score_100=round2_or_none(attendance.score_100),
                ),
                participation=GradebookParticipation(
                    participation_count=participation.count,
                    participation_average=round2_or_none(participation.average),
                    participation_score_100=round2_or_none(participation.score_100),
                ),
                attendance_participation=(
                    _attendance_participation_detail(
                        attendance.score_100,
                        participation.score_100,
                        category_results_by_id[attendance_participation_category_id],
                    )
                    if attendance_participation_category_id is not None
                    else None
                ),
                categories=[
                    GradebookCategoryResult(
                        category_id=result.category_id,
                        name=result.name,
                        calculation_type=category_by_id[result.category_id]["calculation_type"],
                        weight_percent=result.weight_percent,
                        category_score_100=result.category_score_100,
                        contribution_points=result.contribution_points,
                    )
                    for result in evaluation.categories
                ],
                weighted_points_earned=evaluation.weighted_points_earned,
                evaluated_weight_percent=evaluation.evaluated_weight_percent,
                current_score_100=evaluation.current_score_100,
                current_grade_10=evaluation.current_grade_10,
            )
        )

    return GradebookResponse(
        course=GradebookCourse(course_id=course_id, name=course["name"]),
        scheme=[
            GradebookCategoryScheme(
                category_id=row["id"],
                name=row["name"],
                calculation_type=row["calculation_type"],
                weight_percent=round2(row["weight_percent"]),
                sort_order=row["sort_order"],
            )
            for row in category_rows
        ],
        columns=columns,
        students=students,
    )


def _attendance_participation_detail(
    attendance_score_100: Decimal | None,
    participation_score_100: Decimal | None,
    category: CategoryEvaluation,
) -> GradebookAttendanceParticipationDetail:
    """category_* come from the shared evaluation result, so they can
    never disagree with the category results; the internal contributions
    use the same ATTENDANCE_WEIGHT / PARTICIPATION_WEIGHT constants the
    blend uses.
    """
    return GradebookAttendanceParticipationDetail(
        attendance_score_100=round2_or_none(attendance_score_100),
        attendance_weight_percent=round2(ATTENDANCE_WEIGHT * _HUNDRED),
        attendance_contribution_points=round2_or_none(
            attendance_score_100 * ATTENDANCE_WEIGHT if attendance_score_100 is not None else None
        ),
        participation_score_100=round2_or_none(participation_score_100),
        participation_weight_percent=round2(PARTICIPATION_WEIGHT * _HUNDRED),
        participation_contribution_points=round2_or_none(
            participation_score_100 * PARTICIPATION_WEIGHT
            if participation_score_100 is not None
            else None
        ),
        category_score_100=category.category_score_100,
        category_weight_percent=category.weight_percent,
        category_contribution_points=category.contribution_points,
    )
