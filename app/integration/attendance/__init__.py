"""Attendance ingestion pipeline: extraction -> raw_attendance -> staging
-> academic.

Only ever invoked as a separate service/command (see sync.py). The
public API never imports from here and never receives Attendance
credentials. Attendance students reconcile to existing canonical
students (created by Moodle sync) by account_number — this pipeline
never creates a new academic.students row.
"""
