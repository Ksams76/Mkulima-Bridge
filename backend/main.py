"""ShambaSense AI FastAPI service. Local-demo persistence uses SQLite."""
import os
import json
import re
import base64
import hashlib
import hmac
import secrets
import sqlite3
from contextvars import ContextVar
from threading import RLock
from contextlib import contextmanager
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from backend import classifier as crop_classifier
from backend import llm as llm_provider
from backend.knowledge import retrieve, retrieve_for_labels, load_documents

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)
DB_PATH = Path(os.getenv("SHAMBASENSE_DB", str(Path(__file__).resolve().parent / "shambasense.db")))
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "true").strip().lower() not in {"0", "false", "no", "off"}
SESSION_COOKIE_NAME = "mkulima_session"
SESSION_DAYS = max(1, min(int(os.getenv("SESSION_DAYS", "14")), 30))
_PRODUCTION_ENV = os.getenv("APP_ENV", "development").strip().lower() in {"production", "prod"}
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "true" if _PRODUCTION_ENV else "false").strip().lower() in {"1", "true", "yes", "on"}
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", str(Path(__file__).resolve().parent / "uploads")))
MAX_CASE_VIDEO_BYTES = 20 * 1024 * 1024
ACTIVE_USER_ID: ContextVar[Optional[int]] = ContextVar("active_user_id", default=None)
_INITIALIZED_USER_DBS: set[str] = set()
_INITIALIZING_USER_DBS: set[str] = set()
_USER_DB_LOCK = RLock()
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.6"))
disease_classifier = crop_classifier.load_classifier()  # None until a model is configured

LLM = llm_provider.load_llm()          # Groq (default) or Hugging Face / Gemma 4, chosen by LLM_PROVIDER
client = LLM.client                    # None until the provider's key/token is set
MODEL_NAME = LLM.model
LLM_PROVIDER = LLM.provider
VISION_ENABLED = LLM.vision            # /diagnose also sends the photo to the model (huggingface only)
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
DEMO_MODE = os.getenv("DEMO_MODE", "false").strip().lower() in {"1", "true", "yes", "on"}

def not_configured_message() -> str:
    if LLM_PROVIDER == "huggingface":
        return "Hugging Face is not configured. Install backend requirements and add HF_TOKEN to the project .env file."
    return "Groq is not configured. Install backend requirements and add GROQ_API_KEY to the project .env file."

def chat_completion(messages: list, max_tokens: int = 1400) -> str:
    """One chat call on the configured provider; returns the cleaned answer text ('' if empty)."""
    kwargs = llm_provider.request_kwargs(LLM_PROVIDER, MODEL_NAME, messages, max_tokens, TEMPERATURE)
    response = client.chat.completions.create(**kwargs)
    return llm_provider.clean_answer(response.choices[0].message.content)

app = FastAPI(title="ShambaSense AI", description="Agricultural guidance for Kenyan farmers", version="1.0.0")
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")
app.mount("/images", StaticFiles(directory=FRONTEND_DIR / "images"), name="images")


class FarmProfile(BaseModel):
    farmer_name: Optional[str] = Field(default=None, max_length=100)
    county: Optional[str] = Field(default=None, max_length=100)
    sub_county: Optional[str] = Field(default=None, max_length=100)
    main_crop: Optional[str] = Field(default=None, max_length=100)
    farm_size: Optional[str] = Field(default=None, max_length=50)

class RegisterInput(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)

class LoginInput(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)

class CropQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    language: str = Field(default="English", max_length=30)
    farm_profile: Optional[FarmProfile] = None

class ReminderInput(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    due_at: str = Field(min_length=10, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=500)
    case_id: Optional[int] = Field(default=None, ge=1)

class FarmCaseInput(BaseModel):
    case_type: str = Field(default="crop", max_length=20)
    crop: Optional[str] = Field(default=None, max_length=100)
    species: Optional[str] = Field(default=None, max_length=80)
    animal_group: Optional[str] = Field(default=None, max_length=100)
    animal_age_group: Optional[str] = Field(default=None, max_length=60)
    animal_count: Optional[float] = Field(default=None, ge=0, le=1000000)
    issue_category: Optional[str] = Field(default=None, max_length=100)
    title: str = Field(min_length=3, max_length=160)
    problem: str = Field(min_length=5, max_length=2000)
    symptoms: Optional[str] = Field(default=None, max_length=1500)
    onset_date: Optional[str] = Field(default=None, max_length=10)
    crop_stage: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = Field(default=None, max_length=1000)

class CaseObservationInput(BaseModel):
    observation: str = Field(min_length=3, max_length=2000)
    observed_at: Optional[str] = Field(default=None, max_length=30)

class CaseStatusInput(BaseModel):
    status: str = Field(min_length=3, max_length=30)

class CaseAssessmentInput(BaseModel):
    language: str = Field(default="English", max_length=30)

class CaseActionInput(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    due_at: str = Field(min_length=10, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=500)


class LearningSessionInput(BaseModel):
    module_id: str = Field(min_length=2, max_length=60)
    answers: list[int] = Field(min_length=1, max_length=10)

class CommunityReportInput(BaseModel):
    case_type: str = Field(default="crop", max_length=20)
    crop: Optional[str] = Field(default=None, max_length=100)
    species: Optional[str] = Field(default=None, max_length=80)
    county: str = Field(min_length=2, max_length=100)
    category: str = Field(min_length=2, max_length=80)
    consent: bool

class ReferralCreateInput(BaseModel):
    expert_category: str = Field(default="general_extension", min_length=2, max_length=60)
    urgency: str = Field(default="routine", max_length=20)
    additional_context: Optional[str] = Field(default=None, max_length=500)

class ChangePasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=10, max_length=128)

class AccountUpdateInput(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)

class UserSettingsInput(BaseModel):
    theme: str = Field(default="system", max_length=20)
    language: str = Field(default="English", max_length=20)
    timezone: str = Field(default="Africa/Nairobi", max_length=80)
    region: str = Field(default="Kenya", max_length=80)
    farm_type: str = Field(default="mixed", max_length=30)
    farm_unit: str = Field(default="acres", max_length=20)
    weather_county: str = Field(default="", max_length=100)
    weather_area: str = Field(default="", max_length=100)
    rainfall_unit: str = Field(default="mm", max_length=20)
    weather_alerts: bool = True
    in_app_reminders: bool = True
    low_stock_alerts: bool = True
    response_style: str = Field(default="balanced", max_length=20)
    save_ai_history: bool = True
    compact_layout: bool = False

class InventoryInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: str = Field(default="Other", max_length=60)
    unit: str = Field(default="units", min_length=1, max_length=30)
    quantity: float = Field(ge=0, le=100000000)
    reorder_level: float = Field(default=0, ge=0, le=100000000)
    notes: Optional[str] = Field(default=None, max_length=500)

class InventoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    category: Optional[str] = Field(default=None, max_length=60)
    unit: Optional[str] = Field(default=None, min_length=1, max_length=30)
    quantity: Optional[float] = Field(default=None, ge=0, le=100000000)
    reorder_level: Optional[float] = Field(default=None, ge=0, le=100000000)
    notes: Optional[str] = Field(default=None, max_length=500)

class ReferralStatusInput(BaseModel):
    status: str = Field(min_length=2, max_length=40)
    expert_name: Optional[str] = Field(default=None, max_length=120)
    notes: Optional[str] = Field(default=None, max_length=500)

def auth_db_path() -> Path:
    return DB_PATH.with_name(f"{DB_PATH.stem}_accounts.sqlite3")

def user_db_path(user_id: int) -> Path:
    directory = DB_PATH.parent / f"{DB_PATH.stem}_users"
    return directory / f"user_{int(user_id)}.sqlite3"

def _connect_database(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn

@contextmanager
def auth_db():
    conn = _connect_database(auth_db_path())
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login_at TEXT
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
        """)
        yield conn
        conn.commit()
    finally:
        conn.close()

@contextmanager
def db():
    user_id = ACTIVE_USER_ID.get()
    if user_id is not None:
        path = user_db_path(user_id)
        key = str(path.resolve())
        if key not in _INITIALIZED_USER_DBS and key not in _INITIALIZING_USER_DBS:
            with _USER_DB_LOCK:
                if key not in _INITIALIZED_USER_DBS and key not in _INITIALIZING_USER_DBS:
                    _INITIALIZING_USER_DBS.add(key)
                    token = ACTIVE_USER_ID.set(None)
                    try:
                        init_db(path)
                        _INITIALIZED_USER_DBS.add(key)
                    finally:
                        ACTIVE_USER_ID.reset(token)
                        _INITIALIZING_USER_DBS.discard(key)
        db_file = path
    else:
        db_file = DB_PATH
    conn = _connect_database(db_file)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

@contextmanager
def community_db():
    """Shared, category-only database for consented community trend counts."""
    conn = _connect_database(DB_PATH.with_name(f"{DB_PATH.stem}_community.sqlite3"))
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS community_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crop TEXT NOT NULL,
            county TEXT NOT NULL,
            category TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'reported',
            created_at TEXT NOT NULL,
            case_type TEXT NOT NULL DEFAULT 'crop',
            species TEXT
        )""")
        columns = {row[1] for row in conn.execute("PRAGMA table_info(community_reports)").fetchall()}
        if "case_type" not in columns:
            conn.execute("ALTER TABLE community_reports ADD COLUMN case_type TEXT NOT NULL DEFAULT 'crop'")
        if "species" not in columns:
            conn.execute("ALTER TABLE community_reports ADD COLUMN species TEXT")
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db(path: Optional[Path] = None):
    target = path or DB_PATH
    conn = _connect_database(target)
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK(id=1), farmer_name TEXT, county TEXT, sub_county TEXT, main_crop TEXT, farm_size TEXT, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL, answer TEXT NOT NULL, language TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, due_at TEXT NOT NULL, notes TEXT, completed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_ref TEXT NOT NULL UNIQUE,
            crop TEXT NOT NULL,
            title TEXT NOT NULL,
            problem TEXT NOT NULL,
            symptoms TEXT,
            onset_date TEXT,
            crop_stage TEXT,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS case_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            observation TEXT NOT NULL,
            observed_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS case_assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            assessment TEXT NOT NULL,
            language TEXT NOT NULL,
            sources_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS learning_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module_id TEXT NOT NULL,
            module_title TEXT NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            answers_json TEXT NOT NULL,
            completed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS community_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crop TEXT NOT NULL,
            county TEXT NOT NULL,
            category TEXT NOT NULL,
            review_status TEXT NOT NULL DEFAULT 'reported',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS expert_referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            case_ref TEXT NOT NULL,
            summary TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'prepared',
            expert_name TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS farm_inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            unit TEXT NOT NULL,
            quantity REAL NOT NULL CHECK(quantity >= 0),
            reorder_level REAL NOT NULL DEFAULT 0 CHECK(reorder_level >= 0),
            notes TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS case_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS user_settings (
            id INTEGER PRIMARY KEY CHECK(id=1),
            settings_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS case_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
            media_kind TEXT NOT NULL DEFAULT 'video',
            stored_name TEXT NOT NULL UNIQUE,
            original_name TEXT NOT NULL,
            content_type TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL
        );
        """)
        reminder_columns = {row[1] for row in conn.execute("PRAGMA table_info(reminders)").fetchall()}
        if "case_id" not in reminder_columns:
            conn.execute("ALTER TABLE reminders ADD COLUMN case_id INTEGER REFERENCES cases(id) ON DELETE SET NULL")
        case_columns = {row[1] for row in conn.execute("PRAGMA table_info(cases)").fetchall()}
        for column, declaration in {
            "case_type": "TEXT NOT NULL DEFAULT 'crop'",
            "species": "TEXT",
            "animal_group": "TEXT",
            "animal_age_group": "TEXT",
            "animal_count": "REAL",
            "issue_category": "TEXT",
        }.items():
            if column not in case_columns:
                conn.execute(f"ALTER TABLE cases ADD COLUMN {column} {declaration}")
        referral_columns = {row[1] for row in conn.execute("PRAGMA table_info(expert_referrals)").fetchall()}
        for column, declaration in {
            "expert_category": "TEXT NOT NULL DEFAULT 'general_extension'",
            "recommended_role": "TEXT NOT NULL DEFAULT 'Agricultural extension officer'",
            "urgency": "TEXT NOT NULL DEFAULT 'routine'",
        }.items():
            if column not in referral_columns:
                conn.execute(f"ALTER TABLE expert_referrals ADD COLUMN {column} {declaration}")
        conn.commit()
    finally:
        conn.close()

init_db()

def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 310_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"

def _verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt_text, digest_text = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False

def _normalise_email(email: str) -> str:
    value = email.strip().lower()
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", value):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    return value

def _issue_session(user_id: int, response: Response):
    raw_token = secrets.token_urlsafe(40)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=SESSION_DAYS)
    with auth_db() as conn:
        conn.execute("INSERT INTO sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",
                     (token_hash, user_id, expires.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")))
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(timespec="seconds"),))
    response.set_cookie(SESSION_COOKIE_NAME, raw_token, max_age=SESSION_DAYS*86400,
                        httponly=True, secure=SESSION_COOKIE_SECURE, samesite="lax", path="/")

def _session_user(raw_token: Optional[str]):
    if not raw_token:
        return None
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now = utc_now()
    with auth_db() as conn:
        row = conn.execute("""SELECT u.id,u.full_name,u.email,u.created_at
            FROM sessions s JOIN users u ON u.id=s.user_id
            WHERE s.token_hash=? AND s.expires_at>?""", (token_hash, now)).fetchone()
    return dict(row) if row else None

def record_case_event(conn, case_id: int, event_type: str, description: str):
    conn.execute("INSERT INTO case_events(case_id,event_type,description,created_at) VALUES(?,?,?,?)", (case_id,event_type,description,utc_now()))

def profile_dict(row):
    if not row:
        return {"farmer_name":"", "county":"", "sub_county":"", "main_crop":"", "farm_size":"", "saved":False, "updated_at":None}
    result = dict(row)
    result["saved"] = True
    return result

PUBLIC_PATHS = {"/", "/health", "/knowledge/status", "/auth/register", "/auth/login", "/auth/logout", "/auth/me", "/learning/modules", "/community/pulse", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
PUBLIC_PREFIXES = ("/css/", "/js/", "/images/")

@app.middleware("http")
async def require_farmer_session(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not AUTH_REQUIRED or path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        return await call_next(request)
    user = _session_user(request.cookies.get(SESSION_COOKIE_NAME))
    if not user:
        return JSONResponse(status_code=401, content={"detail":"Please sign in to access your farm workspace."})
    request.state.user = user
    token = ACTIVE_USER_ID.set(int(user["id"]))
    try:
        return await call_next(request)
    finally:
        ACTIVE_USER_ID.reset(token)

# CORS is registered AFTER the auth middleware on purpose: Starlette runs the last-added middleware first,
# so preflight (OPTIONS) requests and 401 responses from the Live Server :5500 -> FastAPI :8000 setup still get CORS headers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500", "http://localhost:5500", "http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=True, allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Supervisor-Token"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
)

@app.post("/auth/register")
def register_account(data: RegisterInput, response: Response):
    full_name = data.full_name.strip()
    if len(full_name) < 2:
        raise HTTPException(status_code=422, detail="Enter your full name.")
    if not any(char.isalpha() for char in data.password) or not any(char.isdigit() for char in data.password):
        raise HTTPException(status_code=422, detail="Use a password with at least one letter and one number.")
    email = _normalise_email(data.email)
    password_hash = _hash_password(data.password)
    now = utc_now()
    try:
        with auth_db() as conn:
            cursor = conn.execute("INSERT INTO users(full_name,email,password_hash,created_at) VALUES(?,?,?,?)",
                                  (full_name, email, password_hash, now))
            user_id = int(cursor.lastrowid)
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="An account with this email already exists. Please sign in instead.")
    # Every account receives a separate local SQLite data store. The original single-user
    # demo database remains untouched and is not exposed to newly registered accounts.
    token = ACTIVE_USER_ID.set(user_id)
    try:
        with db():
            pass
    finally:
        ACTIVE_USER_ID.reset(token)
    _issue_session(user_id, response)
    return {"message":"Your MkulimaBridge account has been created.", "user":{"id":user_id,"full_name":full_name,"email":email,"created_at":now}}

@app.post("/auth/login")
def login_account(data: LoginInput, response: Response):
    email = _normalise_email(data.email)
    with auth_db() as conn:
        row = conn.execute("SELECT id,full_name,email,password_hash,created_at FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone()
    # Run a fixed dummy PBKDF2 on missing users to reduce account-enumeration timing differences.
    if not row:
        _verify_password(data.password, _hash_password("dummy-password-987654"))
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    if not _verify_password(data.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    with auth_db() as conn:
        conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (utc_now(), row["id"]))
    _issue_session(int(row["id"]), response)
    return {"message":"You are signed in.", "user":{"id":row["id"],"full_name":row["full_name"],"email":row["email"],"created_at":row["created_at"]}}

@app.post("/auth/logout")
def logout_account(request: Request, response: Response):
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        with auth_db() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", httponly=True, secure=SESSION_COOKIE_SECURE, samesite="lax")
    return {"message":"You have been signed out."}

@app.get("/auth/me")
def current_account(request: Request):
    user = _session_user(request.cookies.get(SESSION_COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="You are not signed in.")
    return {"authenticated":True,"user":user}


DEFAULT_USER_SETTINGS = {
    "theme": "system", "language": "English", "timezone": "Africa/Nairobi", "region": "Kenya",
    "farm_type": "mixed", "farm_unit": "acres", "weather_county": "", "weather_area": "",
    "rainfall_unit": "mm", "weather_alerts": True, "in_app_reminders": True,
    "low_stock_alerts": True, "response_style": "balanced", "save_ai_history": True,
    "compact_layout": False,
}

@app.get("/account")
def get_account(request: Request):
    user = getattr(request.state, "user", None)
    if user is None:
        user = _session_user(request.cookies.get(SESSION_COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="Please sign in to view account settings.")
    return {"full_name": user["full_name"], "email": user["email"], "created_at": user["created_at"]}

@app.patch("/account")
def update_account(data: AccountUpdateInput, request: Request):
    user = getattr(request.state, "user", None)
    if user is None:
        user = _session_user(request.cookies.get(SESSION_COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="Please sign in to update your account.")
    full_name = data.full_name.strip()
    if len(full_name) < 2:
        raise HTTPException(status_code=422, detail="Enter your full name.")
    with auth_db() as conn:
        conn.execute("UPDATE users SET full_name=? WHERE id=?", (full_name, int(user["id"])))
    return {"message": "Account name updated successfully.", "full_name": full_name, "email": user["email"]}

@app.post("/account/password")
def change_account_password(data: ChangePasswordInput, request: Request):
    user = getattr(request.state, "user", None)
    if user is None:
        user = _session_user(request.cookies.get(SESSION_COOKIE_NAME))
    if not user:
        raise HTTPException(status_code=401, detail="Please sign in to change your password.")
    if not any(ch.isalpha() for ch in data.new_password) or not any(ch.isdigit() for ch in data.new_password):
        raise HTTPException(status_code=422, detail="Use a new password containing at least one letter and one number.")
    with auth_db() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id=?", (int(user["id"]),)).fetchone()
        if not row or not _verify_password(data.current_password, row["password_hash"]):
            raise HTTPException(status_code=400, detail="Your current password is incorrect.")
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (_hash_password(data.new_password), int(user["id"])))
        conn.execute("DELETE FROM sessions WHERE user_id=?", (int(user["id"]),))
    response = JSONResponse({"message": "Password changed. Please sign in again on this device and any other devices."})
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", httponly=True, secure=SESSION_COOKIE_SECURE, samesite="lax")
    return response

@app.get("/settings")
def get_user_settings():
    with db() as conn:
        row = conn.execute("SELECT settings_json,updated_at FROM user_settings WHERE id=1").fetchone()
    settings = dict(DEFAULT_USER_SETTINGS)
    if row:
        try:
            settings.update(json.loads(row["settings_json"]))
        except (json.JSONDecodeError, TypeError):
            pass
    settings["updated_at"] = row["updated_at"] if row else None
    settings["saved"] = bool(row)
    return settings

@app.put("/settings")
def save_user_settings(data: UserSettingsInput):
    values = data.model_dump()
    allowed = {
        "theme": {"light", "dark", "system"}, "language": {"English", "Kiswahili"},
        "farm_type": {"crop", "livestock", "mixed"}, "farm_unit": {"acres", "hectares"},
        "rainfall_unit": {"mm", "inches"}, "response_style": {"simple", "balanced", "detailed"},
    }
    for key, choices in allowed.items():
        if values[key] not in choices:
            raise HTTPException(status_code=422, detail=f"Unsupported {key.replace('_', ' ')} setting.")
    values["timezone"] = values["timezone"].strip() or "Africa/Nairobi"
    values["region"] = values["region"].strip() or "Kenya"
    values["weather_county"] = values["weather_county"].strip()
    values["weather_area"] = values["weather_area"].strip()
    now = utc_now()
    with db() as conn:
        conn.execute("INSERT INTO user_settings(id,settings_json,updated_at) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET settings_json=excluded.settings_json,updated_at=excluded.updated_at", (json.dumps(values), now))
    return {"message": "Your settings have been saved successfully.", "settings": values, "updated_at": now, "saved": True}

def get_setting_value(key: str, default=None):
    with db() as conn:
        row = conn.execute("SELECT settings_json FROM user_settings WHERE id=1").fetchone()
    if not row:
        return default
    try:
        return json.loads(row["settings_json"]).get(key, default)
    except (json.JSONDecodeError, TypeError):
        return default

@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")

@app.get("/health")
def health():
    return {"status":"ok", "api_key_configured":client is not None, "provider":{"huggingface":"Hugging Face"}.get(LLM_PROVIDER,"Groq"), "model":MODEL_NAME, "database":"sqlite", "classifier_configured":disease_classifier is not None, "authentication_required":AUTH_REQUIRED, "photo_sent_to_model":bool(VISION_ENABLED and LLM_PROVIDER=="huggingface"), "demo_mode":DEMO_MODE, "settings_persisted": True, "video_upload_limit_mb": 20, "weather_live_data": False}

@app.get("/profile")
def get_profile():
    with db() as conn:
        row = conn.execute("SELECT farmer_name,county,sub_county,main_crop,farm_size,updated_at FROM profile WHERE id=1").fetchone()
    return profile_dict(row)

@app.put("/profile")
def save_profile(profile: FarmProfile):
    values = {k: (v.strip() if isinstance(v, str) else v) for k,v in profile.model_dump().items()}
    if not values.get("farmer_name") or not values.get("county") or not values.get("main_crop"):
        raise HTTPException(status_code=422, detail="Farmer name, county and main crop are required before saving your farm profile.")
    saved_at = utc_now()
    with db() as conn:
        conn.execute("""INSERT INTO profile(id,farmer_name,county,sub_county,main_crop,farm_size,updated_at) VALUES(1,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET farmer_name=excluded.farmer_name, county=excluded.county, sub_county=excluded.sub_county, main_crop=excluded.main_crop, farm_size=excluded.farm_size, updated_at=excluded.updated_at""",
        (values["farmer_name"],values["county"],values["sub_county"],values["main_crop"],values["farm_size"],saved_at))
    values.update({"saved":True,"updated_at":saved_at})
    return {"message":"Your farm profile has been saved successfully.", "profile":values, "saved_at":saved_at}

# Seeded source references are useful pointers; this MVP does not yet fetch/index their content (no RAG claim).
AG_SOURCE_REFERENCES = [
    {"title":"Kenya Agricultural and Livestock Research Organization (KALRO)","url":"https://www.kalro.org/"},
    {"title":"Ministry of Agriculture and Livestock Development, Kenya","url":"https://www.kilimo.go.ke/"},
    {"title":"FAO Kenya","url":"https://www.fao.org/kenya/"},
]

@app.post("/ask")
def ask_crop_question(data: CropQuestion):
    if DEMO_MODE:
        if data.language.lower().startswith("kis"):
            answer = "Hii ni hali ya majaribio ya ShambaSense AI. Kwanza rekodi dalili unazoona, zao na hatua ya ukuaji. Kagua mimea kadhaa katika sehemu tofauti za shamba na linganisha mimea iliyoathirika na isiyoathirika. Usichukulie jibu hili kama utambuzi au maelekezo ya kutumia dawa. Wasiliana na afisa ugani kwa tatizo linaloendelea au kuenea."
        else:
            answer = "This is a clearly labelled ShambaSense AI demo response. First record the crop, growth stage and signs you can actually observe. Inspect more than one part of the field and compare affected and unaffected plants. This sample does not diagnose the crop or recommend a treatment. Contact an agricultural extension officer if the problem spreads or persists."
        if get_setting_value("save_ai_history", True):
            with db() as conn:
                conn.execute("INSERT INTO history(question,answer,language,created_at) VALUES(?,?,?,?)", (data.question,answer,data.language,utc_now()))
        return {"question":data.question,"language":data.language,"answer":answer,"sources":[],"retrieval_used":False,"demo_mode":True}
    if client is None:
        raise HTTPException(status_code=503, detail=not_configured_message())
    profile = data.farm_profile
    if profile is None:
        try:
            profile = FarmProfile(**get_profile())
        except Exception:
            profile = FarmProfile()
    fields = [("Farmer",profile.farmer_name),("County",profile.county),("Sub-county",profile.sub_county),("Main crop",profile.main_crop),("Farm size",profile.farm_size)]
    context = "\n".join(f"{label}: {value.strip()}" for label,value in fields if value and value.strip()) or "No farm profile information was provided."
    retrieved = retrieve(data.question)
    knowledge_context = "\n\n".join(f"SOURCE: {item['title']}\nURL: {item['url']}\nEXCERPT: {item['text']}" for item in retrieved)
    if not knowledge_context:
        knowledge_context = "No reviewed local source excerpt matched this question. Do not imply source retrieval occurred; answer cautiously from general model knowledge and recommend local extension verification for consequential advice."
    style = get_setting_value("response_style", "balanced")
    style_note = {
        "simple": "Use very simple language, short sentences and a few practical steps.",
        "detailed": "Give a structured, more detailed explanation while distinguishing evidence from uncertainty.",
        "balanced": "Use clear, practical explanations with concise steps.",
    }.get(style, "Use clear, practical explanations.")
    livestock_terms = ("cattle", "cow", "goat", "sheep", "poultry", "chicken", "hen", "broiler", "pig", "rabbit", "camel", "fish", "ng'ombe", "mbuzi", "kondoo", "kuku", "nguruwe", "samaki")
    is_livestock_question = any(term in data.question.lower() for term in livestock_terms) or get_setting_value("farm_type", "mixed") == "livestock"
    if is_livestock_question:
        role_instruction = "The question concerns livestock. Give cautious animal-care information, not veterinary diagnosis. Do not prescribe veterinary medicines, antibiotics, dewormers, injections, home remedies or dosages. Encourage prompt advice from a qualified veterinary professional for serious, worsening or unclear signs. Treat breathing difficulty, collapse, seizures, severe bleeding, suspected poisoning, difficult birth or several animals suddenly ill as urgent."
    else:
        role_instruction = "For high-risk crop protection advice, advise following the registered product label and consulting a local agricultural extension officer."
    prompt = f"""You are ShambaSense AI, a cautious agriculture and livestock information assistant supporting smallholder farmers in Kenya.
FARM PROFILE:\n{context}
RETRIEVED REVIEWED KNOWLEDGE (may be empty):\n{knowledge_context}
Use the profile only when relevant; do not infer weather, soil, growth stage, or diagnosis from location alone.
Answer in {data.language}. {style_note} Ask for missing details when needed.
Distinguish possible causes from confirmed diagnosis. Do not invent chemical or veterinary dosages or unsupported facts.
{role_instruction}
When retrieved excerpts support a claim, cite the source title and URL. Never fabricate citations or claim a source was retrieved if no excerpt is supplied.
QUESTION: {data.question}"""
    try:
        answer = chat_completion([
            {"role":"system","content":"Be helpful, grounded, cautious, and clear. Use natural standard Kenyan Kiswahili when requested. Never claim a definite crop or animal diagnosis from limited details. For animal health questions, do not act as a veterinarian and do not prescribe medicines or dosages."},
            {"role":"user","content":prompt}])
        if not answer:
            raise HTTPException(status_code=502, detail="The AI returned an empty response.")
        if get_setting_value("save_ai_history", True):
            with db() as conn:
                conn.execute("INSERT INTO history(question,answer,language,created_at) VALUES(?,?,?,?)", (data.question,answer,data.language,utc_now()))
        return {"question":data.question,"language":data.language,"answer":answer,"sources":[{"title":item["title"],"url":item["url"]} for item in retrieved],"retrieval_used":bool(retrieved)}
    except HTTPException:
        raise
    except Exception as exc:
        print("LLM request failed:",type(exc).__name__)
        raise HTTPException(status_code=502, detail="The AI request failed. Check the backend terminal and provider availability.")

def farm_context(profile: FarmProfile) -> str:
    fields = [("Farmer",profile.farmer_name),("County",profile.county),("Sub-county",profile.sub_county),("Main crop",profile.main_crop),("Farm size",profile.farm_size)]
    return "\n".join(f"{label}: {value.strip()}" for label,value in fields if value and value.strip()) or "No farm profile information was provided."

def build_diagnosis_prompt(predictions, confident: bool, retrieved: list[dict], profile_text: str, language: str, note: Optional[str], vision: bool = False) -> str:
    ranked = "\n".join(f"{i}. {p.display_label} ({p.confidence*100:.0f}%)" for i,p in enumerate(predictions,1))
    status = ("The top prediction is above the confidence threshold, but it is still an automatic suggestion, not a confirmed diagnosis."
              if confident else
              "CONFIDENCE IS LOW. Do not present any disease as likely. Say plainly that the photo could not be identified reliably, list what to check on the plant, and ask for clearer photos.")
    if retrieved:
        knowledge = "\n\n".join(f"SOURCE: {i['title']}\nURL: {i['url']}\nMATCH: {'exact disease label' if i.get('matched_by')=='label' else 'keyword match only - may not be about this exact disease'}\nEXCERPT: {i['text']}" for i in retrieved)
    else:
        knowledge = "No reviewed local source excerpt matched. Do not imply source retrieval occurred, and give no specific treatments or product names."
    vision_note = ("\nA photo of the plant is attached before this text. Treat the classifier as one signal, not as the truth. Describe only symptoms you can actually see (spot colour and shape, pattern, where on the plant). If what you see disagrees with the classifier, say so and treat the result as uncertain. Do not diagnose from the photo alone.\n" if vision else "")
    return f"""You are ShambaSense AI, a cautious agricultural information assistant supporting smallholder farmers in Kenya.
An automatic image classifier analysed the farmer's crop photo. Its output is below.
CLASSIFIER PREDICTIONS (most likely first):\n{ranked}
STATUS: {status}
FARM PROFILE:\n{profile_text}
FARMER NOTE: {note or "None"}
RETRIEVED REVIEWED KNOWLEDGE (may be empty):\n{knowledge}{vision_note}
Answer in {language}. Use short, practical steps a smallholder farmer can follow.
Explain what the classifier suggests, which symptoms the farmer should confirm on the plant before acting, and safe next steps.
Only state treatment details that appear in the retrieved excerpts. Otherwise suggest general non-chemical practices (isolating affected plants, removing badly infected leaves, avoiding overhead watering) and advise following the registered product label and consulting a local agricultural extension officer.
Never invent pesticide names or dosages. Never claim a definite diagnosis from a photo. Cite only the sources supplied above, by title and URL."""

@app.post("/diagnose")
def diagnose_crop_image(image: UploadFile = File(...), language: str = Form("English"), note: Optional[str] = Form(None)):
    """Image -> classifier -> reviewed knowledge -> cautious explanation in English or Kiswahili."""
    if disease_classifier is None:
        raise HTTPException(status_code=503, detail="The crop image classifier is not configured. Set CLASSIFIER_MODEL_PATH and CLASSIFIER_LABELS_PATH in .env (see README).")
    language = (language or "English").strip()[:30] or "English"
    note = note.strip()[:500] if note and note.strip() else None
    if image.content_type not in crop_classifier.ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Please upload a JPEG, PNG or WebP image.")
    data = image.file.read(crop_classifier.MAX_IMAGE_BYTES + 1)
    if len(data) > crop_classifier.MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="The image is larger than 5 MB. Please upload a smaller photo.")
    try:
        pil_image = crop_classifier.load_image(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        predictions = disease_classifier.predict(pil_image)
    except Exception as exc:
        print("Classifier failed:", type(exc).__name__)
        raise HTTPException(status_code=500, detail="The image could not be analysed. Please try another photo.")
    if not predictions:
        raise HTTPException(status_code=500, detail="The classifier returned no predictions.")
    confident = predictions[0].confidence >= CONFIDENCE_THRESHOLD
    retrieved = retrieve_for_labels([p.label for p in predictions if p.confidence >= 0.10]) if confident else []
    try:
        profile = FarmProfile(**get_profile())
    except Exception:
        profile = FarmProfile()
    result = {
        "status": "confident" if confident else "uncertain",
        "threshold": CONFIDENCE_THRESHOLD,
        "predictions": [{"label":p.label,"display_label":p.display_label,"confidence":round(p.confidence,4)} for p in predictions],
        "language": language, "answer": None,
        "sources": [{"title":i["title"],"url":i["url"]} for i in retrieved], "retrieval_used": bool(retrieved),
        "disclaimer": "Automatic suggestion from a photo, not a confirmed diagnosis. Confirm symptoms on the plant and consult a local agricultural extension officer before treating.",
    }
    result["vision_used"] = False
    if client is None:
        result["warning"] = "Explanation unavailable: the language model is not configured. Showing classifier results only."
        return result
    system_message = {"role":"system","content":"Be helpful, grounded, cautious, and clear. Use natural standard Kenyan Kiswahili when requested. Never claim a definite crop diagnosis from a photo."}
    profile_text = farm_context(profile)
    answer = ""
    if VISION_ENABLED and LLM_PROVIDER == "huggingface":
        # Option 2: the model sees the (re-encoded, metadata-free) photo. Image goes before the text.
        try:
            prompt = build_diagnosis_prompt(predictions, confident, retrieved, profile_text, language, note, vision=True)
            answer = chat_completion([system_message, {"role":"user","content":[
                {"type":"image_url","image_url":{"url":llm_provider.image_data_url(pil_image)}},
                {"type":"text","text":prompt}]}])
            result["vision_used"] = bool(answer)
        except Exception as exc:
            print("LLM vision request failed, retrying without the photo:", type(exc).__name__)
            answer = ""
    if not answer:
        # Option 1 (and fallback): the model only sees classifier labels, scores and reviewed knowledge.
        try:
            prompt = build_diagnosis_prompt(predictions, confident, retrieved, profile_text, language, note)
            answer = chat_completion([system_message, {"role":"user","content":prompt}])
        except Exception as exc:
            print("LLM request failed:", type(exc).__name__)
            answer = ""
    if not answer:
        result["warning"] = "The explanation could not be generated. Showing classifier results only."
        return result
    result["answer"] = answer
    top = predictions[0]
    summary = f"[Image diagnosis] {top.display_label} ({top.confidence*100:.0f}%)" if confident else "[Image diagnosis] Low confidence - photo not identified"
    if get_setting_value("save_ai_history", True):
        with db() as conn:
            conn.execute("INSERT INTO history(question,answer,language,created_at) VALUES(?,?,?,?)", (summary, answer, language, utc_now()))
    return result

@app.get("/knowledge/status")
def knowledge_status():
    docs=load_documents()
    return {"document_count":len(docs),"retrieval":"local lexical matching","status":"ready" if docs else "empty corpus; add reviewed source excerpts to backend/knowledge_base.json"}

def _case_detail(conn, case_id: int):
    row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["observations"] = [dict(item) for item in conn.execute(
        "SELECT id, observation, observed_at, created_at FROM case_observations WHERE case_id=? ORDER BY id DESC", (case_id,)
    ).fetchall()]
    assessments = conn.execute(
        "SELECT id, assessment, language, sources_json, created_at FROM case_assessments WHERE case_id=? ORDER BY id DESC", (case_id,)
    ).fetchall()
    result["assessments"] = []
    for item in assessments:
        assessment = dict(item)
        try:
            assessment["sources"] = json.loads(assessment.pop("sources_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            assessment["sources"] = []
            assessment.pop("sources_json", None)
        result["assessments"].append(assessment)
    result["actions"] = [dict(item) for item in conn.execute(
        "SELECT id, title, due_at, notes, completed, created_at FROM reminders WHERE case_id=? ORDER BY due_at ASC", (case_id,)
    ).fetchall()]
    result["events"] = [dict(item) for item in conn.execute(
        "SELECT id,event_type,description,created_at FROM case_events WHERE case_id=? ORDER BY id DESC LIMIT 100", (case_id,)
    ).fetchall()]
    result["media"] = [dict(item) for item in conn.execute(
        "SELECT id,media_kind,original_name,content_type,file_size,description,created_at FROM case_media WHERE case_id=? ORDER BY id DESC", (case_id,)
    ).fetchall()]
    return result

LIVESTOCK_SPECIES = ["Cattle", "Goats", "Sheep", "Poultry", "Pigs", "Rabbits", "Camels", "Fish", "Other"]
LIVESTOCK_ISSUES = ["Reduced appetite or not eating", "Unusual behaviour or weakness", "Coughing or breathing concern", "Diarrhoea or digestive concern", "Skin, coat or parasite concern", "Lameness or movement concern", "Reproductive or birthing concern", "Egg or milk production change", "Injury or wound", "Sudden illness or multiple animals affected", "Other animal health concern"]
EXPERT_CATEGORIES = {
    "general_extension": {"label": "General agricultural extension", "role": "Agricultural extension officer", "case_types": ["crop", "livestock"], "description": "General farm advice, assessment and referral coordination."},
    "crop_protection": {"label": "Crop pests and diseases", "role": "Crop protection specialist / plant pathologist", "case_types": ["crop"], "description": "Crop symptoms, pests, plant diseases and integrated pest management."},
    "soil_nutrition": {"label": "Soil and crop nutrition", "role": "Soil scientist / agronomist", "case_types": ["crop"], "description": "Soil condition, nutrient concerns and crop nutrition."},
    "water_irrigation": {"label": "Water and irrigation", "role": "Irrigation / water-management adviser", "case_types": ["crop"], "description": "Water availability, irrigation and drainage concerns."},
    "post_harvest": {"label": "Harvest and post-harvest handling", "role": "Post-harvest specialist", "case_types": ["crop"], "description": "Harvest quality, drying, storage and post-harvest loss."},
    "veterinary_health": {"label": "Animal health and veterinary care", "role": "Licensed veterinary professional", "case_types": ["livestock"], "description": "Animal illness, injuries, unusual behaviour and health concerns."},
    "animal_nutrition": {"label": "Animal feeding and nutrition", "role": "Animal nutritionist / livestock production adviser", "case_types": ["livestock"], "description": "Feed, water, body condition and production-related nutrition."},
    "animal_husbandry": {"label": "Animal housing and husbandry", "role": "Livestock production / animal husbandry officer", "case_types": ["livestock"], "description": "Housing, hygiene, welfare, handling and farm management."},
    "poultry_management": {"label": "Poultry production", "role": "Poultry specialist / veterinary professional", "case_types": ["livestock"], "description": "Poultry health, flock management, eggs and production."},
    "breeding_reproduction": {"label": "Breeding and reproduction", "role": "Animal reproduction / breeding specialist", "case_types": ["livestock"], "description": "Breeding management and reproductive concerns."},
}

@app.get("/livestock/options")
def livestock_options():
    return {"species": LIVESTOCK_SPECIES, "issues": LIVESTOCK_ISSUES, "expert_categories": [dict(key=k, **v) for k,v in EXPERT_CATEGORIES.items() if "livestock" in v["case_types"]]}

@app.get("/expert/categories")
def expert_categories(case_type: str = "crop"):
    case_type = (case_type or "crop").strip().lower()
    if case_type not in {"crop", "livestock"}:
        raise HTTPException(status_code=422, detail="case_type must be crop or livestock.")
    return [dict(key=k, **v) for k,v in EXPERT_CATEGORIES.items() if case_type in v["case_types"]]

@app.post("/cases")
def create_case(data: FarmCaseInput):
    onset_date = (data.onset_date or "").strip() or None
    if onset_date:
        try:
            date.fromisoformat(onset_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="onset_date must use YYYY-MM-DD format.")
    now = utc_now()
    clean = {key: (value.strip() if isinstance(value, str) else value) for key, value in data.model_dump().items()}
    case_type = (clean.get("case_type") or "crop").lower()
    if case_type not in {"crop", "livestock"}:
        raise HTTPException(status_code=422, detail="Choose either a crop or livestock case.")
    if not clean["title"] or not clean["problem"]:
        raise HTTPException(status_code=422, detail="Case title and problem description cannot be blank.")
    if case_type == "crop":
        if not clean.get("crop"):
            raise HTTPException(status_code=422, detail="Choose or enter the affected crop.")
        crop_value = clean["crop"]
        species = None
        if not clean.get("issue_category"):
            clean["issue_category"] = "General crop concern"
    else:
        species = clean.get("species")
        if not species or species not in LIVESTOCK_SPECIES:
            raise HTTPException(status_code=422, detail="Choose the animal species affected.")
        crop_value = "Livestock"
        if not clean.get("issue_category"):
            clean["issue_category"] = "General animal health concern"
    clean["onset_date"] = onset_date
    with db() as conn:
        for _ in range(5):
            case_ref = f"SS-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(3).upper()}"
            try:
                cur = conn.execute(
                    """INSERT INTO cases(case_ref,crop,title,problem,symptoms,onset_date,crop_stage,notes,status,created_at,updated_at,case_type,species,animal_group,animal_age_group,animal_count,issue_category)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (case_ref, crop_value, clean["title"], clean["problem"], clean["symptoms"], onset_date, clean["crop_stage"], clean["notes"], "open", now, now, case_type, species, clean.get("animal_group"), clean.get("animal_age_group"), clean.get("animal_count"), clean.get("issue_category"))
                )
                case_id = cur.lastrowid
                break
            except sqlite3.IntegrityError:
                continue
        else:
            raise HTTPException(status_code=500, detail="Could not create a unique case reference. Please try again.")
        description = "Livestock concern recorded for " + str(species) + "." if case_type == "livestock" else "Crop problem case recorded."
        record_case_event(conn, case_id, "created", description)
        result = _case_detail(conn, case_id)
    return result

@app.get("/cases")
def list_cases(status: Optional[str] = None, limit: int = 50, case_type: Optional[str] = None):
    limit = max(1, min(limit, 100))
    allowed_statuses = {"open", "monitoring", "resolved", "referred"}
    if status and status not in allowed_statuses:
        raise HTTPException(status_code=422, detail="Unsupported case status.")
    if case_type and case_type not in {"crop", "livestock"}:
        raise HTTPException(status_code=422, detail="Unsupported case type.")
    with db() as conn:
        conditions=[]; params=[]
        if status:
            conditions.append("status=?"); params.append(status)
        if case_type:
            conditions.append("case_type=?"); params.append(case_type)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = conn.execute(f"SELECT * FROM cases{where} ORDER BY updated_at DESC LIMIT ?", (*params, limit)).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            item["observation_count"] = conn.execute("SELECT COUNT(*) FROM case_observations WHERE case_id=?", (row["id"],)).fetchone()[0]
            item["assessment_count"] = conn.execute("SELECT COUNT(*) FROM case_assessments WHERE case_id=?", (row["id"],)).fetchone()[0]
            item["action_count"] = conn.execute("SELECT COUNT(*) FROM reminders WHERE case_id=?", (row["id"],)).fetchone()[0]
            results.append(item)
    return results

@app.get("/cases/{case_id}")
def get_case(case_id: int):
    with db() as conn:
        result = _case_detail(conn, case_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Farm case not found.")
    return result

def active_media_directory() -> Path:
    user_id = ACTIVE_USER_ID.get()
    if user_id is None:
        raise HTTPException(status_code=401, detail="Sign in before uploading or viewing farm videos.")
    directory = MEDIA_ROOT / f"user_{int(user_id)}"
    directory.mkdir(parents=True, exist_ok=True)
    return directory

@app.get("/cases/{case_id}/media")
def list_case_media(case_id: int):
    with db() as conn:
        if not conn.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Farm case not found.")
        rows = conn.execute("SELECT id,media_kind,original_name,content_type,file_size,description,created_at FROM case_media WHERE case_id=? ORDER BY id DESC", (case_id,)).fetchall()
    return [dict(row, url=f"/case-media/{row['id']}") for row in rows]

@app.post("/cases/{case_id}/media/videos")
async def upload_case_video(case_id: int, video: UploadFile = File(...), description: str = Form(default="")):
    allowed = {
        ".mp4": {"video/mp4"},
        ".mov": {"video/quicktime", "video/mp4"},
        ".webm": {"video/webm"},
    }
    original = Path(video.filename or "farm-video").name
    suffix = Path(original).suffix.lower()
    if suffix not in allowed or video.content_type not in allowed[suffix]:
        raise HTTPException(status_code=415, detail="Upload a short MP4, MOV or WebM video.")
    data = await video.read(MAX_CASE_VIDEO_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="The selected video is empty.")
    if len(data) > MAX_CASE_VIDEO_BYTES:
        raise HTTPException(status_code=413, detail="The video exceeds the 20 MB limit. Choose a shorter or smaller clip.")
    signature_ok = (suffix in {".mp4", ".mov"} and len(data) >= 12 and data[4:8] == b"ftyp") or (suffix == ".webm" and data.startswith(b"\x1aE\xdf\xa3"))
    if not signature_ok:
        raise HTTPException(status_code=422, detail="The file content does not appear to match the selected video format.")
    directory = active_media_directory()
    stored_name = f"case_{case_id}_{secrets.token_hex(16)}{suffix}"
    stored_path = directory / stored_name
    with db() as conn:
        if not conn.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Farm case not found in your workspace.")
        stored_path.write_bytes(data)
        try:
            cur = conn.execute("INSERT INTO case_media(case_id,media_kind,stored_name,original_name,content_type,file_size,description,created_at) VALUES(?,?,?,?,?,?,?,?)", (case_id,"video",stored_name,original,video.content_type,len(data),(description or "").strip()[:300],utc_now()))
            media_id = cur.lastrowid
            record_case_event(conn, case_id, "video_attached", "A short farm video was attached to this case.")
            conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (utc_now(), case_id))
        except Exception:
            stored_path.unlink(missing_ok=True)
            raise
    return {"id": media_id, "case_id": case_id, "original_name": original, "content_type": video.content_type, "file_size": len(data), "url": f"/case-media/{media_id}", "message": "Video attached to the farm case successfully."}

@app.get("/case-media/{media_id}")
def get_case_media(media_id: int):
    directory = active_media_directory()
    with db() as conn:
        row = conn.execute("SELECT stored_name,original_name,content_type FROM case_media WHERE id=?", (media_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Video not found in your workspace.")
    filename = Path(row["stored_name"]).name
    path = directory / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The stored video file is missing. It may need to be uploaded again.")
    return FileResponse(path, media_type=row["content_type"], filename=Path(row["original_name"]).name, content_disposition_type="inline")

@app.delete("/case-media/{media_id}")
def delete_case_media(media_id: int):
    directory = active_media_directory()
    with db() as conn:
        row = conn.execute("SELECT id,case_id,stored_name FROM case_media WHERE id=?", (media_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Video not found in your workspace.")
        conn.execute("DELETE FROM case_media WHERE id=?", (media_id,))
        record_case_event(conn, row["case_id"], "video_removed", "A video attachment was removed from this case.")
    (directory / Path(row["stored_name"]).name).unlink(missing_ok=True)
    return {"message": "Video attachment deleted."}

@app.post("/cases/{case_id}/observations")
def add_case_observation(case_id: int, data: CaseObservationInput):
    observation = data.observation.strip()
    if not observation:
        raise HTTPException(status_code=422, detail="Observation cannot be blank.")
    observed_at = (data.observed_at or "").strip() or None
    if observed_at:
        try:
            datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail="observed_at must be an ISO date/time value.")
    with db() as conn:
        if not conn.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Farm case not found.")
        conn.execute("INSERT INTO case_observations(case_id,observation,observed_at,created_at) VALUES(?,?,?,?)",
                     (case_id, observation, observed_at, utc_now()))
        conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (utc_now(), case_id))
        record_case_event(conn, case_id, "observation", "Follow-up observation added.")
        result = _case_detail(conn, case_id)
    return result

@app.patch("/cases/{case_id}/status")
def update_case_status(case_id: int, data: CaseStatusInput):
    allowed = {"open", "monitoring", "resolved", "referred"}
    status = data.status.strip().lower()
    if status not in allowed:
        raise HTTPException(status_code=422, detail=f"Status must be one of: {', '.join(sorted(allowed))}.")
    with db() as conn:
        previous = conn.execute("SELECT status FROM cases WHERE id=?", (case_id,)).fetchone()
        if not previous:
            raise HTTPException(status_code=404, detail="Farm case not found.")
        conn.execute("UPDATE cases SET status=?, updated_at=? WHERE id=?", (status, utc_now(), case_id))
        if previous["status"] != status:
            record_case_event(conn, case_id, "status_changed", f"Status changed from {previous['status']} to {status}.")
        result = _case_detail(conn, case_id)
    return result

@app.post("/cases/{case_id}/assessments")
def assess_case(case_id: int, data: CaseAssessmentInput):
    if DEMO_MODE:
        with db() as conn:
            case = _case_detail(conn, case_id)
            if case is None:
                raise HTTPException(status_code=404, detail="Farm case not found.")
            language = data.language.strip() or "English"
            if language.lower().startswith("kis"):
                answer = "JIBU LA MAJARIBIO: Huu si utambuzi halisi. Rekodi dalili kwa tarehe, kagua mimea mingi na linganisha sehemu zilizoathirika na zisizoathirika. Sababu zinaweza kuwa tofauti na zinahitaji uchunguzi zaidi. Usitumie dawa kwa kutegemea jibu hili. Tafuta ushauri wa afisa ugani ikiwa tatizo linaenea au ni kubwa."
            else:
                if case.get("case_type") == "livestock":
                    answer = "DEMO LIVESTOCK GUIDANCE — NOT A VETERINARY DIAGNOSIS. Record when signs began, how many animals are affected, their age group, appetite, behaviour and any changes in feed or water. Keep the animal comfortable and contact a qualified veterinary professional promptly for serious, worsening or unexplained signs. Do not give medicines based on this sample response."
                else:
                    answer = "DEMO ASSESSMENT — NOT A REAL AI DIAGNOSIS. The case has been saved for demonstration. Record dated observations, compare affected and unaffected plants, and seek an agricultural extension officer if the problem is spreading or severe. Do not choose a pesticide or treatment based on this sample response."
            conn.execute("INSERT INTO case_assessments(case_id,assessment,language,sources_json,created_at) VALUES(?,?,?,?,?)", (case_id,answer,language,"[]",utc_now()))
            conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (utc_now(),case_id))
            record_case_event(conn,case_id,"assessment_created","Demo assessment saved; no AI provider was called.")
            result = _case_detail(conn,case_id)
        return result
    if client is None:
        raise HTTPException(status_code=503, detail=not_configured_message())
    with db() as conn:
        case = _case_detail(conn, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Farm case not found.")
    profile = FarmProfile(**get_profile())
    language = data.language.strip() or "English"
    if case.get("case_type") == "livestock":
        details = [f"Case type: livestock", f"Species: {case.get('species') or 'Not provided'}", f"Animal group: {case.get('animal_group') or 'Not provided'}", f"Age group: {case.get('animal_age_group') or 'Not provided'}", f"Number of animals: {case.get('animal_count') if case.get('animal_count') is not None else 'Not provided'}", f"Issue category: {case.get('issue_category') or 'Not provided'}", f"Problem: {case['problem']}"]
    else:
        details = [f"Case type: crop", f"Crop: {case['crop']}", f"Issue category: {case.get('issue_category') or 'Not provided'}", f"Problem: {case['problem']}"]
    for label, key in (("Symptoms / signs", "symptoms"), ("Date first noticed", "onset_date"), ("Growth stage", "crop_stage"), ("Farmer notes", "notes")):
        if case.get(key): details.append(f"{label}: {case[key]}")
    if case["observations"]:
        details.append("Follow-up observations:\n" + "\n".join(f"- {item['observation']}" for item in reversed(case["observations"])))
    retrieved = retrieve(" ".join(details))
    knowledge_context = "\n\n".join(f"SOURCE: {item['title']}\nURL: {item['url']}\nEXCERPT: {item['text']}" for item in retrieved)
    if not knowledge_context:
        knowledge_context = "No reviewed local source excerpt matched this case. Do not imply source retrieval occurred or give specific chemical treatment instructions."
    if case.get("case_type") == "livestock":
        prompt = f"""You are ShambaSense AI, a cautious livestock information assistant for smallholder farmers in Kenya. This is not veterinary diagnosis.
FARM CONTEXT:
{farm_context(profile)}
ANIMAL CASE DETAILS:
{"\n".join(details)}
REVIEWED SOURCE EXCERPTS (may be empty):
{knowledge_context}
Respond in {language}. Summarise the reported signs and list possible explanations only as possibilities. Ask focused questions about appetite, water, behaviour, age, number affected and onset where relevant. Suggest only low-risk observation and welfare steps. Do not prescribe medicines, antibiotics, dewormers, injections, chemical treatments or dosages. Do not recommend home remedies. Clearly advise prompt contact with a qualified veterinary professional for serious, worsening or unclear illness. Treat difficulty breathing, collapse or inability to stand, seizures, severe bleeding, suspected poisoning, difficult birth or several animals suddenly ill as urgent veterinary situations. Never claim a confirmed diagnosis."""
        system_content = "Be cautious and welfare-first. You are not a veterinarian. Do not prescribe veterinary medicines or dosages and do not replace a qualified veterinary professional."
    else:
        style = get_setting_value("response_style", "balanced")
        style_note = {"simple": "Use very simple language and short steps.", "detailed": "Give a structured, more detailed explanation while distinguishing evidence from uncertainty.", "balanced": "Use clear, practical explanations with concise steps."}.get(style, "Use clear, practical explanations.")
        prompt = f"""You are ShambaSense AI, a cautious agriculture information assistant for smallholder farmers in Kenya.
FARM CONTEXT:
{farm_context(profile)}
CASE DETAILS:
{"\n".join(details)}
REVIEWED SOURCE EXCERPTS (may be empty):
{knowledge_context}
Respond in {language}. {style_note} Provide: (1) a short summary of what the farmer reported, (2) possible explanations clearly labelled as possibilities rather than diagnosis, (3) safe observations the farmer can make next, (4) practical low-risk next steps, (5) when to contact an agricultural extension officer. Ask focused follow-up questions where information is missing. Do not invent pesticide dosages, product names, weather, soil facts or sources. Only provide treatment details supported by supplied excerpts. Never claim a confirmed diagnosis."""
        system_content = "Be careful, practical, honest about uncertainty, and accessible. Never claim a definite crop diagnosis from limited information."
    try:
        answer = chat_completion([
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt}
        ])
        if not answer:
            raise HTTPException(status_code=502, detail="The AI returned an empty assessment.")
    except HTTPException:
        raise
    except Exception as exc:
        print("Case assessment failed:", type(exc).__name__)
        raise HTTPException(status_code=502, detail="The case assessment failed. Check provider availability.")
    sources = [{"title": item["title"], "url": item["url"]} for item in retrieved]
    with db() as conn:
        conn.execute("INSERT INTO case_assessments(case_id,assessment,language,sources_json,created_at) VALUES(?,?,?,?,?)",
                     (case_id, answer, language, json.dumps(sources), utc_now()))
        conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (utc_now(), case_id))
        record_case_event(conn, case_id, "assessment_created", "AI assessment saved.")
        result = _case_detail(conn, case_id)
    return result

@app.post("/cases/{case_id}/actions")
def create_case_action(case_id: int, data: CaseActionInput):
    try:
        datetime.fromisoformat(data.due_at.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail="due_at must be an ISO date/time value.")
    title = data.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="FarmAction title cannot be blank.")
    with db() as conn:
        if not conn.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Farm case not found.")
        cur = conn.execute("INSERT INTO reminders(title,due_at,notes,completed,created_at,case_id) VALUES(?,?,?,0,?,?)",
                           (title, data.due_at, (data.notes or "").strip() or None, utc_now(), case_id))
        reminder_id = cur.lastrowid
        conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (utc_now(), case_id))
        record_case_event(conn, case_id, "action_created", f"FarmAction added: {title}")
        action = dict(conn.execute("SELECT id,title,due_at,notes,completed,created_at,case_id FROM reminders WHERE id=?", (reminder_id,)).fetchone())
    return {"action": action, "message": "Action added to FarmAction and linked to this case."}

# BuddyAI-inspired farmer workspace, learning, community, referral and inventory features.
LEARNING_MODULES = [
    {
        "id": "field-scouting", "title": "Field scouting basics", "duration": "5–7 min",
        "summary": "Practise observing crops systematically before deciding what action to take.",
        "content": "Walk the field in a consistent pattern. Check more than one part of the plot. Compare healthy-looking and affected plants. Record the crop stage, date, affected area and what you actually observe. Repeat observations so you can see whether the situation is changing.",
        "content_sw": "Pitia shamba kwa mpangilio unaofanana kila mara. Kagua sehemu zaidi ya moja. Linganisha mimea inayoonekana vizuri na iliyoathirika. Andika hatua ya ukuaji, tarehe, eneo lililoathirika na ulichoona. Rudia ukaguzi ili kujua kama hali inabadilika.",
        "source_title": "FAO – How to practice Integrated Pest Management?", "source_url": "https://www.fao.org/agriculture/crops/thematic-sitemap/theme/spi/scpi-home/managing-ecosystems/integrated-pest-management/ipm-how/en/",
        "quiz": [
            {"question": "What is the best first step when you notice possible crop damage?", "options": ["Spray immediately", "Observe and record what is happening", "Remove the whole crop"], "answer": 1, "explanation": "Careful monitoring helps establish what is happening before choosing an intervention."},
            {"question": "Why should you inspect more than one part of a field?", "options": ["To compare patterns across the plot", "To make the visit longer", "It is not useful"], "answer": 0, "explanation": "Checking different areas helps avoid basing decisions on one plant or one small patch."},
            {"question": "What should a useful field note include?", "options": ["A guess only", "Date, crop stage and observed signs", "A product brand"], "answer": 1, "explanation": "Observations and dates make changes easier to track."}
        ]
    },
    {
        "id": "integrated-pest-management", "title": "Integrated pest management", "duration": "6–8 min",
        "summary": "Understand monitoring, prevention and careful decision-making around crop pests.",
        "content": "Integrated pest management (IPM) combines crop and field observations with prevention and suitable management options. Keep monitoring the crop, consider non-chemical and ecological approaches where appropriate, and avoid treating every insect or mark as proof that spraying is needed. If a pesticide is being considered, follow Kenyan legal requirements, the product label and qualified local guidance.",
        "content_sw": "Usimamizi jumuishi wa visumbufu vya mimea (IPM) huunganisha ukaguzi wa shamba, kinga na njia zinazofaa za kudhibiti. Endelea kufuatilia mimea, zingatia njia zisizo za kemikali inapofaa, na usichukulie kila mdudu au doa kuwa sababu ya kunyunyizia dawa. Dawa inapofikiriwa, fuata sheria za Kenya, maelekezo ya lebo na ushauri wa mtaalamu anayefaa.",
        "source_title": "FAO – Integrated Pest Management", "source_url": "https://www.fao.org/pest-and-pesticide-management/ipm/integrated-pest-management/en/",
        "quiz": [
            {"question": "What is the main idea of IPM?", "options": ["Use one control method for every crop", "Combine monitoring, prevention and suitable control options", "Always spray at the first sign of insects"], "answer": 1, "explanation": "IPM considers multiple options and the local field situation."},
            {"question": "Should every insect automatically trigger a pesticide application?", "options": ["Yes", "No, monitor and assess the situation", "Only at midday"], "answer": 1, "explanation": "Monitoring helps determine whether action is needed."},
            {"question": "Where should pesticide use instructions come from?", "options": ["A guess from an AI answer", "The approved product label and qualified guidance", "A social media comment"], "answer": 1, "explanation": "Use must follow the product label and applicable local requirements."}
        ]
    },
    {
        "id": "farm-records", "title": "Useful farm records", "duration": "4–6 min",
        "summary": "Learn to keep simple records of farm problems, actions and outcomes.",
        "content": "A useful farm record separates what you observed from what you think caused it. Include a date, crop, field area, crop stage, observations, actions taken and the result at the next check. Keep input and harvest records where possible. Records help you compare seasons and explain a problem to an extension officer.",
        "content_sw": "Rekodi nzuri hutofautisha ulichoona na unachodhani kuwa chanzo. Andika tarehe, zao, eneo la shamba, hatua ya ukuaji, uchunguzi, hatua ulizochukua na matokeo ya ukaguzi unaofuata. Hifadhi rekodi za pembejeo na mavuno inapowezekana. Rekodi hukusaidia kulinganisha misimu na kueleza tatizo kwa afisa ugani.",
        "source_title": "FAO – Farmer field school approach", "source_url": "https://www.fao.org/agriculture/ippm/programme/ffs-approach/en/",
        "quiz": [
            {"question": "Which record is most useful for following a crop problem?", "options": ["Date, signs observed, action and follow-up result", "Only a crop name", "Only the farmer's guess"], "answer": 0, "explanation": "Records over time help assess whether conditions have changed."},
            {"question": "Should an observation and a suspected cause be recorded as the same thing?", "options": ["Yes", "No, keep observations separate from interpretations", "Only when using photos"], "answer": 1, "explanation": "Separating observations from interpretations reduces confusion."},
            {"question": "Who may benefit from a clear case summary?", "options": ["An agricultural extension officer", "Nobody", "Only a shopkeeper"], "answer": 0, "explanation": "A concise record can make expert follow-up more useful."}
        ]
    }
]

LEARNING_MODULES_SW_QUIZ = {
    "field-scouting": [
        {"question":"Unapoona dalili za uharibifu wa zao, hatua ya kwanza inayofaa ni ipi?", "options":["Nyunyizia dawa mara moja", "Angalia na uandike kinachoendelea", "Ng’oa mimea yote"], "explanation":"Ukaguzi makini husaidia kuelewa hali kabla ya kuchagua hatua."},
        {"question":"Kwa nini ukague sehemu zaidi ya moja ya shamba?", "options":["Ili kulinganisha hali katika maeneo tofauti", "Ili kuongeza muda wa ukaguzi", "Hakuna faida"], "explanation":"Kukagua maeneo tofauti huzuia maamuzi kutegemea mmea mmoja au sehemu ndogo."},
        {"question":"Rekodi nzuri ya shambani inapaswa kuwa na nini?", "options":["Dhana pekee", "Tarehe, hatua ya ukuaji na dalili ulizoona", "Jina la bidhaa"], "explanation":"Uchunguzi na tarehe husaidia kufuatilia mabadiliko."}
    ],
    "integrated-pest-management": [
        {"question":"Wazo kuu la usimamizi jumuishi wa visumbufu vya mimea (IPM) ni lipi?", "options":["Kutumia njia moja kwa kila zao", "Kuunganisha ukaguzi, kinga na njia zinazofaa za udhibiti", "Kunyunyizia dawa mara tu wadudu wanapoonekana"], "explanation":"IPM huzingatia njia mbalimbali na hali halisi ya shamba."},
        {"question":"Je, kila mdudu anapaswa kusababisha matumizi ya dawa moja kwa moja?", "options":["Ndiyo", "Hapana, kagua na tathmini hali kwanza", "Wakati wa mchana pekee"], "explanation":"Ukaguzi husaidia kubaini kama hatua inahitajika."},
        {"question":"Maelekezo ya kutumia dawa ya mimea yanapaswa kutoka wapi?", "options":["Makisio ya AI", "Lebo iliyoidhinishwa ya bidhaa na ushauri wa mtaalamu", "Maoni ya mitandao ya kijamii"], "explanation":"Matumizi lazima yafuate lebo ya bidhaa na masharti yanayotumika."}
    ],
    "farm-records": [
        {"question":"Ni rekodi gani inafaa zaidi kufuatilia tatizo la zao?", "options":["Tarehe, dalili, hatua iliyochukuliwa na matokeo ya ukaguzi unaofuata", "Jina la zao pekee", "Dhana ya mkulima pekee"], "explanation":"Rekodi za muda husaidia kutathmini mabadiliko."},
        {"question":"Je, uchunguzi na chanzo kinachoshukiwa vinapaswa kuandikwa kama kitu kimoja?", "options":["Ndiyo", "Hapana, vitenganishe ulichoona na tafsiri yako", "Picha zinapotumika pekee"], "explanation":"Kutenganisha uchunguzi na tafsiri hupunguza mkanganyiko."},
        {"question":"Nani anaweza kunufaika na muhtasari mzuri wa tatizo la shambani?", "options":["Afisa ugani wa kilimo", "Hakuna mtu", "Muuzaji pekee"], "explanation":"Rekodi fupi na wazi inaweza kurahisisha msaada wa kitaalamu."}
    ]
}

@app.get("/dashboard/summary")
def dashboard_summary():
    today = date.today().isoformat()
    with db() as conn:
        profile = conn.execute("SELECT farmer_name,county,main_crop FROM profile WHERE id=1").fetchone()
        open_cases = conn.execute("SELECT COUNT(*) FROM cases WHERE status IN ('open','monitoring','referred')").fetchone()[0]
        completed_actions = conn.execute("SELECT COUNT(*) FROM reminders WHERE completed=1").fetchone()[0]
        pending_actions = conn.execute("SELECT COUNT(*) FROM reminders WHERE completed=0").fetchone()[0]
        upcoming = [dict(r) for r in conn.execute("SELECT id,title,due_at,completed,case_id FROM reminders WHERE completed=0 ORDER BY due_at LIMIT 5").fetchall()]
        recent_cases = [dict(r) for r in conn.execute("SELECT id,case_ref,title,crop,case_type,species,status,updated_at FROM cases ORDER BY updated_at DESC LIMIT 5").fetchall()]
        low_stock = conn.execute("SELECT COUNT(*) FROM farm_inventory WHERE quantity<=reorder_level").fetchone()[0]
        sessions = conn.execute("SELECT COUNT(*) FROM learning_sessions").fetchone()[0]
    return {"profile":dict(profile) if profile else {}, "open_cases":open_cases, "pending_actions":pending_actions, "completed_actions":completed_actions, "upcoming_actions":upcoming, "recent_cases":recent_cases, "low_stock_items":low_stock, "learning_sessions":sessions, "as_of":today, "scope":"private account workspace (local SQLite prototype)"}

@app.get("/learning/modules")
def learning_modules():
    return [{"id":m["id"],"title":m["title"],"duration":m["duration"],"summary":m["summary"],"content":m["content"],"content_sw":m["content_sw"],"source_title":m["source_title"],"source_url":m["source_url"],"quiz":[{"question":q["question"],"options":q["options"]} for q in m["quiz"]],"quiz_sw":LEARNING_MODULES_SW_QUIZ[m["id"]]} for m in LEARNING_MODULES]

@app.post("/learning/sessions")
def save_learning_session(data: LearningSessionInput):
    module = next((m for m in LEARNING_MODULES if m["id"] == data.module_id), None)
    if module is None:
        raise HTTPException(status_code=404, detail="Learning module not found.")
    if len(data.answers) != len(module["quiz"]):
        raise HTTPException(status_code=422, detail="Submit one answer for each question.")
    if any(answer < 0 or answer >= len(q["options"]) for answer,q in zip(data.answers,module["quiz"])):
        raise HTTPException(status_code=422, detail="One or more answer choices are invalid.")
    score = sum(1 for answer,q in zip(data.answers,module["quiz"]) if answer == q["answer"])
    with db() as conn:
        cur = conn.execute("INSERT INTO learning_sessions(module_id,module_title,score,total,answers_json,completed_at) VALUES(?,?,?,?,?,?)", (module["id"],module["title"],score,len(module["quiz"]),json.dumps(data.answers),utc_now()))
        session_id = cur.lastrowid
    return {"id":session_id,"module_id":module["id"],"module_title":module["title"],"score":score,"total":len(module["quiz"]),"percent":round(score/len(module["quiz"])*100),"completed_at":utc_now(),"explanations":[q["explanation"] for q in module["quiz"]],"explanations_sw":[q["explanation"] for q in LEARNING_MODULES_SW_QUIZ[module["id"]]]}

@app.get("/learning/progress")
def learning_progress():
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM learning_sessions").fetchone()[0]
        avg = conn.execute("SELECT AVG(CASE WHEN total>0 THEN score*100.0/total END) FROM learning_sessions").fetchone()[0]
        best = conn.execute("SELECT MAX(CASE WHEN total>0 THEN ROUND(score*100.0/total) END) FROM learning_sessions").fetchone()[0]
        rows = [dict(r) for r in conn.execute("SELECT id,module_id,module_title,score,total,completed_at FROM learning_sessions ORDER BY id DESC LIMIT 8").fetchall()]
    return {"sessions":total,"average_percent":round(avg) if avg is not None else None,"best_percent":int(best) if best is not None else None,"recent":rows}

@app.post("/community/reports")
def create_community_report(data: CommunityReportInput):
    if not data.consent:
        raise HTTPException(status_code=400, detail="Consent is required before sharing a community report.")
    case_type = (data.case_type or "crop").strip().lower()
    if case_type not in {"crop", "livestock"}:
        raise HTTPException(status_code=422, detail="Choose a crop or livestock report.")
    clean_crop = (data.crop or "").strip()
    clean_species = (data.species or "").strip()
    clean_county = data.county.strip()
    clean_category = data.category.strip()
    crop_report_categories = {
        "Leaf discolouration", "Insect activity", "Visible leaf or fruit spots", "Wilting or poor growth",
        "Water or drainage concern", "Storage or post-harvest concern", "Other crop concern"
    }
    if case_type == "crop" and len(clean_crop) < 2:
        raise HTTPException(status_code=422, detail="Enter the affected crop.")
    if case_type == "livestock" and clean_species not in LIVESTOCK_SPECIES:
        raise HTTPException(status_code=422, detail="Choose the affected animal species.")
    allowed_categories = set(LIVESTOCK_ISSUES) if case_type == "livestock" else crop_report_categories
    if clean_category not in allowed_categories:
        raise HTTPException(status_code=422, detail="Choose an issue category that matches the selected crop or livestock report.")
    if not clean_county:
        raise HTTPException(status_code=422, detail="County and issue category are required.")
    crop_value = clean_crop if case_type == "crop" else "Livestock"
    with community_db() as conn:
        cur=conn.execute("INSERT INTO community_reports(crop,county,category,review_status,created_at,case_type,species) VALUES(?,?,?,?,?,?,?)",(crop_value,clean_county,clean_category,"reported",utc_now(),case_type,clean_species or None))
        report_id=cur.lastrowid
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        cutoff_iso = cutoff.isoformat(timespec="seconds")
        total=conn.execute("SELECT COUNT(*) FROM community_reports WHERE created_at>=?", (cutoff_iso,)).fetchone()[0]
        similar=conn.execute("SELECT COUNT(*) FROM community_reports WHERE case_type=? AND crop=? AND COALESCE(species,'')=COALESCE(?, '') AND county=? AND category=? AND created_at>=?",(case_type,crop_value,clean_species or None,clean_county,clean_category,cutoff_iso)).fetchone()[0]
    return {"id":report_id,"status":"reported","total_reports":total,"trend_visible":similar>=3,"message":"Your category-only report was saved. Similar categories appear in shared trends only after at least three reports are grouped together. Reports are not independently verified."}

@app.get("/community/pulse")
def community_pulse(days: int = 30):
    days=max(1,min(days,90))
    cutoff=datetime.now(timezone.utc).timestamp() - days*86400
    cutoff_iso=datetime.fromtimestamp(cutoff,timezone.utc).isoformat(timespec="seconds")
    with community_db() as conn:
        rows=conn.execute("""SELECT case_type,crop,species,county,category,COUNT(*) AS report_count,MAX(created_at) AS latest_report
            FROM community_reports WHERE created_at>=?
            GROUP BY case_type,crop,species,county,category HAVING COUNT(*)>=3
            ORDER BY report_count DESC LIMIT 30""",(cutoff_iso,)).fetchall()
        total=conn.execute("SELECT COUNT(*) FROM community_reports WHERE created_at>=?",(cutoff_iso,)).fetchone()[0]
    groups=[]
    for row in rows:
        item=dict(row)
        item["subject"] = item.get("species") if item.get("case_type")=="livestock" else item.get("crop")
        item["evidence_label"]="farmer-reported trend; not independently verified"
        groups.append(item)
    return {"days":days,"total_reports":total,"groups":groups,"privacy":"Groups with fewer than three reports are suppressed. Reports contain category details only, not farmer names, contacts or free-text descriptions."}

@app.post("/cases/{case_id}/referrals")
def create_case_referral(case_id: int, data: Optional[ReferralCreateInput] = None):
    with db() as conn:
        case=_case_detail(conn,case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Farm case not found.")
    expert_category = data.expert_category if data else ("veterinary_health" if case.get("case_type")=="livestock" else "general_extension")
    recommendation = EXPERT_CATEGORIES.get(expert_category)
    if not recommendation or case.get("case_type") not in recommendation["case_types"]:
        raise HTTPException(status_code=422, detail="Choose an expert category suitable for this case type.")
    urgency = (data.urgency if data else "routine").strip().lower()
    if urgency not in {"routine", "soon", "urgent"}:
        raise HTTPException(status_code=422, detail="Urgency must be routine, soon or urgent.")
    extra = (data.additional_context or "").strip() if data else ""
    summary_lines=["MkulimaBridge – Expert case summary",f"Reference: {case['case_ref']}",f"Case type: {case.get('case_type','crop')}",f"Recommended expertise: {recommendation['label']}",f"Suggested professional role: {recommendation['role']}",f"Farmer-selected urgency: {urgency}",f"Crop / category: {case.get('crop') or 'Not provided'}",f"Animal species: {case.get('species') or 'Not applicable'}",f"Issue category: {case.get('issue_category') or 'Not provided'}",f"Case title: {case['title']}",f"Reported problem: {case['problem']}",f"Symptoms / signs: {case.get('symptoms') or 'Not provided'}",f"First noticed: {case.get('onset_date') or 'Not provided'}",f"Crop stage: {case.get('crop_stage') or 'Not provided'}",f"Case status: {case['status']}"]
    if extra: summary_lines.append(f"Additional context for the expert: {extra}")
    if case["observations"]:
        summary_lines.append("Follow-up observations:")
        summary_lines.extend(f"- {o['observation']} ({o['created_at']})" for o in reversed(case["observations"]))
    if case["assessments"]:
        summary_lines.extend(["Latest AI assessment (decision support only):",case["assessments"][0]["assessment"]])
    if case.get("media"):
        summary_lines.append(f"Video attachments available in farmer workspace: {len(case['media'])}. Share only with consent and through a secure channel.")
    summary_lines.append("This is a farmer-prepared referral summary. No expert has been contacted or assigned automatically. AI output is not a confirmed diagnosis.")
    summary="\n".join(summary_lines)
    now=utc_now()
    with db() as conn:
        cur=conn.execute("INSERT INTO expert_referrals(case_id,case_ref,summary,status,created_at,updated_at,expert_category,recommended_role,urgency) VALUES(?,?,?,?,?,?,?,?,?)",(case_id,case["case_ref"],summary,"prepared",now,now,expert_category,recommendation["role"],urgency))
        referral_id=cur.lastrowid
        record_case_event(conn, case_id, "referral_prepared", f"Expert summary prepared for {recommendation['role']}; not sent automatically.")
    return {"id":referral_id,"case_id":case_id,"case_ref":case["case_ref"],"summary":summary,"expert_category":expert_category,"recommended_role":recommendation["role"],"urgency":urgency,"status":"prepared","message":f"Summary prepared for {recommendation['role']}. It has not been sent or assigned automatically; no expert has been contacted."}

@app.get("/referrals")
def list_referrals():
    with db() as conn:
        return [dict(r) for r in conn.execute("SELECT id,case_id,case_ref,status,expert_name,notes,expert_category,recommended_role,urgency,created_at,updated_at FROM expert_referrals ORDER BY updated_at DESC LIMIT 50").fetchall()]

@app.patch("/referrals/{referral_id}")
def update_referral(referral_id: int, data: ReferralStatusInput):
    allowed={"prepared","shared_by_farmer","response_received","closed"}
    status=data.status.strip().lower()
    if status not in allowed:
        raise HTTPException(status_code=422,detail="Unsupported referral status.")
    with db() as conn:
        cur=conn.execute("UPDATE expert_referrals SET status=?,expert_name=COALESCE(?,expert_name),notes=COALESCE(?,notes),updated_at=? WHERE id=?",(status,data.expert_name.strip() if data.expert_name else None,data.notes.strip() if data.notes else None,utc_now(),referral_id))
        if not cur.rowcount:
            raise HTTPException(status_code=404,detail="Referral record not found.")
        row=dict(conn.execute("SELECT id,case_ref,status,expert_name,notes,expert_category,recommended_role,urgency,updated_at FROM expert_referrals WHERE id=?",(referral_id,)).fetchone())
    return row

@app.get("/inventory")
def list_inventory():
    with db() as conn:
        rows=[dict(r) for r in conn.execute("SELECT * FROM farm_inventory ORDER BY name COLLATE NOCASE").fetchall()]
    for row in rows:
        row["low_stock"] = row["quantity"] <= row["reorder_level"]
    return rows

@app.post("/inventory")
def add_inventory_item(data: InventoryInput):
    now=utc_now(); values=data.model_dump()
    with db() as conn:
        cur=conn.execute("INSERT INTO farm_inventory(name,category,unit,quantity,reorder_level,notes,updated_at) VALUES(?,?,?,?,?,?,?)",(values["name"].strip(),values["category"].strip() or "Other",values["unit"].strip(),values["quantity"],values["reorder_level"],(values["notes"] or "").strip(),now))
        row=dict(conn.execute("SELECT * FROM farm_inventory WHERE id=?",(cur.lastrowid,)).fetchone())
    row["low_stock"]=row["quantity"]<=row["reorder_level"]
    return row

@app.patch("/inventory/{item_id}")
def update_inventory_item(item_id: int, data: InventoryUpdate):
    values={k:v for k,v in data.model_dump(exclude_unset=True).items()}
    if not values:
        raise HTTPException(status_code=400,detail="Provide at least one field to update.")
    for key,value in values.items():
        if isinstance(value,str): values[key]=value.strip()
    assignments=", ".join(f"{key}=?" for key in values)
    params=list(values.values())+[utc_now(),item_id]
    with db() as conn:
        cur=conn.execute(f"UPDATE farm_inventory SET {assignments},updated_at=? WHERE id=?",params)
        if not cur.rowcount: raise HTTPException(status_code=404,detail="Inventory item not found.")
        row=dict(conn.execute("SELECT * FROM farm_inventory WHERE id=?",(item_id,)).fetchone())
    row["low_stock"]=row["quantity"]<=row["reorder_level"]
    return row

@app.delete("/inventory/{item_id}")
def delete_inventory_item(item_id: int):
    with db() as conn:
        cur=conn.execute("DELETE FROM farm_inventory WHERE id=?",(item_id,))
        if not cur.rowcount: raise HTTPException(status_code=404,detail="Inventory item not found.")
    return {"message":"Inventory item deleted."}

@app.get("/supervisor/overview")
def supervisor_overview(x_supervisor_token: Optional[str] = Header(default=None, alias="X-Supervisor-Token")):
    configured=os.getenv("SUPERVISOR_ACCESS_TOKEN", "").strip()
    if not configured:
        raise HTTPException(status_code=503,detail="Supervisor overview is disabled. Configure SUPERVISOR_ACCESS_TOKEN in the server environment.")
    supplied=x_supervisor_token or ""
    if not secrets.compare_digest(supplied, configured):
        raise HTTPException(status_code=403,detail="Supervisor access denied.")
    with db() as conn:
        total_cases=conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        by_status=[dict(r) for r in conn.execute("SELECT status,COUNT(*) AS count FROM cases GROUP BY status").fetchall()]
        by_crop=[dict(r) for r in conn.execute("SELECT crop,COUNT(*) AS count FROM cases GROUP BY crop ORDER BY count DESC LIMIT 8").fetchall()]
        actions=conn.execute("SELECT COUNT(*) FROM reminders WHERE completed=0").fetchone()[0]
        low_stock=conn.execute("SELECT COUNT(*) FROM farm_inventory WHERE quantity<=reorder_level").fetchone()[0]
        reports=conn.execute("SELECT COUNT(*) FROM community_reports WHERE review_status='reported'").fetchone()[0]
        recent=[dict(r) for r in conn.execute("SELECT case_ref,crop,title,status,updated_at FROM cases ORDER BY updated_at DESC LIMIT 10").fetchall()]
    return {"cases":total_cases,"cases_by_status":by_status,"cases_by_crop":by_crop,"pending_actions":actions,"low_stock_items":low_stock,"community_reports_pending_review":reports,"recent_cases":recent,"note":"This prototype overview summarizes only the signed-in account workspace. It is not a platform-wide supervisor dashboard; deploy role-based supervisor authorization before using it for multi-farmer oversight."}

@app.get("/history")
def get_history(limit: int = 50):
    limit = max(1,min(limit,100))
    with db() as conn:
        rows = conn.execute("SELECT id,question,answer,language,created_at FROM history ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
    return [dict(row) for row in rows]

@app.delete("/history")
def clear_history():
    with db() as conn:
        conn.execute("DELETE FROM history")
    return {"message":"Question history cleared."}

@app.get("/reminders")
def get_reminders():
    with db() as conn:
        rows = conn.execute("SELECT r.id,r.title,r.due_at,r.notes,r.completed,r.created_at,r.case_id,c.case_ref,c.title AS case_title FROM reminders r LEFT JOIN cases c ON c.id=r.case_id ORDER BY r.due_at ASC").fetchall()
    return [dict(row) for row in rows]

@app.post("/reminders")
def create_reminder(reminder: ReminderInput):
    try:
        datetime.fromisoformat(reminder.due_at.replace("Z","+00:00"))
    except ValueError:
        raise HTTPException(status_code=422,detail="due_at must be an ISO date/time value.")
    with db() as conn:
        if reminder.case_id is not None and not conn.execute("SELECT id FROM cases WHERE id=?", (reminder.case_id,)).fetchone():
            raise HTTPException(status_code=404, detail="Linked farm case not found.")
        cur = conn.execute("INSERT INTO reminders(title,due_at,notes,created_at,case_id) VALUES(?,?,?,?,?)",(reminder.title.strip(),reminder.due_at,reminder.notes,utc_now(),reminder.case_id))
        reminder_id = cur.lastrowid
    return {"id":reminder_id,"title":reminder.title.strip(),"due_at":reminder.due_at,"notes":reminder.notes,"completed":0,"case_id":reminder.case_id,"message":"Reminder saved in the app. No push notification is scheduled."}

@app.patch("/reminders/{reminder_id}/complete")
def complete_reminder(reminder_id: int):
    with db() as conn:
        existing = conn.execute("SELECT case_id,title,completed FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404,detail="Reminder not found.")
        cur = conn.execute("UPDATE reminders SET completed=1-completed WHERE id=?",(reminder_id,))
        row = conn.execute("SELECT id,title,due_at,notes,completed,created_at,case_id FROM reminders WHERE id=?",(reminder_id,)).fetchone()
        if existing["case_id"] is not None:
            verb = "completed" if row["completed"] else "marked incomplete"
            record_case_event(conn, existing["case_id"], "action_updated", f"FarmAction {verb}: {existing['title']}")
            conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (utc_now(), existing["case_id"]))
    return dict(row)

@app.delete("/reminders/{reminder_id}")
def delete_reminder(reminder_id: int):
    with db() as conn:
        existing = conn.execute("SELECT case_id,title FROM reminders WHERE id=?", (reminder_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404,detail="Reminder not found.")
        conn.execute("DELETE FROM reminders WHERE id=?",(reminder_id,))
        if existing["case_id"] is not None:
            record_case_event(conn, existing["case_id"], "action_deleted", f"FarmAction deleted: {existing['title']}")
            conn.execute("UPDATE cases SET updated_at=? WHERE id=?", (utc_now(), existing["case_id"]))
    return {"message":"Reminder deleted."}
