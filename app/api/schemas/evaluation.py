"""Response models for the student evaluation breakdown (Phase 7) —
GET /me/evaluation and GET /students/{student_id}/evaluation.

Every field here is presentation-rounded `float`, converted explicitly
from full-precision Decimal in app.services.evaluation_service (never
repeatedly rounded mid-calculation — only at this boundary). `None`
always means "not currently calculable" (a NULL grade, or zero
evaluated weight) — never coerced to 0.
"""

from pydantic import BaseModel, Field


class EvaluationItem(BaseModel):
    grade_item_id: int
    name: str
    activity_type: str | None
    grade: float | None
    max_grade: float
    score_100: float | None = Field(
        description=(
            "(grade / max_grade) * 100, rounded to 2 decimals; null exactly when grade is null."
        )
    )
    counts_toward_current_grade: bool = Field(
        description=(
            "Whether this item is included in its category's average and this "
            "course's evaluated weight — explicit configuration, never inferred."
        )
    )


class CategoryEvaluation(BaseModel):
    category_id: int
    name: str
    weight_percent: float
    category_score_100: float | None = Field(
        description=(
            "Equal-weight average of score_100 across this category's "
            "counted AND graded items. null when none of this category's "
            "counted items have an actual grade yet — never 0."
        )
    )
    contribution_points: float | None = Field(
        description=(
            "category_score_100 * weight_percent / 100. "
            "null exactly when category_score_100 is null."
        )
    )
    counted_items: int = Field(description="Items with counts_toward_current_grade=true.")
    graded_items: int = Field(
        description="Counted items that also have an actual (non-null) grade."
    )
    ungraded_items: int = Field(description="Counted items with grade=null.")
    items: list[EvaluationItem] = Field(
        description=(
            "Every configured item in this category, counted or not, graded or not "
            "— full transparency."
        )
    )


class StudentEvaluationResponse(BaseModel):
    student_id: int
    course_id: int
    weighted_points_earned: float = Field(
        description="Sum of every calculable category's contribution_points."
    )
    evaluated_weight_percent: float = Field(
        description=(
            "Sum of weight_percent for categories that currently have at least "
            "one graded, counted item."
        )
    )
    current_score_100: float | None = Field(
        description=(
            "weighted_points_earned / evaluated_weight_percent * 100. "
            "null when evaluated_weight_percent is 0 — never 0 itself."
        )
    )
    current_grade_10: float | None = Field(
        description="current_score_100 / 10. null exactly when current_score_100 is null."
    )
    categories: list[CategoryEvaluation]
