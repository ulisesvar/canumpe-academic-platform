from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.api.routes.me import router as me_router
from app.api.routes.students import router as students_router
from app.services.student_read_service import StudentNotFoundError

app = FastAPI(title="CANUMPE Academic Platform", version="0.1.0")
app.include_router(health_router)
app.include_router(students_router)
app.include_router(me_router)


@app.exception_handler(StudentNotFoundError)
def _handle_student_not_found(request: Request, exc: StudentNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "Student not found"})
