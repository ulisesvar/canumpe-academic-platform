"""Admin-only read-only student endpoints.

Reads canonical academic.* tables only, via
app.services.student_read_service — never a direct query here, never a
write, never a connection to Moodle/Attendance or their raw_*/staging
landing tables. Since Phase 6, every route here requires an ADMIN API
key (app.auth.dependencies.require_admin, applied once at the router
level below) — a STUDENT key gets 403. Students use /me/* instead
(app.api.routes.me), where student_id comes from their own credential,
never from a path parameter.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas.evaluation import StudentEvaluationResponse
from app.api.schemas.students import (
    StudentAttendanceResponse,
    StudentCourseResponse,
    StudentGradeResponse,
    StudentSummaryResponse,
)
from app.auth.dependencies import require_admin
from app.db.session import get_db
from app.services import evaluation_service
from app.services import student_read_service as service

router = APIRouter(prefix="/students", tags=["students"], dependencies=[Depends(require_admin)])


@router.get(
    "/{student_id}/courses",
    response_model=StudentCourseResponse,
    summary="List a student's canonical course enrollments",
)
def get_student_courses(
    student_id: int, db: Session = Depends(get_db)
) -> StudentCourseResponse:
    return service.get_student_courses(db, student_id)


@router.get(
    "/{student_id}/attendance",
    response_model=StudentAttendanceResponse,
    summary="List a student's recorded attendance events",
    description=(
        "Each entry is a recorded presence event only. The canonical schema "
        "does not track absence, so `present` is always true and no "
        "attendance percentage can be derived from this endpoint."
    ),
)
def get_student_attendance(
    student_id: int, db: Session = Depends(get_db)
) -> StudentAttendanceResponse:
    return service.get_student_attendance(db, student_id)


@router.get(
    "/{student_id}/grades",
    response_model=StudentGradeResponse,
    summary="List a student's canonical grades",
    description=(
        "grade is null when the student hasn't been graded yet, and a real "
        "numeric zero when graded as zero — the two are never conflated."
    ),
)
def get_student_grades(student_id: int, db: Session = Depends(get_db)) -> StudentGradeResponse:
    return service.get_student_grades(db, student_id)


@router.get(
    "/{student_id}/summary",
    response_model=StudentSummaryResponse,
    summary="Conservative overview of a student's canonical academic data",
    description=(
        "Aggregates canonical counts only — no GPA, averages, attendance "
        "percentages, or pass/fail status, since the underlying gradebook "
        "aggregation and full-session semantics aren't modeled yet."
    ),
)
def get_student_summary(student_id: int, db: Session = Depends(get_db)) -> StudentSummaryResponse:
    return service.get_student_summary(db, student_id)


@router.get(
    "/{student_id}/evaluation",
    response_model=StudentEvaluationResponse,
    summary="Full weighted-evaluation breakdown for any student (admin)",
    description=(
        "Same semantics as GET /me/evaluation, for instructor/administrative use. "
        "If course_id is omitted, defaults to the student's one enrolled course; "
        "ambiguous or missing enrollment returns 404."
    ),
)
def get_student_evaluation(
    student_id: int, course_id: int | None = None, db: Session = Depends(get_db)
) -> StudentEvaluationResponse:
    return evaluation_service.get_student_evaluation(db, student_id, course_id)
