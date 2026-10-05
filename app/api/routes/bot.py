"""Bot-only read endpoint for the Telegram attendance bot.

A BOT API key (app.auth.dependencies.require_bot) is restricted to one
course, carried by the credential itself. The only thing the bot may do
is read ONE student's current evaluation in that course; it can reach no
other router (/admin/*, /students/*, /me/* all reject it with 403) and
the route performs no write.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas.evaluation import StudentEvaluationResponse
from app.auth.dependencies import require_bot
from app.db.session import get_db
from app.services import evaluation_service

router = APIRouter(prefix="/bot", tags=["bot"])


@router.get(
    "/evaluation/{account_number}",
    response_model=StudentEvaluationResponse,
    summary="One student's current evaluation, for the bot's course (bot key)",
    description=(
        "Same response and calculation as GET /me/evaluation. The course comes ONLY "
        "from the bot API key; the client cannot supply course_id. 404 when the "
        "account number is unknown OR the student has no active enrollment in the "
        "key's course — the two cases are indistinguishable."
    ),
)
def get_bot_evaluation(
    account_number: str,
    course_id: int = Depends(require_bot),
    db: Session = Depends(get_db),
) -> StudentEvaluationResponse:
    return evaluation_service.get_bot_student_evaluation(db, course_id, account_number)
