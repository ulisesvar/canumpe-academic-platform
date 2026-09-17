"""Query layer: explicit SQLAlchemy queries against academic.* only.

Never integration.*/raw_moodle.*/raw_attendance.*/staging.* — those are
ingestion-internal, not product read models. Never a write.
"""
