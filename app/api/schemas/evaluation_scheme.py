"""Admin-only evaluation-scheme configuration (Phase 7) —
GET/PUT /admin/courses/{course_id}/evaluation-scheme.

Request models use Decimal for weight_percent (never float) so a
category weight is never subject to binary-floating-point error before
the exact-100% validation in app.services.evaluation_service. Response
models use presentation-rounded float, matching every other response
in this API.
"""

from decimal import Decimal

from pydantic import BaseModel, Field


class GradeItemAssignmentRequest(BaseModel):
    grade_item_id: int
    counts_toward_current_grade: bool


class CategorySchemeRequest(BaseModel):
    name: str
    weight_percent: Decimal
    sort_order: int
    grade_items: list[GradeItemAssignmentRequest] = Field(default_factory=list)


class EvaluationSchemeRequest(BaseModel):
    categories: list[CategorySchemeRequest]


class GradeItemAssignment(BaseModel):
    grade_item_id: int
    name: str
    activity_type: str | None
    counts_toward_current_grade: bool


class CategoryScheme(BaseModel):
    category_id: int
    name: str
    weight_percent: float
    sort_order: int
    grade_items: list[GradeItemAssignment]


class UnassignedGradeItem(BaseModel):
    grade_item_id: int
    name: str
    activity_type: str | None


class EvaluationSchemeResponse(BaseModel):
    course_id: int
    course_name: str
    categories: list[CategoryScheme]
    unassigned_grade_items: list[UnassignedGradeItem] = Field(
        description=(
            "Canonical grade items in this course not yet assigned to any evaluation category."
        )
    )
