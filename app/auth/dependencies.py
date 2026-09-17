"""FastAPI authentication/authorization dependencies for the API-key
security model.

    HTTP request -> X-API-Key -> SHA-256 -> auth.api_keys lookup
    (read-only) -> role/student resolution -> route-level role check

Kept entirely separate from academic read logic
(app.services.student_read_service): this module only ever hands a
route a resolved role or student_id, never touches academic.*.

Authentication failures are deliberately generic and uniform — missing,
malformed, unknown, and revoked keys all produce the exact same 401
response, so a caller can never learn whether a particular key exists
by observing a different error for each case.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.auth.api_keys import get_active_key_by_hash, hash_key
from app.auth.models import ROLE_ADMIN, ROLE_STUDENT, ApiKey
from app.db.session import get_db

API_KEY_HEADER_NAME = "X-API-Key"

_api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key",
    )


def _authenticate(api_key: str | None, db: Session) -> ApiKey:
    if not api_key:
        raise _unauthorized()
    record = get_active_key_by_hash(db, hash_key(api_key))
    if record is None:
        raise _unauthorized()
    return record


def require_admin(
    api_key: str | None = Depends(_api_key_header),
    db: Session = Depends(get_db),
) -> ApiKey:
    """Authorizes an ADMIN-role credential. Protects every
    /students/{student_id}/* route — see app.api.routes.students.
    """
    record = _authenticate(api_key, db)
    if record.role != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin API key required"
        )
    return record


def require_student(
    api_key: str | None = Depends(_api_key_header),
    db: Session = Depends(get_db),
) -> int:
    """Authorizes a STUDENT-role credential and returns the
    authenticated student's canonical student_id — resolved exclusively
    from the credential, never accepted as client input. Backs every
    /me/* route — see app.api.routes.me.
    """
    record = _authenticate(api_key, db)
    if record.role != ROLE_STUDENT:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Student API key required"
        )
    assert record.student_id is not None, (
        "ck_api_keys_role_student_id_consistency guarantees a student-role row always "
        "has a student_id"
    )
    return record.student_id
