"""Admin-only evaluation-scheme configuration endpoints.

Every route here requires an ADMIN API key (app.auth.dependencies.require_admin,
applied once at the router level below) — a STUDENT key gets 403. This
is the only way evaluation categories/weights/grade-item assignments
are ever configured; there is no student-facing write path anywhere in
this API. See app.services.evaluation_service for the validation and
atomic-replace semantics behind the PUT.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas.evaluation_scheme import EvaluationSchemeRequest, EvaluationSchemeResponse
from app.auth.dependencies import require_admin
from app.db.session import get_db
from app.services import evaluation_service

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
