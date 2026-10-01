"""Admin-only configuration, data-entry and reporting endpoints: the
evaluation scheme (Phase 7), participation observations (Phase 8.1),
and the course roster and gradebook (Phase 8.4).

Every route here requires an ADMIN API key (app.auth.dependencies.require_admin,
applied once at the router level below) — a STUDENT key gets 403. This
is the only way evaluation categories/weights/grade-item assignments
and participation observations are ever written; there is no
student-facing write path anywhere in this API. See
app.services.evaluation_service for the validation and atomic-replace
semantics behind the scheme PUT, and app.services.participation_service
for participation.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas.evaluation_scheme import EvaluationSchemeRequest, EvaluationSchemeResponse
from app.api.schemas.gradebook import CourseRosterResponse, GradebookResponse
from app.api.schemas.participation import (
    ParticipationListResponse,
    ParticipationObservationRequest,
    ParticipationRecordedResponse,
    ParticipationSummaryResponse,
)
from app.auth.dependencies import require_admin
from app.auth.models import ApiKey
from app.db.session import get_db
from app.services import evaluation_service, gradebook_service, participation_service

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get(
    "/courses/{course_id}/evaluation-scheme",
    response_model=EvaluationSchemeResponse,
    summary="Read a course's evaluation categories, weights, and grade-item assignments",
)
def get_evaluation_scheme(
    course_id: int, db: Session = Depends(get_db)
) -> EvaluationSchemeResponse:
    return evaluation_service.get_evaluation_scheme(db, course_id)


@router.put(
    "/courses/{course_id}/evaluation-scheme",
    response_model=EvaluationSchemeResponse,
    summary="Atomically replace a course's entire evaluation scheme",
    description=(
        "Validates the complete payload (weights total exactly 100%, no duplicate "
        "category name/sort_order, each grade item assigned to at most one category "
        "and belonging to this course) before writing anything — either the whole "
        "update succeeds or nothing changes."
    ),
)
def put_evaluation_scheme(
    course_id: int, payload: EvaluationSchemeRequest, db: Session = Depends(get_db)
) -> EvaluationSchemeResponse:
    return evaluation_service.replace_evaluation_scheme(db, course_id, payload)


@router.post(
    "/courses/{course_id}/students/{student_id}/participation",
    response_model=ParticipationRecordedResponse,
    status_code=201,
    summary="Record one participation observation (0, 1, 2 or 3)",
    description=(
        "Appends an observation; a student may have many. Returns the recorded "
        "observation and the student's updated participation summary. 404 if the "
        "course or student doesn't exist, or the student isn't enrolled in the course."
    ),
)
def post_participation_observation(
    course_id: int,
    student_id: int,
    payload: ParticipationObservationRequest,
    api_key: ApiKey = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ParticipationRecordedResponse:
    return participation_service.record_observation(db, course_id, student_id, payload, api_key)


@router.get(
    "/courses/{course_id}/students/{student_id}/participation",
    response_model=ParticipationListResponse,
    summary="List a student's participation observations and summary",
    description=(
        "participation_average is the arithmetic mean of all observations and "
        "participation_score_100 is (average / 3) * 100. With no observations, count is 0 "
        "and both are 0 (participation without observations is 0)."
    ),
)
def get_participation(
    course_id: int, student_id: int, db: Session = Depends(get_db)
) -> ParticipationListResponse:
    return participation_service.get_participation(db, course_id, student_id)


@router.delete(
    "/courses/{course_id}/students/{student_id}/participation/{observation_id}",
    response_model=ParticipationSummaryResponse,
    summary="Delete one participation observation",
    description=(
        "Hard-deletes exactly that observation and returns the updated summary. An "
        "observation belonging to a different course or student is a 404, identical to "
        "one that doesn't exist."
    ),
)
def delete_participation_observation(
    course_id: int, student_id: int, observation_id: int, db: Session = Depends(get_db)
) -> ParticipationSummaryResponse:
    return participation_service.delete_observation(db, course_id, student_id, observation_id)


@router.get(
    "/courses/{course_id}/students",
    response_model=CourseRosterResponse,
    summary="List a course's students",
    description=(
        "Students with an active enrollment in the course, ordered by last name, first "
        "name, then id. full_name is derived (first_name + ' ' + last_name). NOTE: "
        "enrollment ingestion currently never deactivates enrollments that vanish from "
        "Moodle, so the active filter does not yet exclude former students."
    ),
)
def get_course_roster(course_id: int, db: Session = Depends(get_db)) -> CourseRosterResponse:
    return gradebook_service.get_course_roster(db, course_id)


@router.get(
    "/courses/{course_id}/gradebook",
    response_model=GradebookResponse,
    summary="The whole class's grades, attendance, participation and current grade",
    description=(
        "One response for the entire course, computed from a constant number of queries "
        "with the same rules as GET /students/{student_id}/evaluation. `columns` lists every "
        "grade item (assigned items by category sort_order then GradeItem.id, unassigned "
        "after; GradeItem.id is ingestion order, not necessarily Moodle's display order). "
        "null always means not calculable — never 0. There is no final grade, only the "
        "current grade."
    ),
)
def get_course_gradebook(course_id: int, db: Session = Depends(get_db)) -> GradebookResponse:
    return gradebook_service.get_course_gradebook(db, course_id)
