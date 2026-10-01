"""Admin-only participation-observation models (Phase 8.1) —
POST/GET/DELETE /admin/courses/{course_id}/students/{student_id}/participation.

value is a strict integer 0-3 (a JSON boolean or string is rejected,
never coerced). Every derived number is presentation-rounded `float`,
converted from full-precision Decimal in
app.services.participation_service. With no observations the count is 0
and participation_average and participation_score_100 are 0 (participation
without observations is 0). A recorded 0 is also a real zero.
"""

from datetime import datetime
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, Field


class ParticipationObservationRequest(BaseModel):
    value: Annotated[int, Field(strict=True, ge=0, le=3)]
    observed_at: AwareDatetime | None = Field(
        default=None, description="Timezone-aware; defaults to the time of the request."
    )


class ParticipationObservationItem(BaseModel):
    observation_id: int
    value: int
    observed_at: datetime


class ParticipationSummaryFields(BaseModel):
    participation_count: int
    participation_average: float | None = Field(
        description="Arithmetic mean of all observations; 0 when there are none."
    )
    participation_score_100: float | None = Field(
        description="(participation_average / 3) * 100; 0 when there are no observations."
    )


class ParticipationSummaryResponse(ParticipationSummaryFields):
    student_id: int
    course_id: int


class ParticipationListResponse(ParticipationSummaryResponse):
    observations: list[ParticipationObservationItem]


class ParticipationRecordedResponse(ParticipationSummaryFields):
    observation_id: int
    value: int
    observed_at: datetime
