-- Reference template for Moodle's own PostgreSQL: the read-only source
-- credential the Academic Platform's Moodle sync uses to extract
-- students/courses/enrollments and (since Phase 4) grade items/student
-- grades.
--
-- Run manually by Moodle's own database administrators against Moodle's
-- production PostgreSQL — never by this application's code or
-- migrations. This repository never creates this role and never grants
-- it anything. This file did not previously exist even though the role
-- has been live in production since Phase 2; it is added now so a fresh
-- installation can reproduce the exact grants already applied manually,
-- including the mdl_grade_items/mdl_grade_grades SELECT added for
-- Phase 4 — see the README's "Database access model" section.
--
-- Least privilege: SELECT only, on exactly the Moodle tables
-- app.integration.moodle.source and app.integration.moodle.grades_source
-- actually query. Not a database owner, not a superuser, no INSERT/
-- UPDATE/DELETE anywhere, and no access to any other Moodle table
-- (never mdl_user_info_data.data for fields other than 'cuenta', never
-- gradebook history/outcomes/scales, never any other course).

CREATE ROLE academic_sync_moodle LOGIN PASSWORD '<set a real secret here>';

GRANT USAGE ON SCHEMA public TO academic_sync_moodle;

-- Students: account_number resolution via the 'cuenta' custom profile
-- field, scoped to active enrollments — see
-- app.integration.moodle.source.ACCOUNT_NUMBER_FIELD_SHORTNAME.
GRANT SELECT ON public.mdl_user TO academic_sync_moodle;
GRANT SELECT ON public.mdl_user_info_field TO academic_sync_moodle;
GRANT SELECT ON public.mdl_user_info_data TO academic_sync_moodle;

-- Courses and enrollments, scoped to the configured MOODLE_COURSE_ID.
GRANT SELECT ON public.mdl_course TO academic_sync_moodle;
GRANT SELECT ON public.mdl_enrol TO academic_sync_moodle;
GRANT SELECT ON public.mdl_user_enrolments TO academic_sync_moodle;

-- Grade items/grades (Phase 4). Extraction itself filters to
-- itemtype='mod' and the configured course — this grant does not need
-- to (and cannot, at the privilege level) restrict by row, only by
-- table. See app.integration.moodle.grades_source.
GRANT SELECT ON public.mdl_grade_items TO academic_sync_moodle;
GRANT SELECT ON public.mdl_grade_grades TO academic_sync_moodle;

-- Explicitly not granted: INSERT, UPDATE, DELETE, CREATE, DROP, ALTER,
-- ownership, superuser, CREATE DATABASE, or SELECT on any other Moodle
-- table (grade history, outcomes, scales, other courses' data, etc.).
