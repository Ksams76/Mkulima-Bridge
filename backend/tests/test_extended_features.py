"""Offline regression tests for the added workspace modules."""
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import backend.main as service

client = TestClient(service.app)

class FakeGroq:
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="This is a cautious sample assessment."))])


def setup_function():
    service.DB_PATH = Path(tempfile.gettempdir()) / "shambasense_test_extended.db"
    if service.DB_PATH.exists(): service.DB_PATH.unlink()
    community_path = service.DB_PATH.with_name(f"{service.DB_PATH.stem}_community.sqlite3")
    if community_path.exists(): community_path.unlink()
    service.init_db()
    service.client = FakeGroq()
    os.environ.pop("SUPERVISOR_ACCESS_TOKEN", None)


def teardown_function():
    if service.DB_PATH.exists(): service.DB_PATH.unlink()
    community_path = service.DB_PATH.with_name(f"{service.DB_PATH.stem}_community.sqlite3")
    if community_path.exists(): community_path.unlink()
    os.environ.pop("SUPERVISOR_ACCESS_TOKEN", None)


def make_case():
    response = client.post("/cases", json={
        "crop": "Maize", "title": "Yellowing lower leaves",
        "problem": "Several plants show yellowing on lower leaves."
    })
    assert response.status_code == 200
    return response.json()


def test_workspace_summary_returns_metrics_and_case_list():
    case = make_case()
    assert client.post("/reminders", json={"title":"Inspect field","due_at":"2026-11-01T08:00:00+03:00"}).status_code == 200
    data = client.get("/dashboard/summary").json()
    assert data["open_cases"] == 1
    assert data["pending_actions"] == 1
    assert data["recent_cases"][0]["case_ref"] == case["case_ref"]
    assert data["scope"] == "private account workspace (local SQLite prototype)"


def test_learning_modules_and_practice_scoring_are_persisted():
    modules = client.get("/learning/modules").json()
    assert len(modules) >= 3
    first = modules[0]
    answers = [q["options"].index(["Observe and record what is happening", "To compare patterns across the plot", "Date, crop stage and observed signs"][i]) for i, q in enumerate(first["quiz"])]
    result = client.post("/learning/sessions", json={"module_id":first["id"], "answers":answers})
    assert result.status_code == 200, result.text
    assert result.json()["score"] == 3
    progress = client.get("/learning/progress").json()
    assert progress["sessions"] == 1
    assert progress["best_percent"] == 100


def test_learning_rejects_invalid_module_and_missing_answers():
    assert client.post("/learning/sessions", json={"module_id":"unknown","answers":[0]}).status_code == 404
    assert client.post("/learning/sessions", json={"module_id":"field-scouting","answers":[0]}).status_code == 422


def test_community_reports_require_consent_and_suppress_small_groups():
    base = {"crop":"Maize","county":"Kiambu","category":"Leaf discolouration","consent":True}
    assert client.post("/community/reports", json={**base,"consent":False}).status_code == 400
    for _ in range(2):
        assert client.post("/community/reports", json=base).status_code == 200
    assert client.get("/community/pulse").json()["groups"] == []
    assert client.post("/community/reports", json=base).status_code == 200
    pulse = client.get("/community/pulse").json()
    assert pulse["groups"][0]["report_count"] == 3
    assert "not independently verified" in pulse["groups"][0]["evidence_label"]


def test_expert_referral_prepares_but_does_not_send_summary():
    case = make_case()
    response = client.post(f"/cases/{case['id']}/referrals")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "prepared"
    assert "has not been sent" in data["message"]
    assert case["case_ref"] in data["summary"]
    assert client.patch(f"/referrals/{data['id']}", json={"status":"shared_by_farmer","expert_name":"Extension officer"}).json()["status"] == "shared_by_farmer"


def test_inventory_add_update_low_stock_and_delete():
    created = client.post("/inventory", json={"name":"Maize seed","category":"Seed","unit":"kg","quantity":2,"reorder_level":5})
    assert created.status_code == 200 and created.json()["low_stock"] is True
    item_id = created.json()["id"]
    updated = client.patch(f"/inventory/{item_id}", json={"quantity":10})
    assert updated.status_code == 200 and updated.json()["low_stock"] is False
    assert client.delete(f"/inventory/{item_id}").status_code == 200
    assert client.get("/inventory").json() == []


def test_supervisor_overview_is_disabled_without_server_token_and_protected_with_it():
    assert client.get("/supervisor/overview").status_code == 503
    os.environ["SUPERVISOR_ACCESS_TOKEN"] = "test-secret-token"
    assert client.get("/supervisor/overview").status_code == 403
    response = client.get("/supervisor/overview", headers={"X-Supervisor-Token":"test-secret-token"})
    assert response.status_code == 200
    assert "only the signed-in account workspace" in response.json()["note"]


def test_demo_mode_returns_scripted_answer_without_provider_call():
    service.DEMO_MODE = True
    try:
        result = client.post("/ask", json={"question":"My maize leaves are yellowing", "language":"English"})
        assert result.status_code == 200
        assert result.json()["demo_mode"] is True
        assert "demo response" in result.json()["answer"].lower()
        assert client.get("/health").json()["demo_mode"] is True
    finally:
        service.DEMO_MODE = False


def test_demo_case_assessment_is_marked_and_saved_without_provider():
    case = make_case()
    service.DEMO_MODE = True
    try:
        service.client = None
        result = client.post(f"/cases/{case['id']}/assessments", json={"language":"English"})
        assert result.status_code == 200
        assert "DEMO ASSESSMENT" in result.json()["assessments"][0]["assessment"]
        assert any(event["event_type"] == "assessment_created" for event in result.json()["events"])
    finally:
        service.DEMO_MODE = False
        service.client = FakeGroq()


def test_linked_action_completion_is_added_to_case_activity_timeline():
    case = make_case()
    response = client.post(f"/cases/{case['id']}/actions", json={
        "title":"Inspect affected rows again", "due_at":"2026-11-01T08:00:00+03:00"
    })
    assert response.status_code == 200
    reminder_id = response.json()["action"]["id"]
    complete = client.patch(f"/reminders/{reminder_id}/complete")
    assert complete.status_code == 200 and complete.json()["completed"] == 1
    detail = client.get(f"/cases/{case['id']}").json()
    assert any(event["event_type"] == "action_updated" for event in detail["events"])
