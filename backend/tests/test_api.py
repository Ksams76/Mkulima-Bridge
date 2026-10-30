"""Fast, offline API tests; no live provider key or paid model call required."""
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
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Check drainage and inspect leaf undersides. This is not a confirmed diagnosis."))])

def setup_function():
    service.DB_PATH = Path(tempfile.gettempdir()) / "shambasense_test_api.db"
    if service.DB_PATH.exists(): service.DB_PATH.unlink()
    service.init_db()
    service.client = FakeGroq()


def teardown_function():
    if service.DB_PATH.exists(): service.DB_PATH.unlink()

client = TestClient(service.app)

def test_health_reports_api_and_db():
    response=client.get("/health")
    assert response.status_code==200
    assert response.json()["database"]=="sqlite"

def test_root_serves_frontend_and_assets():
    page=client.get("/")
    assert page.status_code==200
    assert "ShambaSense AI | Your Farming Assistant" in page.text
    assert client.get("/css/style.css").status_code==200
    assert client.get("/js/auth.js").status_code==200
    assert client.get("/js/app.js").status_code==200
    assert "auth-screen" in page.text and "profile-saved-card" in page.text
    assert client.get("/images/shambasense.jpeg").status_code==200
    assert client.get("/js/extended.js").status_code==200

def test_profile_round_trip():
    payload={"farmer_name":"Amina","county":"Kiambu","sub_county":"Thika","main_crop":"Maize","farm_size":"1.5"}
    assert client.put("/profile",json=payload).status_code==200
    assert client.get("/profile").json()["main_crop"]=="Maize"

def test_question_validation_and_history():
    assert client.post("/ask",json={"question":"x"}).status_code==422
    response=client.post("/ask",json={"question":"Maize leaves are yellowing","language":"English"})
    assert response.status_code==200
    assert "answer" in response.json()
    assert len(client.get("/history").json())==1

def test_reminder_create_complete_delete():
    created=client.post("/reminders",json={"title":"Inspect crop","due_at":"2026-11-01T09:00:00+03:00"})
    assert created.status_code==200
    rid=created.json()["id"]
    assert client.patch(f"/reminders/{rid}/complete").json()["completed"]==1
    assert client.delete(f"/reminders/{rid}").status_code==200
    assert client.delete(f"/reminders/{rid}").status_code==404

def test_knowledge_status_is_honest_when_corpus_empty():
    response=client.get("/knowledge/status")
    assert response.status_code==200
    assert response.json()["document_count"] >= 3
    assert response.json()["status"] == "ready"
