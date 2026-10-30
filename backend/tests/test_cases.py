"""Offline tests for Farm Problem Case Management and linked FarmActions."""
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import backend.main as service


class FakeGroq:
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    content=(
                        "Possible explanations include several environmental or crop-care factors; "
                        "this is not a confirmed diagnosis. Check the affected and unaffected plants, "
                        "record changes, and contact an agricultural extension officer if the problem spreads."
                    )
                ))])


client = TestClient(service.app)


def setup_function():
    service.DB_PATH = Path(tempfile.gettempdir()) / "shambasense_test_cases.db"
    if service.DB_PATH.exists():
        service.DB_PATH.unlink()
    service.init_db()
    service.client = FakeGroq()


def teardown_function():
    if service.DB_PATH.exists():
        service.DB_PATH.unlink()


def create_case():
    response = client.post("/cases", json={
        "crop": "Maize",
        "title": "Yellowing leaves in two rows",
        "problem": "Several maize plants have yellowing leaves, especially on the lower part of the plants.",
        "symptoms": "Older leaves appear pale; no clear spots observed.",
        "onset_date": "2026-10-25",
        "crop_stage": "Vegetative",
        "notes": "The farmer noticed the change after a period of rain."
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_case_create_and_detail_have_reference_and_empty_timeline():
    created = create_case()
    assert created["case_ref"].startswith("SS-")
    assert created["status"] == "open"
    assert created["observations"] == []
    assert created["assessments"] == []
    assert created["actions"] == []
    assert created["events"][0]["event_type"] == "created"
    detail = client.get(f"/cases/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["title"] == "Yellowing leaves in two rows"


def test_case_validation_and_not_found_responses():
    assert client.post("/cases", json={"crop": "M", "title": "No", "problem": "x"}).status_code == 422
    assert client.get("/cases/987654").status_code == 404
    assert client.post("/cases/987654/observations", json={"observation": "New leaves look different"}).status_code == 404


def test_observations_and_status_updates_are_saved():
    case = create_case()
    observed = client.post(f"/cases/{case['id']}/observations", json={
        "observation": "Three more plants show the same yellowing today.",
        "observed_at": "2026-10-30T08:00:00+03:00"
    })
    assert observed.status_code == 200
    assert len(observed.json()["observations"]) == 1
    changed = client.patch(f"/cases/{case['id']}/status", json={"status": "monitoring"})
    assert changed.status_code == 200
    assert changed.json()["status"] == "monitoring"
    assert any(event["event_type"] == "status_changed" for event in changed.json()["events"])
    assert any(event["event_type"] == "observation" for event in changed.json()["events"])
    assert client.patch(f"/cases/{case['id']}/status", json={"status": "unknown"}).status_code == 422


def test_case_assessment_is_saved_and_returned():
    case = create_case()
    response = client.post(f"/cases/{case['id']}/assessments", json={"language": "English"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["assessments"]) == 1
    assert "not a confirmed diagnosis" in result["assessments"][0]["assessment"]
    assert result["assessments"][0]["sources"]
    assert any("KALRO" in source["title"] for source in result["assessments"][0]["sources"])


def test_farmer_approved_action_is_linked_to_case_and_existing_reminder_list():
    case = create_case()
    response = client.post(f"/cases/{case['id']}/actions", json={
        "title": "Inspect affected maize plants",
        "due_at": "2026-10-31T08:00:00+03:00",
        "notes": "Compare the newest and older leaves."
    })
    assert response.status_code == 200
    action = response.json()["action"]
    assert action["case_id"] == case["id"]
    reminders = client.get("/reminders").json()
    assert len(reminders) == 1
    assert reminders[0]["case_ref"] == case["case_ref"]
    assert reminders[0]["case_title"] == case["title"]


def test_existing_reminder_without_case_remains_supported():
    response = client.post("/reminders", json={
        "title": "Check irrigation",
        "due_at": "2026-11-01T09:00:00+03:00"
    })
    assert response.status_code == 200
    assert response.json()["case_id"] is None
    rows = client.get("/reminders").json()
    assert rows[0]["title"] == "Check irrigation"
    assert rows[0]["case_ref"] is None


def test_additive_migration_preserves_old_reminders_table():
    # Simulate a database created by the earlier project release.
    legacy_path = Path(tempfile.gettempdir()) / "shambasense_legacy_migration.db"
    if legacy_path.exists():
        legacy_path.unlink()
    legacy = sqlite3.connect(legacy_path)
    legacy.execute("CREATE TABLE reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, due_at TEXT NOT NULL, notes TEXT, completed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)")
    legacy.execute("INSERT INTO reminders(title,due_at,created_at) VALUES('Old task','2026-11-01T09:00:00+03:00','2026-10-20T00:00:00+00:00')")
    legacy.commit()
    legacy.close()

    previous_path = service.DB_PATH
    try:
        service.DB_PATH = legacy_path
        service.init_db()
        with service.db() as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(reminders)").fetchall()}
            old_row = conn.execute("SELECT title,case_id FROM reminders WHERE id=1").fetchone()
        assert "case_id" in columns
        assert old_row["title"] == "Old task"
        assert old_row["case_id"] is None
    finally:
        service.DB_PATH = previous_path
        if legacy_path.exists():
            legacy_path.unlink()
