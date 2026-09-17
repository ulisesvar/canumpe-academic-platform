"""Moodle sync orchestrator and CLI entry point.

Run as a one-shot command, host-native in production (see the README's
"Host-native operational integration jobs" section) or from a container
in development:

    python -m app.integration.moodle.sync

Not scheduled by this repository, not triggered by the API, not run on
API startup. Since Phase 4, `main()` also runs the grades sync
(`app.integration.moodle.grades_sync`) right after the primary students/
courses/enrollments sync — one process invocation, one systemd unit, per
the README's "Grades integrated into the Moodle sync" section, rather
than a second scheduler. `main()` is the only place that reads
MOODLE_DB_URL/DATABASE_URL/MOODLE_COURSE_ID from the environment;
everything else takes engines as explicit arguments, so the pipeline
itself never depends on process-wide configuration and is easy to test.
"""

import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.core.config import get_settings
from app.integration.moodle.config import get_moodle_sync_settings
from app.integration.moodle.grades_sync import run_moodle_grades_sync
from app.integration.moodle.merge import MergeResult, merge_batch
from app.integration.moodle.raw_writer import write_raw_batch
from app.integration.moodle.runs import (
    advance_sync_state,
    mark_sync_run_failed,
    mark_sync_run_success,
    start_sync_run,
)
from app.integration.moodle.source import extract_moodle_batch
from app.integration.moodle.staging_writer import write_staging_batch
from app.integration.moodle.validation import validate_staged_batch

SOURCE_SYSTEM = "moodle"

#: Phase 2 processes students, courses, and enrollments as one unit per
#: run (enrollments depend on both), so they share a single sync_runs
#: row rather than three. This is a documented convention, not a fixed
#: schema requirement — a later phase could split them if useful.
ENTITY_TYPE = "students_courses_enrollments"


@dataclass
class SyncOutcome:
    status: str
    batch_id: uuid.UUID
    issues: list[str] = field(default_factory=list)
    merge_result: MergeResult | None = None


def run_moodle_sync(app_engine: Engine, moodle_engine: Engine, course_id: int) -> SyncOutcome:
    batch_id = uuid.uuid4()
    run_id = start_sync_run(app_engine, batch_id, SOURCE_SYSTEM, ENTITY_TYPE)
    rows_read = 0

    try:
        extraction = extract_moodle_batch(moodle_engine, course_id)
        rows_read = len(extraction.students) + len(extraction.courses) + len(extraction.enrollments)

        # RAW is committed on its own: it must survive even if a later
        # stage in this same run hits an unexpected error.
        with app_engine.begin() as connection:
            write_raw_batch(connection, batch_id, extraction)

        with app_engine.begin() as connection:
            staging_issues = write_staging_batch(connection, batch_id, extraction)

        with app_engine.begin() as connection:
            validation_issues = validate_staged_batch(connection)

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
            merge_result = merge_batch(connection, now)
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
    """Runs the primary students/courses/enrollments sync, then the
    grades sync — one process invocation, one systemd unit, per the
    README's "Grades integrated into the Moodle sync" section. Grades
    always run, even if the primary sync failed: grades resolve through
    whatever student/course mappings already exist from the last
    successful sync, and withholding them on a transient primary failure
    would only delay otherwise-mergeable grade data for no benefit. Each
    stage gets its own integration.sync_runs row and is independently
    observable; the process exits non-zero if either stage failed.
    """
    settings = get_settings()
    moodle_settings = get_moodle_sync_settings()

    app_engine = create_engine(settings.database_url)
    moodle_engine = create_engine(moodle_settings.moodle_db_url)
    try:
        outcome = run_moodle_sync(app_engine, moodle_engine, moodle_settings.moodle_course_id)
        grades_outcome = run_moodle_grades_sync(
            app_engine, moodle_engine, moodle_settings.moodle_course_id
        )
    finally:
        app_engine.dispose()
        moodle_engine.dispose()

    exit_code = 0

    if outcome.status != "SUCCESS":
        print(
            f"Moodle sync FAILED (batch_id={outcome.batch_id}): {'; '.join(outcome.issues)}",
            file=sys.stderr,
        )
        exit_code = 1
    else:
        counters = outcome.merge_result.counters if outcome.merge_result else None
        print(f"Moodle sync SUCCESS (batch_id={outcome.batch_id}): {counters}")

    if grades_outcome.status != "SUCCESS":
        print(
            f"Moodle grades sync FAILED (batch_id={grades_outcome.batch_id}): "
            f"{'; '.join(grades_outcome.issues)}",
            file=sys.stderr,
        )
        exit_code = 1
    else:
        grades_counters = (
            grades_outcome.merge_result.counters if grades_outcome.merge_result else None
        )
        print(f"Moodle grades sync SUCCESS (batch_id={grades_outcome.batch_id}): {grades_counters}")

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
