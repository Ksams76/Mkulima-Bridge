"""Regression tests for settings, livestock cases, community, inventory and media attachments."""
from pathlib import Path

from fastapi.testclient import TestClient

import backend.main as service


def register(client: TestClient, name: str, email: str, password: str = "strongfarm123"):
    response = client.post("/auth/register", json={"full_name": name, "email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["user"]


def configure_test_app(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "mkb.sqlite3")
    monkeypatch.setattr(service, "MEDIA_ROOT", tmp_path / "uploads")
    monkeypatch.setattr(service, "AUTH_REQUIRED", True)
    service._INITIALIZED_USER_DBS.clear()
    service.init_db()


def test_settings_are_saved_per_account_and_apply_ai_preferences(tmp_path, monkeypatch):
    configure_test_app(tmp_path, monkeypatch)
    with TestClient(service.app) as farmer_a:
        register(farmer_a, "Amina Wanjiru", "settings-a@example.com")
        defaults = farmer_a.get("/settings")
        assert defaults.status_code == 200
        assert defaults.json()["theme"] == "system"
        saved = farmer_a.put("/settings", json={"theme":"dark", "language":"Kiswahili", "farm_type":"livestock", "response_style":"simple", "save_ai_history":False})
        assert saved.status_code == 200, saved.text
        assert saved.json()["saved"] is True
        assert farmer_a.get("/settings").json()["theme"] == "dark"
        assert farmer_a.get("/settings").json()["save_ai_history"] is False

        with TestClient(service.app) as farmer_b:
            register(farmer_b, "Brian Mwangi", "settings-b@example.com")
            other = farmer_b.get("/settings").json()
            assert other["theme"] == "system"
            assert other["language"] == "English"
            assert other["save_ai_history"] is True

        # Account details can be changed, while the email stays fixed.
        updated = farmer_a.patch("/account", json={"full_name":"Amina Wanjiru Maina"})
        assert updated.status_code == 200
        assert farmer_a.get("/auth/me").json()["user"]["full_name"] == "Amina Wanjiru Maina"


def test_livestock_case_expert_categories_and_animal_safe_demo_assessment(tmp_path, monkeypatch):
    configure_test_app(tmp_path, monkeypatch)
    original_demo = service.DEMO_MODE
    try:
        service.DEMO_MODE = True
        with TestClient(service.app) as client:
            register(client, "John Farmer", "livestock@example.com")
            options = client.get("/livestock/options").json()
            assert "Cattle" in options["species"] and "Poultry" in options["species"]
            categories = client.get("/expert/categories?case_type=livestock").json()
            keys = {item["key"] for item in categories}
            assert "veterinary_health" in keys and "animal_nutrition" in keys
            assert "crop_protection" not in keys

            created = client.post("/cases", json={
                "case_type":"livestock", "species":"Goats", "animal_group":"Dairy goats",
                "animal_age_group":"Adult", "animal_count":2, "issue_category":"Reduced appetite or not eating",
                "title":"Two goats are eating less", "problem":"Two adult goats have reduced appetite since this morning."
            })
            assert created.status_code == 200, created.text
            case = created.json()
            assert case["case_type"] == "livestock" and case["species"] == "Goats"

            referral = client.post(f"/cases/{case['id']}/referrals", json={"expert_category":"veterinary_health", "urgency":"soon"})
            assert referral.status_code == 200, referral.text
            assert referral.json()["recommended_role"] == "Licensed veterinary professional"

            invalid_referral = client.post(f"/cases/{case['id']}/referrals", json={"expert_category":"crop_protection"})
            assert invalid_referral.status_code == 422

            assessed = client.post(f"/cases/{case['id']}/assessments", json={"language":"English"})
            assert assessed.status_code == 200
            text = assessed.json()["assessments"][0]["assessment"].lower()
            assert "not a veterinary diagnosis" in text and "veterinary professional" in text
    finally:
        service.DEMO_MODE = original_demo


def test_video_attachment_is_stored_and_isolated_between_accounts(tmp_path, monkeypatch):
    configure_test_app(tmp_path, monkeypatch)
    with TestClient(service.app) as farmer_a:
        register(farmer_a, "Video Farmer", "video-a@example.com")
        case = farmer_a.post("/cases", json={"crop":"Tomato", "title":"Leaf movement", "problem":"A short video records how leaves move in the wind."}).json()
        mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 24
        upload = farmer_a.post(f"/cases/{case['id']}/media/videos", files={"video":("farm-clip.mp4", mp4, "video/mp4")}, data={"description":"Short field clip"})
        assert upload.status_code == 200, upload.text
        media = upload.json()
        assert media["message"].startswith("Video attached")
        detail = farmer_a.get(f"/cases/{case['id']}").json()
        assert len(detail["media"]) == 1
        assert farmer_a.get(media["url"]).content == mp4

        with TestClient(service.app) as farmer_b:
            register(farmer_b, "Other Farmer", "video-b@example.com")
            assert farmer_b.get(media["url"]).status_code == 404
            assert farmer_b.get("/cases").json() == []

        deleted = farmer_a.delete(media["url"])
        assert deleted.status_code == 200
        assert farmer_a.get(media["url"]).status_code == 404


def test_inventory_updates_are_persistent_and_account_scoped(tmp_path, monkeypatch):
    configure_test_app(tmp_path, monkeypatch)
    with TestClient(service.app) as farmer_a:
        register(farmer_a, "Inventory Farmer", "stock-a@example.com")
        created = farmer_a.post("/inventory", json={"name":"Dairy meal", "category":"Animal feed", "unit":"kg", "quantity":25, "reorder_level":10})
        assert created.status_code == 200, created.text
        item_id = created.json()["id"]
        updated = farmer_a.patch(f"/inventory/{item_id}", json={"quantity":5, "notes":"Stored in dry room"})
        assert updated.status_code == 200
        assert updated.json()["low_stock"] is True
        listed = farmer_a.get("/inventory").json()
        assert len(listed) == 1 and listed[0]["quantity"] == 5

        with TestClient(service.app) as farmer_b:
            register(farmer_b, "Other Stock Farmer", "stock-b@example.com")
            assert farmer_b.get("/inventory").json() == []


def test_community_report_counter_updates_but_small_groups_stay_hidden(tmp_path, monkeypatch):
    configure_test_app(tmp_path, monkeypatch)
    with TestClient(service.app) as client:
        register(client, "Community Farmer", "pulse@example.com")
        payload = {"case_type":"livestock", "species":"Goats", "county":"Kiambu", "category":"Reduced appetite or not eating", "consent":True}
        one = client.post("/community/reports", json=payload)
        assert one.status_code == 200 and one.json()["trend_visible"] is False
        pulse_one = client.get("/community/pulse").json()
        assert pulse_one["total_reports"] == 1 and pulse_one["groups"] == []
        client.post("/community/reports", json=payload)
        third = client.post("/community/reports", json=payload).json()
        assert third["trend_visible"] is True
        pulse_three = client.get("/community/pulse").json()
        assert pulse_three["total_reports"] == 3
        assert pulse_three["groups"][0]["species"] == "Goats"


def test_ai_preferences_control_normal_question_history_and_answer_style(tmp_path, monkeypatch):
    from types import SimpleNamespace
    configure_test_app(tmp_path, monkeypatch)
    captured = {}

    class FakeCompletion:
        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Check several maize plants and record what you observe."))])

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletion()))
    monkeypatch.setattr(service, "client", fake_client)
    monkeypatch.setattr(service, "DEMO_MODE", False)
    with TestClient(service.app) as client:
        register(client, "AI Settings Farmer", "ai-settings@example.com")
        saved = client.put("/settings", json={"response_style":"simple", "save_ai_history":False})
        assert saved.status_code == 200
        answer = client.post("/ask", json={"question":"Why are my maize leaves yellow?", "language":"English"})
        assert answer.status_code == 200, answer.text
        assert client.get("/history").json() == []
        prompt = next(message["content"] for message in captured["messages"] if message["role"] == "user")
        assert "very simple language" in prompt
        client.put("/settings", json={"farm_type":"livestock", "save_ai_history":False})
        animal_answer = client.post("/ask", json={"question":"My goats have stopped eating. What should I observe?", "language":"English"})
        assert animal_answer.status_code == 200
        animal_prompt = next(message["content"] for message in captured["messages"] if message["role"] == "user")
        assert "not veterinary diagnosis" in animal_prompt
        assert "Do not prescribe veterinary medicines" in animal_prompt
        assert client.get("/history").json() == []


def test_expertconnect_case_list_includes_new_crop_and_livestock_cases(tmp_path, monkeypatch):
    """The chooser endpoint must expose both case types for the signed-in farmer."""
    configure_test_app(tmp_path, monkeypatch)
    with TestClient(service.app) as client:
        register(client, "ExpertConnect Farmer", "expertconnect-cases@example.com")
        crop = client.post("/cases", json={
            "crop": "Maize", "title": "Yellow lower leaves",
            "problem": "Several maize plants have yellowing lower leaves."
        })
        animal = client.post("/cases", json={
            "case_type": "livestock", "species": "Goats",
            "issue_category": "Reduced appetite or not eating",
            "title": "Goats eating less", "problem": "Two goats have reduced appetite."
        })
        assert crop.status_code == 200, crop.text
        assert animal.status_code == 200, animal.text

        listed = client.get("/cases?limit=100")
        assert listed.status_code == 200
        rows = listed.json()
        assert {row["id"] for row in rows} == {crop.json()["id"], animal.json()["id"]}
        assert {row["case_type"] for row in rows} == {"crop", "livestock"}

        crop_referral = client.post(
            f"/cases/{crop.json()['id']}/referrals",
            json={"expert_category": "crop_protection", "urgency": "routine"},
        )
        animal_referral = client.post(
            f"/cases/{animal.json()['id']}/referrals",
            json={"expert_category": "veterinary_health", "urgency": "soon"},
        )
        assert crop_referral.status_code == 200, crop_referral.text
        assert animal_referral.status_code == 200, animal_referral.text
        referrals = client.get("/referrals").json()
        assert {row["case_id"] for row in referrals} == {crop.json()["id"], animal.json()["id"]}


def test_async_form_handlers_do_not_reset_event_current_target_after_await():
    """Regression guard for the browser's null event.currentTarget after async awaits."""
    project_root = Path(__file__).resolve().parents[2]
    extended = (project_root / "frontend" / "js" / "extended.js").read_text(encoding="utf-8")
    app = (project_root / "frontend" / "js" / "app.js").read_text(encoding="utf-8")

    assert "event.currentTarget.reset()" not in extended
    assert "event.target.reset()" not in app
    assert "const form = event.currentTarget;" in extended
    assert "form.reset(); syncCommunityReportType();" in extended
    assert "form.reset(); $(\"inventory-unit\").value" in extended
    assert "const form=event.currentTarget;" in extended
    assert "form.reset(); window.location.reload();" in extended
    assert "const form=event.currentTarget;" in app
    assert "form.reset();alert(result.message);" in app
    assert "form.reset();\n    const updated = await api" in app


def test_expertconnect_case_chooser_refresh_is_wired_to_case_creation_and_navigation():
    """ExpertConnect should refresh when opened and whenever a new case is saved."""
    project_root = Path(__file__).resolve().parents[2]
    extended = (project_root / "frontend" / "js" / "extended.js").read_text(encoding="utf-8")
    app = (project_root / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
    markup = (project_root / "frontend" / "index.html").read_text(encoding="utf-8")

    assert 'id="refresh-referral-cases"' in markup
    assert 'id="referral-case-help"' in markup
    assert 'window.addEventListener("mkb:cases-updated", loadReferralCases)' in extended
    assert "data-view-link=\"expert-connect\"" in extended
    assert app.count('window.dispatchEvent(new CustomEvent("mkb:cases-updated"))') >= 2
