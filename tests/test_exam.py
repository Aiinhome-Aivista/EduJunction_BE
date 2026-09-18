import uuid

def _generate_exam(client, headers, student_id, **overrides):
    payload = {
        "studentId": student_id, "board": "CBSE", "classGrade": "Class 10",
        "subject": "Mathematics", "difficulty": "medium",
    }
    payload.update(overrides)
    return client.post("/api/v1/exams/generate", json=payload, headers=headers)


def test_generate_exam_returns_ten_questions_without_answers(client, registered_parent, child):
    res = _generate_exam(client, registered_parent["headers"], child["id"])
    assert res.status_code == 201
    exam = res.get_json()["data"]["exam"]
    assert exam["questionCount"] == 10
    assert len(exam["questions"]) == 10
    # Check keys specifically (not a raw substring search) — one of the
    # fallback bank's own MCQ option strings legitimately contains the word
    # "explanation" ("...is the correct explanation of A"), which a naive
    # substring check would misflag.
    for q in exam["questions"]:
        assert "correctAnswer" not in q
        assert "explanation" not in q


def test_generate_exam_for_someone_elses_child_forbidden(client, registered_parent, child):
    other = client.post(
        "/api/v1/auth/register",
        json={"name": "Other", "username": f"other_{uuid.uuid4().hex[:6]}", "email": f"other-{uuid.uuid4().hex[:6]}@test.com", "password": "Passw0rd!"},
    ).get_json()["data"]
    other_headers = {"Authorization": f"Bearer {other['accessToken']}"}

    res = _generate_exam(client, other_headers, child["id"])
    assert res.status_code in (403, 404)


def test_submit_exam_computes_score_and_returns_analysis(client, registered_parent, child):
    exam = _generate_exam(client, registered_parent["headers"], child["id"]).get_json()["data"]["exam"]
    answers = {q["id"]: "A" for q in exam["questions"]}

    res = client.post(
        f"/api/v1/exams/{exam['id']}/submit",
        json={"answers": answers, "timeTakenSeconds": 200},
        headers=registered_parent["headers"],
    )
    assert res.status_code == 200
    body = res.get_json()["data"]
    submission = body["submission"]
    assert submission["totalMarks"] in (10, 15)
    assert 0 <= submission["marksObtained"] <= submission["totalMarks"]
    assert "analysis" in submission and "evaluations" in submission
    assert len(submission["evaluations"]) == 10
    assert body["xpEarned"] > 0
    assert "badge-pioneer" in body["newlyUnlockedBadges"]


def test_double_submit_rejected(client, registered_parent, child):
    exam = _generate_exam(client, registered_parent["headers"], child["id"]).get_json()["data"]["exam"]
    answers = {q["id"]: "A" for q in exam["questions"]}
    headers = registered_parent["headers"]

    first = client.post(f"/api/v1/exams/{exam['id']}/submit", json={"answers": answers}, headers=headers)
    assert first.status_code == 200
    second = client.post(f"/api/v1/exams/{exam['id']}/submit", json={"answers": answers}, headers=headers)
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "ALREADY_SUBMITTED"


def test_unlimited_exams_allowed(client, registered_parent, child):
    headers = registered_parent["headers"]
    first = _generate_exam(client, headers, child["id"])
    assert first.status_code == 201

    second = _generate_exam(client, headers, child["id"])
    assert second.status_code == 201


def test_submission_updates_child_stats_and_mastery(client, registered_parent, child):
    headers = registered_parent["headers"]
    exam = _generate_exam(client, headers, child["id"]).get_json()["data"]["exam"]
    answers = {q["id"]: "A" for q in exam["questions"]}
    client.post(f"/api/v1/exams/{exam['id']}/submit", json={"answers": answers}, headers=headers)

    overview = client.get(f"/api/v1/parents/me/children/{child['id']}/overview", headers=headers)
    assert overview.status_code == 200
    data = overview.get_json()["data"]
    assert data["child"]["totalExamsTaken"] == 1
    assert len(data["recentExams"]) == 1
    assert len(data["topicMastery"]) > 0
