"""Authentication and per-account farm-profile isolation tests."""
from pathlib import Path
from fastapi.testclient import TestClient
import backend.main as service


def test_registration_login_logout_and_profile_isolation(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "app.sqlite3")
    monkeypatch.setattr(service, "AUTH_REQUIRED", True)
    service.init_db()

    with TestClient(service.app) as farmer_a:
        blocked = farmer_a.get("/profile")
        assert blocked.status_code == 401

        registered = farmer_a.post("/auth/register", json={
            "full_name": "Amina Wanjiru",
            "email": "AMINA@example.com",
            "password": "farmsecure123"
        })
        assert registered.status_code == 200, registered.text
        assert registered.json()["user"]["email"] == "amina@example.com"
        set_cookie = registered.headers.get("set-cookie", "").lower()
        assert "httponly" in set_cookie and "samesite=lax" in set_cookie

        saved = farmer_a.put("/profile", json={
            "farmer_name": "Amina Wanjiru", "county": "Kiambu", "sub_county": "Ruiru",
            "main_crop": "Maize", "farm_size": "1.5"
        })
        assert saved.status_code == 200, saved.text
        assert saved.json()["message"] == "Your farm profile has been saved successfully."
        assert saved.json()["profile"]["saved"] is True

        profile_a = farmer_a.get("/profile").json()
        assert profile_a["farmer_name"] == "Amina Wanjiru"
        assert profile_a["county"] == "Kiambu"
        case_a = farmer_a.post("/cases", json={
            "crop": "Maize", "title": "Yellowing leaves", "problem": "Several plants have yellowing lower leaves."
        })
        assert case_a.status_code == 200, case_a.text

        with TestClient(service.app) as farmer_b:
            registered_b = farmer_b.post("/auth/register", json={
                "full_name": "Brian Mwangi", "email": "brian@example.com", "password": "harvestsecure456"
            })
            assert registered_b.status_code == 200, registered_b.text
            profile_b = farmer_b.get("/profile")
            assert profile_b.status_code == 200
            assert profile_b.json()["saved"] is False
            assert profile_b.json()["farmer_name"] == ""
            assert farmer_b.get("/cases").json() == []
            assert farmer_b.get(f"/cases/{case_a.json()['id']}").status_code == 404

            saved_b = farmer_b.put("/profile", json={
                "farmer_name": "Brian Mwangi", "county": "Nakuru", "sub_county": "Naivasha",
                "main_crop": "Beans", "farm_size": "2"
            })
            assert saved_b.status_code == 200
            assert farmer_b.get("/profile").json()["county"] == "Nakuru"

        # Farmer A's profile remains unchanged after Farmer B created theirs.
        assert farmer_a.get("/profile").json()["county"] == "Kiambu"
        assert farmer_a.get("/cases").json()[0]["title"] == "Yellowing leaves"
        assert farmer_a.get("/auth/me").json()["user"]["full_name"] == "Amina Wanjiru"

        logout = farmer_a.post("/auth/logout")
        assert logout.status_code == 200
        assert farmer_a.get("/profile").status_code == 401
        login_again = farmer_a.post("/auth/login", json={"email":"amina@example.com", "password":"farmsecure123"})
        assert login_again.status_code == 200
        assert farmer_a.get("/profile").json()["county"] == "Kiambu"


def test_duplicate_email_and_password_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "app.sqlite3")
    monkeypatch.setattr(service, "AUTH_REQUIRED", True)
    service.init_db()
    with TestClient(service.app) as client:
        weak = client.post("/auth/register", json={"full_name":"Jane Farmer", "email":"jane@example.com", "password":"short"})
        assert weak.status_code == 422
        first = client.post("/auth/register", json={"full_name":"Jane Farmer", "email":"jane@example.com", "password":"strongpass123"})
        assert first.status_code == 200
        duplicate = client.post("/auth/register", json={"full_name":"Jane Farmer", "email":"JANE@example.com", "password":"anotherpass123"})
        assert duplicate.status_code == 409
        bad_login = client.post("/auth/login", json={"email":"jane@example.com", "password":"wrongpassword123"})
        assert bad_login.status_code == 401


def test_profile_requires_minimum_farm_details(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "app.sqlite3")
    monkeypatch.setattr(service, "AUTH_REQUIRED", True)
    service.init_db()
    with TestClient(service.app) as client:
        assert client.post("/auth/register", json={"full_name":"John Farmer", "email":"john@example.com", "password":"password12345"}).status_code == 200
        result = client.put("/profile", json={"farmer_name":"John", "county":"", "sub_county":"", "main_crop":"", "farm_size":""})
        assert result.status_code == 422


def test_cors_preflight_and_401_work_for_live_server_origin(tmp_path, monkeypatch):
    """Frontend on Live Server (:5500) -> FastAPI (:8000): preflight must not hit the auth wall,
    and 401 responses must still carry CORS headers so the browser shows the real error."""
    monkeypatch.setattr(service, "DB_PATH", tmp_path / "app.sqlite3")
    monkeypatch.setattr(service, "AUTH_REQUIRED", True)
    service.init_db()
    origin = "http://127.0.0.1:5500"
    with TestClient(service.app) as client:
        pre = client.options("/diagnose", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
        assert pre.status_code == 200, pre.text
        assert pre.headers.get("access-control-allow-origin") == origin
        assert pre.headers.get("access-control-allow-credentials") == "true"
        blocked = client.get("/profile", headers={"Origin": origin})
        assert blocked.status_code == 401
        assert blocked.headers.get("access-control-allow-origin") == origin
