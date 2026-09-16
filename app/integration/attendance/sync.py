"""Attendance sync orchestrator and CLI entry point.

Run as a one-shot command, host-native in production (see the README's
"Host-native operational integration jobs" section) or from a container
in development:

    python -m app.integration.attendance.sync

Not scheduled by this repository, not triggered by the API, not run on
API startup. `main()` is the only place that reads
ATTENDANCE_DB_URL/DATABASE_URL/ATTENDANCE_MOODLE_COURSE_ID from the
environment; everything else takes engines/config as explicit arguments.
"""

import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.integration.attendance.config import get_attendance_sync_settings
from app.integration.attendance.merge import MergeResult, merge_batch
from app.integration.attendance.raw_writer import write_raw_batch
from app.integration.attendance.runs import (
    advance_sync_state,
    mark_sync_run_failed,
    mark_sync_run_success,
    start_sync_run,
)
from app.integration.attendance.source import extract_attendance_batch
from app.integration.attendance.staging_writer import write_staging_batch
from app.integration.attendance.validation import validate_staged_batch

SOURCE_SYSTEM = "attendance"

#: Phase 3 processes students, sessions, and attendances as one unit per
#: run (attendances depend on both), so they share a single sync_runs
#: row rather than three. Documented convention, not a fixed schema
#: requirement — mirrors the Moodle pipeline's approach.
ENTITY_TYPE = "students_sessions_attendances"


@dataclass
class SyncOutcome:
    status: str
    batch_id: uuid.UUID
    issues: list[str] = field(default_factory=list)
    merge_result: MergeResult | None = None


def run_attendance_sync(
    app_engine: Engine, attendance_engine: Engine, moodle_course_id: int
) -> SyncOutcome:
    batch_id = uuid.uuid4()
    run_id = start_sync_run(app_engine, batch_id, SOURCE_SYSTEM, ENTITY_TYPE)
    rows_read = 0

    try:
        extraction = extract_attendance_batch(attendance_engine)
        rows_read = (
            len(extraction.students) + len(extraction.sessions) + len(extraction.attendances)
        )

        # RAW is committed on its own: it must survive even if a later
        # stage in this same run hits an unexpected error.
        with app_engine.begin() as connection:
            write_raw_batch(connection, batch_id, extraction)

        with app_engine.begin() as connection:
            staging_issues = write_staging_batch(connection, batch_id, extraction)

        with app_engine.begin() as connection:
            validation_issues = validate_staged_batch(connection, moodle_course_id)

        issues = staging_issues + validation_issues
        if issues:
            mark_sync_run_failed(
                app_engine,
                run_id,
                error_message="; ".join(issues),
                rows_read=rows_read,
                error_count=len(issues),
            )
            return SyncOutcome(status="FAILED", batch_id=batch_id, issues=issues)

        now = datetime.now(UTC)
        with app_engine.begin() as connection:
            merge_result = merge_batch(connection, now, moodle_course_id)
            advance_sync_state(
                connection,
                SOURCE_SYSTEM,
                ENTITY_TYPE,
                state={
                    "last_batch_id": str(batch_id),
                    "last_snapshot_time": extraction.snapshot_time.isoformat(),
                },
                updated_at=now,
            )
            # Same transaction as the merge: SUCCESS is never visible
            # unless the academic writes above actually committed.
            mark_sync_run_success(
                connection,
                run_id,
                snapshot_time=extraction.snapshot_time,
                rows_read=rows_read,
                rows_valid=rows_read,
                counters=merge_result.counters,
            )
    except Exception as exc:
        mark_sync_run_failed(app_engine, run_id, error_message=str(exc), rows_read=rows_read)
        return SyncOutcome(status="FAILED", batch_id=batch_id, issues=[str(exc)])

    return SyncOutcome(status="SUCCESS", batch_id=batch_id, merge_result=merge_result)


def main() -> int:
    settings = get_settings()
    attendance_settings = get_attendance_sync_settings()

    app_engine = create_engine(settings.database_url)
    attendance_engine = create_engine(attendance_settings.attendance_db_url)
    try:
        outcome = run_attendance_sync(
            app_engine, attendance_engine, attendance_settings.attendance_moodle_course_id
        )
    finally:
        app_engine.dispose()
        attendance_engine.dispose()

    if outcome.status != "SUCCESS":
        print(
            f"Attendance sync FAILED (batch_id={outcome.batch_id}): {'; '.join(outcome.issues)}",
            file=sys.stderr,
        )
        return 1

    counters = outcome.merge_result.counters if outcome.merge_result else None
    print(f"Attendance sync SUCCESS (batch_id={outcome.batch_id}): {counters}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
