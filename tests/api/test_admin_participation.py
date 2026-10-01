"""HTTP-level tests for POST/GET/DELETE
/admin/courses/{course_id}/students/{student_id}/participation[...].
"""

from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select

from app.academic.models import ParticipationObservation
from tests.api.helpers import (
    create_course,
    create_enrollment,
    create_student,
    issue_test_admin_key,
    issue_test_student_key,
    revoke_test_key_by_plaintext,
)


def _enrolled(
    db_engine: Engine, account_number: str, course_id: int | None = None
) -> tuple[int, int]:
    """Returns (course_id, student_id) for a student enrolled in a course
    (a new one unless course_id is given).
    """
    student_id = create_student(db_engine, account_number=account_number)
    resolved_course_id = course_id if course_id is not None else create_course(db_engine)
    create_enrollment(db_engine, student_id=student_id, course_id=resolved_course_id)
    return resolved_course_id, student_id


def _url(course_id: int, student_id: int, observation_id: int | None = None) -> str:
    base = f"/admin/courses/{course_id}/students/{student_id}/participation"
    return base if observation_id is None else f"{base}/{observation_id}"


def _record(
    client: TestClient, headers: dict[str, str], course_id: int, student_id: int, value: int
):
    return client.post(_url(course_id, student_id), headers=headers, json={"value": value})


def _count_rows(db_engine: Engine) -> int:
    with db_engine.connect() as connection:
        return connection.execute(
            select(func.count()).select_from(ParticipationObservation)
        ).scalar_one()


# -- calculation through the API ----------------------------------------


def test_value_zero_is_valid_and_is_a_real_zero(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id, student_id = _enrolled(db_engine, "8201")

    response = _record(client, admin_headers, course_id, student_id, 0)

    assert response.status_code == 201
    body = response.json()
    assert body["value"] == 0
    assert body["participation_count"] == 1
    assert body["participation_average"] == 0.0
    assert body["participation_score_100"] == 0.0


def test_no_observations_yields_count_zero_and_zero_average_and_score(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id, student_id = _enrolled(db_engine, "8202")

    response = client.get(_url(course_id, student_id), headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {
        "student_id": student_id,
        "course_id": course_id,
        "observations": [],
        "participation_count": 0,
        "participation_average": 0.0,
        "participation_score_100": 0.0,
    }


def test_two_threes_average_three_and_score_100(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id, student_id = _enrolled(db_engine, "8203")
    _record(client, admin_headers, course_id, student_id, 3)
    _record(client, admin_headers, course_id, student_id, 3)

    body = client.get(_url(course_id, student_id), headers=admin_headers).json()

    assert body["participation_count"] == 2
    assert body["participation_average"] == 3.0
    assert body["participation_score_100"] == 100.0


def test_five_threes_and_two_threes_have_the_same_score(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id, five_id = _enrolled(db_engine, "8204")
    _, two_id = _enrolled(db_engine, "8205", course_id=course_id)
    for _ in range(5):
        _record(client, admin_headers, course_id, five_id, 3)
    for _ in range(2):
        _record(client, admin_headers, course_id, two_id, 3)

    five = client.get(_url(course_id, five_id), headers=admin_headers).json()
    two = client.get(_url(course_id, two_id), headers=admin_headers).json()

    assert five["participation_count"] == 5
    assert two["participation_count"] == 2
    assert five["participation_average"] == two["participation_average"] == 3.0
    assert five["participation_score_100"] == two["participation_score_100"] == 100.0


def test_three_two_three_three_averages_2_75_and_scores_91_67(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id, student_id = _enrolled(db_engine, "8206")
    for value in (3, 2, 3, 3):
        last = _record(client, admin_headers, course_id, student_id, value)

    assert last.json()["participation_average"] == 2.75
    assert last.json()["participation_score_100"] == 91.67
    body = client.get(_url(course_id, student_id), headers=admin_headers).json()
    assert body["participation_average"] == 2.75
    assert body["participation_score_100"] == 91.67


def test_multiple_observations_are_individually_persisted(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id, student_id = _enrolled(db_engine, "8207")
    ids = [
        _record(client, admin_headers, course_id, student_id, value).json()["observation_id"]
        for value in (3, 2, 3, 3)
    ]

    body = client.get(_url(course_id, student_id), headers=admin_headers).json()

    assert len(set(ids)) == 4
    assert [o["observation_id"] for o in body["observations"]] == ids
    assert [o["value"] for o in body["observations"]] == [3, 2, 3, 3]
    assert _count_rows(db_engine) == 4


def test_observed_at_defaults_to_now_and_can_be_supplied(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id, student_id = _enrolled(db_engine, "8208")

    defaulted = _record(client, admin_headers, course_id, student_id, 1)
    supplied = client.post(
        _url(course_id, student_id),
        headers=admin_headers,
        json={"value": 2, "observed_at": "2026-03-01T09:00:00+00:00"},
    )

    assert defaulted.json()["observed_at"] is not None
    assert supplied.status_code == 201
    assert supplied.json()["observed_at"].startswith("2026-03-01T09:00:00")


# -- validation ---------------------------------------------------------


def test_out_of_range_values_are_rejected(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id, student_id = _enrolled(db_engine, "8209")

    for bad_value in (-1, 4):
        response = _record(client, admin_headers, course_id, student_id, bad_value)
        assert response.status_code == 422

    assert _count_rows(db_engine) == 0


def test_non_integer_values_and_naive_datetimes_are_rejected(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id, student_id = _enrolled(db_engine, "8210")
    url = _url(course_id, student_id)

    assert client.post(url, headers=admin_headers, json={"value": True}).status_code == 422
    assert client.post(url, headers=admin_headers, json={"value": "3"}).status_code == 422
    assert client.post(url, headers=admin_headers, json={"value": 2.5}).status_code == 422
    assert client.post(url, headers=admin_headers, json={}).status_code == 422
    assert (
        client.post(
            url, headers=admin_headers, json={"value": 3, "observed_at": "2026-03-01T09:00:00"}
        ).status_code
        == 422
    )
    assert _count_rows(db_engine) == 0


# -- enrollment / existence ---------------------------------------------


def test_cannot_record_for_a_student_not_enrolled_in_the_course(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id = create_course(db_engine)
    student_id = create_student(db_engine, account_number="8211")

    response = _record(client, admin_headers, course_id, student_id, 3)

    assert response.status_code == 404
    assert response.json() == {"detail": "Student not enrolled in course"}
    assert _count_rows(db_engine) == 0


def test_cannot_record_in_a_course_the_student_is_not_enrolled_in_even_if_enrolled_elsewhere(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    _, student_id = _enrolled(db_engine, "8212")
    other_course_id = create_course(db_engine, name="Other")

    response = _record(client, admin_headers, other_course_id, student_id, 3)

    assert response.status_code == 404
    assert _count_rows(db_engine) == 0


def test_unknown_course_and_student_return_404(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id, student_id = _enrolled(db_engine, "8213")

    unknown_course = _record(client, admin_headers, 999_999, student_id, 3)
    unknown_student = _record(client, admin_headers, course_id, 999_999, 3)

    assert unknown_course.status_code == 404
    assert unknown_course.json() == {"detail": "Course not found"}
    assert unknown_student.status_code == 404
    assert unknown_student.json() == {"detail": "Student not found"}
    assert client.get(_url(course_id, 999_999), headers=admin_headers).status_code == 404
    assert client.get(_url(999_999, student_id), headers=admin_headers).status_code == 404


def test_get_for_an_unenrolled_student_returns_404(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id = create_course(db_engine)
    student_id = create_student(db_engine, account_number="8214")

    assert client.get(_url(course_id, student_id), headers=admin_headers).status_code == 404


# -- delete -------------------------------------------------------------


def test_delete_removes_only_the_requested_observation_and_recalculates(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id, student_id = _enrolled(db_engine, "8215")
    ids = [
        _record(client, admin_headers, course_id, student_id, value).json()["observation_id"]
        for value in (3, 2, 3, 3)
    ]

    response = client.delete(_url(course_id, student_id, ids[1]), headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {
        "student_id": student_id,
        "course_id": course_id,
        "participation_count": 3,
        "participation_average": 3.0,
        "participation_score_100": 100.0,
    }
    remaining = client.get(_url(course_id, student_id), headers=admin_headers).json()
    assert [o["observation_id"] for o in remaining["observations"]] == [ids[0], ids[2], ids[3]]
    assert _count_rows(db_engine) == 3


def test_deleting_the_final_observation_returns_count_zero_and_zero_average_and_score(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id, student_id = _enrolled(db_engine, "8216")
    observation_id = _record(client, admin_headers, course_id, student_id, 2).json()[
        "observation_id"
    ]

    response = client.delete(_url(course_id, student_id, observation_id), headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {
        "student_id": student_id,
        "course_id": course_id,
        "participation_count": 0,
        "participation_average": 0.0,
        "participation_score_100": 0.0,
    }
    assert _count_rows(db_engine) == 0


def test_delete_cannot_remove_another_students_or_courses_observation(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id, student_id = _enrolled(db_engine, "8217")
    _, other_student_id = _enrolled(db_engine, "8218", course_id=course_id)
    other_course_id = create_course(db_engine, name="Other")
    create_enrollment(db_engine, student_id=student_id, course_id=other_course_id)
    target_id = _record(client, admin_headers, course_id, student_id, 3).json()["observation_id"]

    wrong_student = client.delete(
        _url(course_id, other_student_id, target_id), headers=admin_headers
    )
    wrong_course = client.delete(
        _url(other_course_id, student_id, target_id), headers=admin_headers
    )
    nonexistent = client.delete(_url(course_id, student_id, 999_999), headers=admin_headers)

    assert wrong_student.status_code == wrong_course.status_code == nonexistent.status_code == 404
    assert wrong_student.json() == wrong_course.json() == nonexistent.json()
    assert wrong_student.json() == {"detail": "Participation observation not found"}
    assert _count_rows(db_engine) == 1


def test_delete_twice_returns_404_the_second_time(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id, student_id = _enrolled(db_engine, "8220")
    observation_id = _record(client, admin_headers, course_id, student_id, 1).json()[
        "observation_id"
    ]

    first = client.delete(_url(course_id, student_id, observation_id), headers=admin_headers)
    second = client.delete(_url(course_id, student_id, observation_id), headers=admin_headers)

    assert first.status_code == 200
    assert second.status_code == 404


# -- authorization ------------------------------------------------------


def test_admin_key_is_recorded_on_the_observation(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id, student_id = _enrolled(db_engine, "8221")
    _record(client, admin_headers, course_id, student_id, 3)

    with db_engine.connect() as connection:
        recorded_by = connection.execute(
            select(ParticipationObservation.recorded_by_api_key_id)
        ).scalar_one()

    assert recorded_by is not None


def test_student_key_gets_403_on_every_participation_route(
    client: TestClient, db_engine: Engine
) -> None:
    course_id, student_id = _enrolled(db_engine, "8222")
    admin_key = issue_test_admin_key(db_engine)
    observation_id = _record(client, {"X-API-Key": admin_key}, course_id, student_id, 3).json()[
        "observation_id"
    ]
    student_headers = {"X-API-Key": issue_test_student_key(db_engine, account_number="8222")}

    post = client.post(_url(course_id, student_id), headers=student_headers, json={"value": 3})
    get = client.get(_url(course_id, student_id), headers=student_headers)
    delete = client.delete(_url(course_id, student_id, observation_id), headers=student_headers)

    for response in (post, get, delete):
        assert response.status_code == 403
        assert response.json() == {"detail": "Admin API key required"}
    assert _count_rows(db_engine) == 1


def test_missing_invalid_and_revoked_keys_return_401_on_every_participation_route(
    client: TestClient, db_engine: Engine
) -> None:
    course_id, student_id = _enrolled(db_engine, "8223")
    revoked_key = issue_test_admin_key(db_engine)
    revoke_test_key_by_plaintext(db_engine, revoked_key)

    for headers in ({}, {"X-API-Key": "bogus"}, {"X-API-Key": revoked_key}):
        assert (
            client.post(_url(course_id, student_id), headers=headers, json={"value": 3}).status_code
            == 401
        )
        assert client.get(_url(course_id, student_id), headers=headers).status_code == 401
        assert client.delete(_url(course_id, student_id, 1), headers=headers).status_code == 401
    assert _count_rows(db_engine) == 0


def test_participation_routes_exist_only_under_admin(
    client: TestClient, db_engine: Engine, admin_headers: dict[str, str]
) -> None:
    course_id, student_id = _enrolled(db_engine, "8224")
    student_headers = {"X-API-Key": issue_test_student_key(db_engine, account_number="8224")}

    assert (
        client.get(f"/students/{student_id}/participation", headers=admin_headers).status_code
        == 404
    )
    assert client.get("/me/participation", headers=student_headers).status_code == 404
    assert (
        client.get(f"/courses/{course_id}/participation", headers=admin_headers).status_code == 404
    )
