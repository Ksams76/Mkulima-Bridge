"""Offline tests for provider selection, Gemma 4 / Hugging Face request shape and the vision path."""
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import backend.knowledge as knowledge
import backend.llm as llm
import backend.main as service
from backend.classifier import Prediction

class FakeClassifier:
    def predict(self, image, top_k=3):
        return [Prediction("Tomato___Late_blight", 0.91), Prediction("Tomato___healthy", 0.05), Prediction("Maize___Common_rust", 0.04)]

class RecordingClient:
    """Mimics both SDKs: records every call; optionally rejects image content."""
    def __init__(self, reply="Possible late blight. Confirm symptoms first.", reject_images=False, content=None):
        self.calls, self.reply, self.reject_images = [], reply, reject_images
        outer = self
        class completions:
            @staticmethod
            def create(**kwargs):
                outer.calls.append(kwargs)
                if outer.reject_images and isinstance(kwargs["messages"][-1]["content"], list):
                    raise RuntimeError("model does not accept images")
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=outer.reply))])
        self.chat = SimpleNamespace(completions=completions)

def png_bytes():
    buf = io.BytesIO(); Image.new("RGB", (300, 200), (30, 120, 40)).save(buf, format="PNG"); return buf.getvalue()

def diagnose(client, **form):
    return client.post("/diagnose", files={"image": ("leaf.png", png_bytes(), "image/png")}, data=form)

def setup_function():
    service.DB_PATH = Path(tempfile.gettempdir()) / "shambasense_test_llm.db"
    if service.DB_PATH.exists(): service.DB_PATH.unlink()
    service.init_db()
    service.disease_classifier = FakeClassifier()
    service.LLM_PROVIDER, service.MODEL_NAME, service.VISION_ENABLED = "groq", "openai/gpt-oss-20b", False
    knowledge.CORPUS_PATH = Path(tempfile.gettempdir()) / "shambasense_test_kb_llm.json"
    knowledge.CORPUS_PATH.write_text(json.dumps({"documents": [{"title": "Late blight guide", "url": "https://example.org/lb", "text": "Reviewed late blight excerpt.", "labels": ["Tomato___Late_blight"]}]}))

def teardown_function():
    for path in (service.DB_PATH, knowledge.CORPUS_PATH):
        if path.exists(): path.unlink()
    service.LLM_PROVIDER, service.MODEL_NAME, service.VISION_ENABLED = "groq", "openai/gpt-oss-20b", False

client = TestClient(service.app)

# ---- pure helpers
def test_request_kwargs_differ_per_provider():
    groq = llm.request_kwargs("groq", "m", [], 100, 0.3)
    hf = llm.request_kwargs("huggingface", "m", [], 100, 0.3)
    assert groq["max_completion_tokens"] == 100 and "max_tokens" not in groq
    assert hf["max_tokens"] == 100 and "max_completion_tokens" not in hf

def test_clean_answer_removes_leaked_thinking():
    raw = "<|channel>thought\nThe farmer asks about blight...<channel|>Check the lower leaves first."
    assert llm.clean_answer(raw) == "Check the lower leaves first."
    assert llm.clean_answer("<|channel>thought\n<channel|>Plain answer") == "Plain answer"
    assert llm.clean_answer(None) == ""

def test_image_data_url_is_small_jpeg_without_metadata():
    big = Image.new("RGB", (3000, 2000), (10, 200, 10))
    url = llm.image_data_url(big)
    assert url.startswith("data:image/jpeg;base64,")
    import base64
    decoded = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert max(decoded.size) <= llm.MAX_VISION_SIDE and not decoded.getexif()

def test_load_llm_selection(monkeypatch):
    for name in ("GROQ_API_KEY", "HF_TOKEN", "HF_MODEL", "DIAGNOSE_USE_VISION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "huggingface")
    cfg = llm.load_llm()
    assert (cfg.provider, cfg.model, cfg.client, cfg.vision) == ("huggingface", llm.DEFAULT_HF_MODEL, None, False)
    monkeypatch.setenv("HF_TOKEN", "hf_test_token"); monkeypatch.setenv("DIAGNOSE_USE_VISION", "true"); monkeypatch.setenv("HF_MODEL", "google/gemma-4-31B-it")
    pytest.importorskip("huggingface_hub")
    cfg = llm.load_llm()
    assert cfg.client is not None and cfg.vision is True and cfg.model == "google/gemma-4-31B-it"
    monkeypatch.setenv("LLM_PROVIDER", "groq")  # vision is not allowed on groq
    cfg = llm.load_llm()
    assert cfg.provider == "groq" and cfg.vision is False
    monkeypatch.setenv("LLM_PROVIDER", "nonsense")
    assert llm.load_llm().provider == "groq"

# ---- option 1: Gemma 4 on Hugging Face as the text explainer
def test_huggingface_text_mode_uses_hf_kwargs_and_never_sends_the_photo():
    rec = RecordingClient(reply="<|channel>thought\nreasoning<channel|>Angalia majani ya chini.")
    service.client, service.LLM_PROVIDER, service.MODEL_NAME = rec, "huggingface", "google/gemma-4-E4B-it"
    body = diagnose(client, language="Kiswahili").json()
    call = rec.calls[0]
    assert call["model"] == "google/gemma-4-E4B-it" and "max_tokens" in call and "max_completion_tokens" not in call
    assert isinstance(call["messages"][-1]["content"], str)  # text only, no photo
    assert body["answer"] == "Angalia majani ya chini." and body["vision_used"] is False

def test_ask_endpoint_works_with_huggingface_provider():
    rec = RecordingClient(reply="Check drainage. Not a confirmed diagnosis.")
    service.client, service.LLM_PROVIDER = rec, "huggingface"
    response = client.post("/ask", json={"question": "Maize leaves are yellowing", "language": "English"})
    assert response.status_code == 200 and "max_tokens" in rec.calls[0]

def test_health_reports_provider_and_photo_flag():
    service.client, service.LLM_PROVIDER, service.VISION_ENABLED = RecordingClient(), "huggingface", True
    health = client.get("/health").json()
    assert health["provider"] == "Hugging Face" and health["photo_sent_to_model"] is True and health["api_key_configured"] is True

def test_not_configured_message_names_the_right_provider():
    service.client, service.LLM_PROVIDER = None, "huggingface"
    detail = client.post("/ask", json={"question": "Maize leaves are yellowing"}).json()["detail"]
    assert "HF_TOKEN" in detail

# ---- option 2: Gemma 4 also looks at the photo
def test_vision_mode_sends_photo_before_text_with_grounding_instructions():
    rec = RecordingClient()
    service.client, service.LLM_PROVIDER, service.VISION_ENABLED = rec, "huggingface", True
    body = diagnose(client).json()
    content = rec.calls[0]["messages"][-1]["content"]
    assert content[0]["type"] == "image_url" and content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert content[1]["type"] == "text" and "photo of the plant is attached" in content[1]["text"]
    assert "Reviewed late blight excerpt" in content[1]["text"] and "Tomato - Late blight (91%)" in content[1]["text"]
    assert body["vision_used"] is True and len(rec.calls) == 1

def test_vision_failure_falls_back_to_text_only():
    rec = RecordingClient(reject_images=True)
    service.client, service.LLM_PROVIDER, service.VISION_ENABLED = rec, "huggingface", True
    body = diagnose(client).json()
    assert len(rec.calls) == 2 and isinstance(rec.calls[1]["messages"][-1]["content"], str)
    assert body["answer"] and body["vision_used"] is False

def test_vision_setting_is_ignored_on_groq():
    rec = RecordingClient()
    service.client, service.LLM_PROVIDER, service.VISION_ENABLED = rec, "groq", True
    body = diagnose(client).json()
    assert isinstance(rec.calls[0]["messages"][-1]["content"], str) and body["vision_used"] is False
