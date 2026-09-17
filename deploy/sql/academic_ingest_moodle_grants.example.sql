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
--
-- Every grant below is on a named table/sequence — deliberately never
-- "ALL TABLES/SEQUENCES IN SCHEMA x". A schema-wide grant only ever
-- covers the tables that exist at the moment it is run: it silently
-- fails to cover a table a *later* migration adds to that same schema,
-- which is exactly how production briefly lost access to
-- integration.sync_issues after 0005_sync_issues shipped (see
-- deploy/sql/academic_ingest_attendance_grants.example.sql's history).
-- Naming every object here instead means a future migration that adds a
-- new raw_moodle/staging/integration/academic table for this pipeline
-- MUST update this file too, or the gap becomes obvious by inspection —
-- see tests/unit/test_moodle_grants_reference.py, which fails CI if a
-- runtime object this pipeline needs isn't named here.

CREATE ROLE academic_ingest_moodle LOGIN PASSWORD '<set a real secret here>';

-- raw_moodle: the pipeline only ever appends here. grade_items/
-- student_grades (Phase 4) land here via the same credential, since
-- grades run as part of this same Moodle sync process.
GRANT USAGE ON SCHEMA raw_moodle TO academic_ingest_moodle;
GRANT SELECT, INSERT ON raw_moodle.students TO academic_ingest_moodle;
GRANT SELECT, INSERT ON raw_moodle.courses TO academic_ingest_moodle;
GRANT SELECT, INSERT ON raw_moodle.enrollments TO academic_ingest_moodle;
GRANT SELECT, INSERT ON raw_moodle.grade_items TO academic_ingest_moodle;
GRANT SELECT, INSERT ON raw_moodle.student_grades TO academic_ingest_moodle;
GRANT USAGE ON
    SEQUENCE raw_moodle.students_id_seq,
    SEQUENCE raw_moodle.courses_id_seq,
    SEQUENCE raw_moodle.enrollments_id_seq,
    SEQUENCE raw_moodle.grade_items_id_seq,
    SEQUENCE raw_moodle.student_grades_id_seq
    TO academic_ingest_moodle;

-- staging: rebuilt every run, so it also needs UPDATE/DELETE. Only the
-- Moodle-owned staging tables — never staging.attendance_*, which
-- belongs to the separate academic_ingest_attendance credential even
-- though it lives in the same schema.
GRANT USAGE ON SCHEMA staging TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE, DELETE ON staging.students TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE, DELETE ON staging.courses TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE, DELETE ON staging.enrollments TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE, DELETE ON staging.grade_items TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE, DELETE ON staging.student_grades TO academic_ingest_moodle;
GRANT USAGE ON
    SEQUENCE staging.students_id_seq,
    SEQUENCE staging.courses_id_seq,
    SEQUENCE staging.enrollments_id_seq,
    SEQUENCE staging.grade_items_id_seq,
    SEQUENCE staging.student_grades_id_seq
    TO academic_ingest_moodle;

-- integration: source mappings this pipeline reads/writes, plus
-- sync_runs/sync_state/sync_issues. sync_issues needs SELECT/INSERT/
-- UPDATE (never DELETE — issues are retained permanently) for the
-- UNRESOLVED_GRADE_STUDENT open/resolve lifecycle (Phase 4) — the exact
-- kind of grant a "ALL TABLES IN SCHEMA integration" shortcut would have
-- silently omitted after the fact, per this file's header note.
GRANT USAGE ON SCHEMA integration TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE ON integration.student_sources TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE ON integration.course_sources TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE ON integration.enrollment_sources TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE ON integration.grade_item_sources TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE ON integration.student_grade_sources TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE ON integration.sync_runs TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE ON integration.sync_state TO academic_ingest_moodle;
GRANT SELECT, INSERT, UPDATE ON integration.sync_issues TO academic_ingest_moodle;
GRANT USAGE ON
    SEQUENCE integration.student_sources_id_seq,
    SEQUENCE integration.course_sources_id_seq,
    SEQUENCE integration.enrollment_sources_id_seq,
    SEQUENCE integration.grade_item_sources_id_seq,
    SEQUENCE integration.student_grade_sources_id_seq,
    SEQUENCE integration.sync_runs_id_seq,
    SEQUENCE integration.sync_state_id_seq,
    SEQUENCE integration.sync_issues_id_seq
    TO academic_ingest_moodle;

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
-- CREATE DATABASE, access to raw_attendance/staging.attendance_*/auth,
-- or DELETE on academic/integration.
