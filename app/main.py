from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.api.routes.admin import router as admin_router
from app.api.routes.me import router as me_router
from app.api.routes.students import router as students_router
from app.services.evaluation_service import (
    CourseNotFoundError,
    InvalidEvaluationSchemeError,
    NoEvaluableCourseError,
)
from app.services.student_read_service import StudentNotFoundError

app = FastAPI(title="CANUMPE Academic Platform", version="0.1.0")
app.include_router(health_router)
app.include_router(students_router)
app.include_router(me_router)
app.include_router(admin_router)


@app.exception_handler(StudentNotFoundError)
def _handle_student_not_found(request: Request, exc: StudentNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Student not found"})


@app.exception_handler(CourseNotFoundError)
def _handle_course_not_found(request: Request, exc: CourseNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Course not found"})


@app.exception_handler(NoEvaluableCourseError)
def _handle_no_evaluable_course(request: Request, exc: NoEvaluableCourseError) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"detail": "No single enrolled course to evaluate; specify course_id"},
    )


@app.exception_handler(InvalidEvaluationSchemeError)
def _handle_invalid_evaluation_scheme(
    request: Request, exc: InvalidEvaluationSchemeError
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})
