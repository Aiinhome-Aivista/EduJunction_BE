def test_public_runbook_list_returns_seeded_data(client):
    res = client.get("/api/v1/runbooks?board=CBSE")
    assert res.status_code == 200
    body = res.get_json()
    assert body["count"] >= 1
    assert all(rb["board"] == "CBSE" for rb in body["data"])


def test_runbook_create_requires_admin(client, registered_parent):
    res = client.post(
        "/api/v1/runbooks",
        json={"board": "CBSE", "classGrade": "Class 9", "subject": "Physics", "chapterName": "Test Chapter"},
        headers=registered_parent["headers"],
    )
    assert res.status_code == 403


def test_admin_can_create_update_delete_runbook(client):
    admin_login = client.post(
        "/api/v1/auth/login", json={"email": "admin@acugrade.ai", "password": "ChangeMe123!"}
    )
    assert admin_login.status_code == 200
    admin_headers = {"Authorization": f"Bearer {admin_login.get_json()['data']['accessToken']}"}

    created = client.post(
        "/api/v1/runbooks",
        json={
            "board": "CBSE", "classGrade": "Class 9", "subject": "Physics",
            "chapterName": "Pytest Chapter", "coreConcepts": ["concept A"],
        },
        headers=admin_headers,
    )
    assert created.status_code == 201
    runbook_id = created.get_json()["data"]["id"]

    updated = client.put(
        f"/api/v1/runbooks/{runbook_id}", json={"chapterName": "Pytest Chapter Updated"}, headers=admin_headers
    )
    assert updated.status_code == 200
    assert updated.get_json()["data"]["chapterName"] == "Pytest Chapter Updated"

    deleted = client.delete(f"/api/v1/runbooks/{runbook_id}", headers=admin_headers)
    assert deleted.status_code == 200

    missing = client.get(f"/api/v1/runbooks/{runbook_id}")
    assert missing.status_code == 404
