"""Moodle grades sync orchestrator.

Called from app.integration.moodle.sync's main() — grades are ingested
by the same host-native process/systemd unit as students/courses/
enrollments (see the README's "Grades integrated into the Moodle sync"
section), never a second scheduler. Kept as its own function/module
(mirroring the Attendance pipeline's shape) so it is independently
testable and gets its own integration.sync_runs row/entity_type, since
it depends on — and is best observed separately from — the primary
students/courses/enrollments sync.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.engine import Engine

from app.integration.moodle.grades_merge import MergeResult, merge_grades_batch
from app.integration.moodle.grades_raw_writer import write_raw_grades_batch
from app.integration.moodle.grades_runs import (
    advance_sync_state,
    mark_sync_run_failed,
    mark_sync_run_success,
    start_sync_run,
)
from app.integration.moodle.grades_source import extract_moodle_grades_batch
from app.integration.moodle.grades_staging_writer import write_staging_grades_batch
from app.integration.moodle.grades_validation import validate_staged_grades_batch

SOURCE_SYSTEM = "moodle"

#: Phase 4 processes grade items and student grades as one unit per run
#: (student grades depend on grade items), sharing a single sync_runs row
#: — distinct from "students_courses_enrollments" because grades resolve
#: through mappings that pipeline already maintains, rather than creating
#: them.
ENTITY_TYPE = "grade_items_student_grades"


@dataclass
class GradesSyncOutcome:
    status: str
    batch_id: uuid.UUID
    issues: list[str] = field(default_factory=list)
    merge_result: MergeResult | None = None


def run_moodle_grades_sync(
    app_engine: Engine, moodle_engine: Engine, course_id: int
) -> GradesSyncOutcome:
    batch_id = uuid.uuid4()
    run_id = start_sync_run(app_engine, batch_id, SOURCE_SYSTEM, ENTITY_TYPE)
    rows_read = 0

    try:
        extraction = extract_moodle_grades_batch(moodle_engine, course_id)
        rows_read = len(extraction.grade_items) + len(extraction.student_grades)

        # RAW is committed on its own: it must survive even if a later
        # stage in this same run hits an unexpected error.
        with app_engine.begin() as connection:
            write_raw_grades_batch(connection, batch_id, course_id, extraction)

        with app_engine.begin() as connection:
            staging_issues = write_staging_grades_batch(connection, batch_id, course_id, extraction)

        with app_engine.begin() as connection:
            validation_issues = validate_staged_grades_batch(connection, course_id)

        issues = staging_issues + validation_issues
        if issues:
            mark_sync_run_failed(
                app_engine,
                run_id,
                error_message="; ".join(issues),
                rows_read=rows_read,
                error_count=len(issues),
            )
            return GradesSyncOutcome(status="FAILED", batch_id=batch_id, issues=issues)

        now = datetime.now(UTC)
        with app_engine.begin() as connection:
            merge_result = merge_grades_batch(connection, now, course_id)
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
            #
            # Counter semantics mirror the Attendance pipeline:
            # - rows_read: every row extraction returned (grade items +
            #   student grades), before any check — including hidden rows.
            # - rows_valid: rows_read, whenever validate_staged_grades_batch
            #   found zero blocking issues for the batch.
            # - rows_skipped (counters.rows_skipped, from merge_grades_batch):
            #   a student grade whose student_source_id doesn't resolve to
            #   any academic student yet — not an error, see grades_merge.py.
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
        return GradesSyncOutcome(status="FAILED", batch_id=batch_id, issues=[str(exc)])

    return GradesSyncOutcome(status="SUCCESS", batch_id=batch_id, merge_result=merge_result)
