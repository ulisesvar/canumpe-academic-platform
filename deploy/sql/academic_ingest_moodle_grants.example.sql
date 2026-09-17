-- Reference template for the Academic Database's Moodle-ingest credential.
--
-- Run manually by a database administrator against the production
-- Academic PostgreSQL. The application never creates this role, never
-- grants it anything, and never runs this file — Alembic migrations
-- only ever run as the existing database-owner credential used by the
-- api/migrate services.
--
-- Least privilege: this role can read/write only the schemas and
-- academic tables the Moodle pipeline actually touches. It is not a
-- database owner, not a superuser, and cannot create databases, roles,
-- or new objects.

CREATE ROLE academic_ingest_moodle LOGIN PASSWORD '<set a real secret here>';

-- raw_moodle: the pipeline only ever appends here.
GRANT USAGE ON SCHEMA raw_moodle TO academic_ingest_moodle;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA raw_moodle TO academic_ingest_moodle;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA raw_moodle TO academic_ingest_moodle;

-- staging: rebuilt every run, so it also needs UPDATE/DELETE.
GRANT USAGE ON SCHEMA staging TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA staging TO academic_ingest_moodle;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA staging TO academic_ingest_moodle;

-- integration: source mappings and sync_runs/sync_state.
GRANT USAGE ON SCHEMA integration TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA integration TO academic_ingest_moodle;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA integration TO academic_ingest_moodle;

-- academic: only the tables this pipeline actually merges into — not the
-- whole schema, and never DELETE (canonical records are never physically
-- deleted by this pipeline). grade_items/student_grades (Phase 4) are
-- merged by the same credential, since grades run as part of this same
-- Moodle sync process — see the README's "Grades integrated into the
-- Moodle sync" section.
GRANT USAGE ON SCHEMA academic TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE ON academic.students TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE ON academic.courses TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE ON academic.enrollments TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE ON academic.grade_items TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE ON academic.student_grades TO academic_ingest_moodle;
GRANT USAGE ON
    SEQUENCE academic.students_id_seq,
    SEQUENCE academic.courses_id_seq,
    SEQUENCE academic.enrollments_id_seq,
    SEQUENCE academic.grade_items_id_seq,
    SEQUENCE academic.student_grades_id_seq
    TO academic_ingest_moodle;

-- Explicitly not granted: CREATE, DROP, ALTER, ownership, superuser,
-- CREATE DATABASE, access to raw_attendance/auth, or DELETE on academic.
