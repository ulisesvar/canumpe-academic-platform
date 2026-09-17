"""A minimal fake Moodle PostgreSQL schema for tests.

Mimics only the mdl_* tables/columns app.integration.moodle.source
actually queries — never a full Moodle schema, and never a connection to
a real Moodle instance. Lives in the "public" schema of the same test
database (our own tables are always schema-qualified under academic/
integration/raw_moodle/staging/auth, so "public" is free to reuse here).
"""

from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS mdl_user (
    id SERIAL PRIMARY KEY,
    deleted SMALLINT NOT NULL DEFAULT 0,
    firstname TEXT NOT NULL,
    lastname TEXT NOT NULL,
    email TEXT,
    timemodified BIGINT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mdl_user_info_field (
    id SERIAL PRIMARY KEY,
    shortname TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mdl_user_info_data (
    id SERIAL PRIMARY KEY,
    userid INTEGER NOT NULL,
    fieldid INTEGER NOT NULL,
    data TEXT
);
CREATE TABLE IF NOT EXISTS mdl_course (
    id SERIAL PRIMARY KEY,
    shortname TEXT,
    fullname TEXT NOT NULL,
    visible SMALLINT NOT NULL DEFAULT 1,
    timemodified BIGINT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mdl_enrol (
    id SERIAL PRIMARY KEY,
    courseid INTEGER NOT NULL,
    status SMALLINT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mdl_user_enrolments (
    id SERIAL PRIMARY KEY,
    enrolid INTEGER NOT NULL,
    userid INTEGER NOT NULL,
    status SMALLINT NOT NULL DEFAULT 0,
    timemodified BIGINT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mdl_grade_items (
    id SERIAL PRIMARY KEY,
    courseid INTEGER NOT NULL,
    itemtype TEXT NOT NULL,
    itemmodule TEXT,
    itemname TEXT,
    grademax NUMERIC(10, 5) NOT NULL DEFAULT 100,
    hidden SMALLINT NOT NULL DEFAULT 0,
    timemodified BIGINT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mdl_grade_grades (
    id SERIAL PRIMARY KEY,
    itemid INTEGER NOT NULL,
    userid INTEGER NOT NULL,
    finalgrade NUMERIC(10, 5),
    hidden SMALLINT NOT NULL DEFAULT 0,
    timemodified BIGINT NOT NULL DEFAULT 0
);
"""

FAKE_MOODLE_TABLES = (
    "mdl_user",
    "mdl_user_info_field",
    "mdl_user_info_data",
    "mdl_course",
    "mdl_enrol",
    "mdl_user_enrolments",
    "mdl_grade_items",
    "mdl_grade_grades",
)

PIPELINE_TABLES = (
    "integration.enrollment_sources",
    "integration.course_sources",
    "integration.student_sources",
    "integration.student_grade_sources",
    "integration.grade_item_sources",
    "integration.sync_runs",
    "integration.sync_state",
    "integration.sync_issues",
    "academic.student_grades",
    "academic.grade_items",
    "academic.enrollments",
    "academic.courses",
    "academic.students",
    "raw_moodle.enrollments",
    "raw_moodle.courses",
    "raw_moodle.students",
    "raw_moodle.student_grades",
    "raw_moodle.grade_items",
    "staging.enrollments",
    "staging.courses",
    "staging.students",
    "staging.student_grades",
    "staging.grade_items",
)


def create_fake_moodle_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(CREATE_TABLES_SQL))


def truncate_fake_moodle_schema(engine: Engine) -> None:
    tables = ", ".join(FAKE_MOODLE_TABLES)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


def truncate_pipeline_tables(engine: Engine) -> None:
    tables = ", ".join(PIPELINE_TABLES)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


def insert_user(
    connection: Connection,
    *,
    firstname: str,
    lastname: str,
    email: str | None = None,
    deleted: int = 0,
    timemodified: int = 0,
) -> int:
    return connection.execute(
        text("""
            INSERT INTO mdl_user (firstname, lastname, email, deleted, timemodified)
            VALUES (:firstname, :lastname, :email, :deleted, :timemodified)
            RETURNING id
        """),
        {
            "firstname": firstname,
            "lastname": lastname,
            "email": email,
            "deleted": deleted,
            "timemodified": timemodified,
        },
    ).scalar_one()


def insert_user_info_field(connection: Connection, shortname: str) -> int:
    return connection.execute(
        text("INSERT INTO mdl_user_info_field (shortname) VALUES (:shortname) RETURNING id"),
        {"shortname": shortname},
    ).scalar_one()


def ensure_cuenta_field(connection: Connection) -> int:
    """Creates the 'cuenta' custom field, deliberately NOT at id=1.

    A decoy field is inserted first so a test relying on `shortname`
    lookup (correct) rather than a hardcoded fieldid (wrong) cannot pass
    by accident.
    """
    insert_user_info_field(connection, "telefono")
    return insert_user_info_field(connection, "cuenta")


def set_account_number(
    connection: Connection, userid: int, fieldid: int, account_number: str
) -> None:
    connection.execute(
        text(
            "INSERT INTO mdl_user_info_data (userid, fieldid, data) "
            "VALUES (:userid, :fieldid, :data)"
        ),
        {"userid": userid, "fieldid": fieldid, "data": account_number},
    )


def insert_course(
    connection: Connection,
    *,
    fullname: str,
    shortname: str | None = None,
    visible: int = 1,
    timemodified: int = 0,
) -> int:
    return connection.execute(
        text("""
            INSERT INTO mdl_course (fullname, shortname, visible, timemodified)
            VALUES (:fullname, :shortname, :visible, :timemodified)
            RETURNING id
        """),
        {
            "fullname": fullname,
            "shortname": shortname,
            "visible": visible,
            "timemodified": timemodified,
        },
    ).scalar_one()


def insert_enrol(connection: Connection, *, courseid: int, status: int = 0) -> int:
    return connection.execute(
        text("INSERT INTO mdl_enrol (courseid, status) VALUES (:courseid, :status) RETURNING id"),
        {"courseid": courseid, "status": status},
    ).scalar_one()


def insert_user_enrolment(
    connection: Connection, *, enrolid: int, userid: int, status: int = 0, timemodified: int = 0
) -> int:
    return connection.execute(
        text("""
            INSERT INTO mdl_user_enrolments (enrolid, userid, status, timemodified)
            VALUES (:enrolid, :userid, :status, :timemodified)
            RETURNING id
        """),
        {"enrolid": enrolid, "userid": userid, "status": status, "timemodified": timemodified},
    ).scalar_one()


def update_user_lastname(connection: Connection, userid: int, lastname: str) -> None:
    connection.execute(
        text("UPDATE mdl_user SET lastname = :lastname WHERE id = :id"),
        {"lastname": lastname, "id": userid},
    )


def update_course_fullname(connection: Connection, courseid: int, fullname: str) -> None:
    connection.execute(
        text("UPDATE mdl_course SET fullname = :fullname WHERE id = :id"),
        {"fullname": fullname, "id": courseid},
    )


def insert_grade_item(
    connection: Connection,
    *,
    courseid: int,
    itemtype: str = "mod",
    itemmodule: str | None = "assign",
    itemname: str | None = "Tarea 01",
    grademax: float = 100,
    hidden: int = 0,
    timemodified: int = 0,
) -> int:
    return connection.execute(
        text("""
            INSERT INTO mdl_grade_items
                (courseid, itemtype, itemmodule, itemname, grademax, hidden, timemodified)
            VALUES (:courseid, :itemtype, :itemmodule, :itemname, :grademax, :hidden, :timemodified)
            RETURNING id
        """),
        {
            "courseid": courseid,
            "itemtype": itemtype,
            "itemmodule": itemmodule,
            "itemname": itemname,
            "grademax": grademax,
            "hidden": hidden,
            "timemodified": timemodified,
        },
    ).scalar_one()


def insert_grade_grade(
    connection: Connection,
    *,
    itemid: int,
    userid: int,
    finalgrade: float | None,
    hidden: int = 0,
    timemodified: int = 0,
) -> int:
    return connection.execute(
        text("""
            INSERT INTO mdl_grade_grades (itemid, userid, finalgrade, hidden, timemodified)
            VALUES (:itemid, :userid, :finalgrade, :hidden, :timemodified)
            RETURNING id
        """),
        {
            "itemid": itemid,
            "userid": userid,
            "finalgrade": finalgrade,
            "hidden": hidden,
            "timemodified": timemodified,
        },
    ).scalar_one()


def update_grade_item_name(connection: Connection, itemid: int, itemname: str) -> None:
    connection.execute(
        text("UPDATE mdl_grade_items SET itemname = :itemname WHERE id = :id"),
        {"itemname": itemname, "id": itemid},
    )


def update_grade_grade_finalgrade(
    connection: Connection, gradeid: int, finalgrade: float | None
) -> None:
    connection.execute(
        text("UPDATE mdl_grade_grades SET finalgrade = :finalgrade WHERE id = :id"),
        {"finalgrade": finalgrade, "id": gradeid},
    )


def enroll_student(
    connection: Connection,
    *,
    userid: int,
    courseid: int,
    enrol_status: int = 0,
    enrolment_status: int = 0,
) -> int:
    """Enrolls an existing user in an existing course via one enrol method.

    Returns the mdl_user_enrolments.id — the stable source identity used
    for raw_moodle.enrollments.source_id.
    """
    enrolid = insert_enrol(connection, courseid=courseid, status=enrol_status)
    return insert_user_enrolment(
        connection, enrolid=enrolid, userid=userid, status=enrolment_status
    )
