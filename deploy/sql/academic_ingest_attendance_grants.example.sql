-- Reference template for the Academic Database's Attendance-ingest
-- credential.
--
-- Run manually by a database administrator against the production
-- Academic PostgreSQL. The application never creates this role, never
-- grants it anything, and never runs this file — Alembic migrations
-- only ever run as the existing database-owner credential used by the
-- api/migrate services.
--
-- Least privilege: this role can read/write only the schemas and
-- academic tables the Attendance pipeline actually touches. It is not a
-- database owner, not a superuser, and cannot create databases, roles,
-- or new objects. Note it needs SELECT on academic.students (to
-- reconcile by account_number) and INSERT/UPDATE on
-- integration.student_sources (to record the mapping) but never
-- INSERT/UPDATE on academic.students itself — this pipeline must never
-- create or modify a canonical student.

CREATE ROLE academic_ingest_attendance LOGIN PASSWORD '<set a real secret here>';

-- raw_attendance: the pipeline only ever appends here.
GRANT USAGE ON SCHEMA raw_attendance TO academic_ingest_attendance;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA raw_attendance TO academic_ingest_attendance;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA raw_attendance TO academic_ingest_attendance;

-- staging: rebuilt every run, so it also needs UPDATE/DELETE.
GRANT USAGE ON SCHEMA staging TO academic_ingest_attendance;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA staging TO academic_ingest_attendance;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA staging TO academic_ingest_attendance;

-- integration: student_sources (reconciliation mappings, source_system=
-- 'attendance'), the new attendance_session_sources/
-- attendance_record_sources, and sync_runs/sync_state. Also needs
-- SELECT on course_sources to resolve the Moodle course mapping.
GRANT USAGE ON SCHEMA integration TO academic_ingest_attendance;
GRANT SELECT, INSERT, UPDATE ON integration.student_sources TO academic_ingest_attendance;
GRANT SELECT ON integration.course_sources TO academic_ingest_attendance;
GRANT SELECT, INSERT, UPDATE ON integration.attendance_session_sources TO academic_ingest_attendance;
GRANT SELECT, INSERT, UPDATE ON integration.attendance_record_sources TO academic_ingest_attendance;
GRANT SELECT, INSERT, UPDATE ON integration.sync_runs TO academic_ingest_attendance;
GRANT SELECT, INSERT, UPDATE ON integration.sync_state TO academic_ingest_attendance;
GRANT USAGE ON
    SEQUENCE integration.attendance_session_sources_id_seq,
    SEQUENCE integration.attendance_record_sources_id_seq,
    SEQUENCE integration.sync_runs_id_seq,
    SEQUENCE integration.sync_state_id_seq
    TO academic_ingest_attendance;

-- academic: read-only on students (to reconcile by account_number, and
-- to enforce the FK on attendance_records) and write on the two new
-- attendance tables only. Never INSERT/UPDATE/DELETE on
-- academic.students, academic.courses, or academic.enrollments.
GRANT USAGE ON SCHEMA academic TO academic_ingest_attendance;
GRANT SELECT ON academic.students TO academic_ingest_attendance;
GRANT SELECT ON academic.courses TO academic_ingest_attendance;
GRANT SELECT, INSERT, UPDATE ON academic.attendance_sessions TO academic_ingest_attendance;
GRANT SELECT, INSERT, UPDATE ON academic.attendance_records TO academic_ingest_attendance;
GRANT USAGE ON
    SEQUENCE academic.attendance_sessions_id_seq,
    SEQUENCE academic.attendance_records_id_seq
    TO academic_ingest_attendance;

-- Explicitly not granted: CREATE, DROP, ALTER, ownership, superuser,
-- CREATE DATABASE, access to raw_moodle/auth, any write access to
-- academic.students/courses/enrollments, or DELETE on academic tables.
