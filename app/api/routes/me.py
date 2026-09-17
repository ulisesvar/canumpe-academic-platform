"""Phase 6 /me endpoints — identical product semantics to the Phase 5
/students/{student_id}/* endpoints, but student_id is resolved
exclusively from the authenticated STUDENT API key
(app.auth.dependencies.require_student), never accepted from the
client. A student key can therefore never retrieve another student's
data — there is no parameter through which one could even try.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas.students import (
    StudentAttendanceResponse,
    StudentCourseResponse,
    StudentGradeResponse,
    StudentIdentityResponse,
    StudentSummaryResponse,
)
from app.auth.dependencies import require_student
from app.db.session import get_db
from app.services import student_read_service as service

router = APIRouter(prefix="/me", tags=["me"])


@router.get(
    "",
    response_model=StudentIdentityResponse,
    summary="The authenticated student's own identity",
)
def get_me(
    student_id: int = Depends(require_student), db: Session = Depends(get_db)
) -> StudentIdentityResponse:
    return service.get_student_identity(db, student_id)


@router.get(
    "/courses",
    response_model=StudentCourseResponse,
    summary="The authenticated student's own course enrollments",
)
def get_my_courses(
    student_id: int = Depends(require_student), db: Session = Depends(get_db)
) -> StudentCourseResponse:
    return service.get_student_courses(db, student_id)


@router.get(
    "/attendance",
    response_model=StudentAttendanceResponse,
    summary="The authenticated student's own recorded attendance events",
    description=(
        "Each entry is a recorded presence event only. The canonical schema "
        "does not track absence, so `present` is always true and no "
        "attendance percentage can be derived from this endpoint."
    ),
)
def get_my_attendance(
    student_id: int = Depends(require_student), db: Session = Depends(get_db)
) -> StudentAttendanceResponse:
    return service.get_student_attendance(db, student_id)


@router.get(
    "/grades",
    response_model=StudentGradeResponse,
    summary="The authenticated student's own canonical grades",
    description=(
        "grade is null when not yet graded, and a real numeric zero when "
        "graded as zero — the two are never conflated."
    ),
)
def get_my_grades(
    student_id: int = Depends(require_student), db: Session = Depends(get_db)
) -> StudentGradeResponse:
    return service.get_student_grades(db, student_id)


@router.get(
    "/summary",
    response_model=StudentSummaryResponse,
    summary="Conservative overview of the authenticated student's own academic data",
    description=(
        "Aggregates canonical counts only — no GPA, averages, attendance "
        "percentages, or pass/fail status."
    ),
)
def get_my_summary(
    student_id: int = Depends(require_student), db: Session = Depends(get_db)
) -> StudentSummaryResponse:
    return service.get_student_summary(db, student_id)
