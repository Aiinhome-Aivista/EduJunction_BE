"""Shared pytest fixtures. Uses an isolated SQLite file per test session
(not MySQL) so the suite runs anywhere with zero external services —
Mistral and ArangoDB are also forced off so every AI call exercises the
deterministic fallback path, keeping tests hermetic and free."""
import os
import uuid

import pytest

os.environ["DATABASE_URL"] = "sqlite:///./test_pytest.db"
os.environ["JWT_SECRET_KEY"] = "pytest-secret"
os.environ["ARANGO_URL"] = ""
os.environ["MISTRAL_API_KEY"] = ""

from database.dbConnection import init_db, engine  # noqa: E402
import app as app_module  # noqa: E402
import seed_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _setup_database():
    init_db()
    seed_db.seed()
    yield
    engine.dispose()
    db_path = "./test_pytest.db"
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture()
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.fixture()
def registered_parent(client):
    uid = uuid.uuid4().hex[:8]
    email = f"parent-{uid}@test.com"
    username = f"parent_{uid}"
    res = client.post(
        "/api/v1/auth/register",
        json={"name": "Test Parent", "username": username, "email": email, "password": "Passw0rd!"},
    )
    assert res.status_code == 201, res.get_json()
    data = res.get_json()["data"]
    return {
        "email": email,
        "username": username,
        "accessToken": data["accessToken"],
        "refreshToken": data["refreshToken"],
        "userId": data["user"]["id"],
        "headers": {"Authorization": f"Bearer {data['accessToken']}"},
    }


@pytest.fixture()
def child(client, registered_parent):
    uid = uuid.uuid4().hex[:8]
    res = client.post(
        "/api/v1/parents/me/children",
        json={"name": "Test Child", "username": f"child_{uid}", "classGrade": "Class 10", "targetBoard": "CBSE", "password": "Passw0rdChild1!"},
        headers=registered_parent["headers"],
    )
    assert res.status_code == 201, res.get_json()
    return res.get_json()["data"]
