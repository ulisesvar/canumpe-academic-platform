"""The `issue-bot` provisioning command (see app.auth.manage_api_keys), and
that the pre-existing commands keep working alongside it.
"""

import pytest
from sqlalchemy import Engine, select

from app.auth.api_keys import hash_key
from app.auth.manage_api_keys import main
from app.auth.models import ROLE_BOT, ApiKey
from tests.api.helpers import create_course, create_student


def _run(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["manage_api_keys", *args])
    return main()


def test_issue_bot_stores_only_the_hash_with_role_and_course(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], db_engine: Engine
) -> None:
    course_id = create_course(db_engine)

    exit_code = _run(
        monkeypatch, "issue-bot", "--course-id", str(course_id), "--label", "telegram-bot"
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    plaintext = next(line for line in out.splitlines() if line.startswith("canumpe_bot_"))
    with db_engine.connect() as connection:
        row = connection.execute(select(ApiKey)).one()
    assert row.role == ROLE_BOT
    assert row.course_id == course_id
    assert row.student_id is None
    assert row.key_hash == hash_key(plaintext)
    assert plaintext not in {row.key_hash, row.key_prefix}
    assert row.label == "telegram-bot"


def test_issue_bot_for_a_nonexistent_course_fails_and_creates_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], db_engine: Engine
) -> None:
    exit_code = _run(monkeypatch, "issue-bot", "--course-id", "999999")

    assert exit_code == 1
    captured = capsys.readouterr()
    assert "999999" in captured.err
    assert "canumpe_bot_" not in captured.out
    with db_engine.connect() as connection:
        assert connection.execute(select(ApiKey)).first() is None


def test_issue_bot_requires_a_course_id(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, "issue-bot")

    assert excinfo.value.code == 2


def test_list_shows_the_bot_key_course_and_never_a_plaintext_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], db_engine: Engine
) -> None:
    course_id = create_course(db_engine)
    _run(monkeypatch, "issue-bot", "--course-id", str(course_id))
    plaintext = next(
        line for line in capsys.readouterr().out.splitlines() if line.startswith("canumpe_bot_")
    )

    _run(monkeypatch, "list")

    listing = capsys.readouterr().out
    assert "role=bot" in listing
    assert f"course_id={course_id}" in listing
    assert plaintext not in listing
    assert hash_key(plaintext) not in listing


def test_existing_commands_still_work_alongside_issue_bot(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], db_engine: Engine
) -> None:
    create_student(db_engine, account_number="80001")
    course_id = create_course(db_engine)

    assert _run(monkeypatch, "issue-student", "--account-number", "80001") == 0
    assert _run(monkeypatch, "rotate-student", "--account-number", "80001") == 0
    assert _run(monkeypatch, "issue-admin", "--label", "x") == 0
    assert _run(monkeypatch, "issue-bot", "--course-id", str(course_id)) == 0
    capsys.readouterr()
    assert _run(monkeypatch, "revoke", "--id", "1") == 0
    assert _run(monkeypatch, "list") == 0
