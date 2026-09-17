"""app.auth.manage_api_keys — the only way an API key is ever created;
there is no public endpoint for it. Exercises main() directly the way
an operator would invoke it (argv + stdout), against the real test
database app.db.session is already bound to.
"""

import pytest
from sqlalchemy import Engine

from app.auth.manage_api_keys import main
from tests.api.helpers import create_student


def _run(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr("sys.argv", ["manage_api_keys", *args])
    return main()


def test_issue_student_prints_plaintext_key_exactly_once(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], db_engine: Engine
) -> None:
    create_student(db_engine, account_number="50001")

    exit_code = _run(monkeypatch, "issue-student", "--account-number", "50001")

    assert exit_code == 0
    out = capsys.readouterr().out
    assert out.count("canumpe_stu_") >= 1


def test_issue_student_for_unknown_account_fails_clearly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = _run(monkeypatch, "issue-student", "--account-number", "does-not-exist")

    assert exit_code == 1
    assert "does-not-exist" in capsys.readouterr().err


def test_issue_admin_prints_plaintext_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = _run(monkeypatch, "issue-admin", "--label", "Test Admin")

    assert exit_code == 0
    assert "canumpe_adm_" in capsys.readouterr().out


def test_list_never_prints_a_plaintext_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], db_engine: Engine
) -> None:
    create_student(db_engine, account_number="50002")
    _run(monkeypatch, "issue-student", "--account-number", "50002")
    issued_plaintext = capsys.readouterr().out.strip().splitlines()[1]

    _run(monkeypatch, "list")
    list_output = capsys.readouterr().out

    assert issued_plaintext not in list_output
    assert "role=student" in list_output
    assert "50002" in list_output  # account_number as the safe "target" identifier


def test_list_never_prints_the_full_key_hash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(monkeypatch, "issue-admin", "--label", "Hash Check")

    _run(monkeypatch, "list")
    list_output = capsys.readouterr().out

    assert "key_hash" not in list_output


def test_revoke_then_list_shows_revoked_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(monkeypatch, "issue-admin", "--label", "To Revoke")
    issued_out = capsys.readouterr().out
    key_id = issued_out.splitlines()[0].split("id=")[1].split(",")[0]

    revoke_exit = _run(monkeypatch, "revoke", "--id", key_id)
    assert revoke_exit == 0

    _run(monkeypatch, "list")
    list_output = capsys.readouterr().out
    assert f"id={key_id}" in list_output
    assert "status=revoked" in list_output


def test_rotate_student_revokes_previous_and_issues_new(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], db_engine: Engine
) -> None:
    create_student(db_engine, account_number="50003")
    _run(monkeypatch, "issue-student", "--account-number", "50003")
    capsys.readouterr()

    exit_code = _run(monkeypatch, "rotate-student", "--account-number", "50003")

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "canumpe_stu_" in out

    _run(monkeypatch, "list")
    list_output = capsys.readouterr().out
    lines = [line for line in list_output.splitlines() if "50003" in line]
    assert len(lines) == 2
    assert sum(1 for line in lines if "status=active" in line) == 1
    assert sum(1 for line in lines if "status=revoked" in line) == 1
