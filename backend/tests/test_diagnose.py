"""Offline tests for /diagnose. A fake classifier and fake LLM are used; no model, key or network needed."""
import io
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import backend.knowledge as knowledge
import backend.main as service
from backend.classifier import Prediction, load_image

class FakeClassifier:
    def __init__(self, preds): self.preds = preds
    def predict(self, image, top_k=3): return self.preds

class FakeGroq:
    prompts = []
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                FakeGroq.prompts.append(kwargs["messages"][-1]["content"])
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Possible late blight. Confirm symptoms first."))])

class BrokenGroq:
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs): raise RuntimeError("provider down")

CONFIDENT = [Prediction("Tomato___Late_blight", 0.91), Prediction("Tomato___Early_blight", 0.06), Prediction("Tomato___healthy", 0.03)]
UNCERTAIN = [Prediction("Tomato___Late_blight", 0.34), Prediction("Tomato___Early_blight", 0.30), Prediction("Tomato___healthy", 0.20)]

def png_bytes(size=(64, 64)):
    buf = io.BytesIO(); Image.new("RGB", size, (30, 120, 40)).save(buf, format="PNG"); return buf.getvalue()

def post(client, data=None, content_type="image/png", **form):
    return client.post("/diagnose", files={"image": ("leaf.png", data if data is not None else png_bytes(), content_type)}, data=form)

def setup_function():
    service.DB_PATH = Path(tempfile.gettempdir()) / "shambasense_test_diagnose.db"
    if service.DB_PATH.exists(): service.DB_PATH.unlink()
    service.init_db()
    service.client = FakeGroq()
    service.disease_classifier = FakeClassifier(CONFIDENT)
    FakeGroq.prompts.clear()
    knowledge.CORPUS_PATH = Path(tempfile.gettempdir()) / "shambasense_test_kb.json"
    knowledge.CORPUS_PATH.write_text(json.dumps({"documents": [
        {"title": "Late blight guide", "url": "https://example.org/late-blight", "text": "Reviewed excerpt about late blight symptoms.", "labels": ["Tomato___Late_blight"]},
        {"title": "Maize planting", "url": "https://example.org/maize", "text": "Unrelated maize planting notes."}]}))

def teardown_function():
    for path in (service.DB_PATH, knowledge.CORPUS_PATH):
        if path.exists(): path.unlink()

client = TestClient(service.app)

def test_not_configured_returns_503():
    service.disease_classifier = None
    assert post(client).status_code == 503

def test_confident_prediction_uses_label_matched_knowledge():
    body = post(client, language="Kiswahili").json()
    assert body["status"] == "confident"
    assert body["predictions"][0]["display_label"] == "Tomato - Late blight"
    assert body["retrieval_used"] is True and body["sources"][0]["url"] == "https://example.org/late-blight"
    assert body["answer"] and body["language"] == "Kiswahili"
    assert "Reviewed excerpt about late blight" in FakeGroq.prompts[0]
    assert "Maize planting" not in FakeGroq.prompts[0]
    assert len(client.get("/history").json()) == 1

def test_low_confidence_skips_knowledge_and_warns_in_prompt():
    service.disease_classifier = FakeClassifier(UNCERTAIN)
    body = post(client).json()
    assert body["status"] == "uncertain" and body["retrieval_used"] is False
    assert "CONFIDENCE IS LOW" in FakeGroq.prompts[0]

def test_llm_failure_still_returns_classifier_results():
    service.client = BrokenGroq()
    body = post(client).json()
    assert body["answer"] is None and body["predictions"] and "warning" in body
    assert client.get("/history").json() == []

def test_no_llm_configured_still_returns_predictions():
    service.client = None
    body = post(client).json()
    assert body["answer"] is None and "warning" in body

def test_rejects_wrong_type_corrupt_and_oversized():
    assert post(client, content_type="text/plain").status_code == 415
    assert post(client, data=b"not an image").status_code == 422
    assert post(client, data=b"\x00" * (5 * 1024 * 1024 + 10)).status_code == 413

def test_rejects_tiny_image():
    with pytest.raises(ValueError):
        load_image(png_bytes((8, 8)))

def test_health_reports_classifier():
    assert client.get("/health").json()["classifier_configured"] is True
    service.disease_classifier = None
    assert client.get("/health").json()["classifier_configured"] is False

def test_label_retrieval_falls_back_to_keywords():
    docs = knowledge.retrieve_for_labels(["Maize___Common_rust"])
    assert docs == []  # nothing about maize rust; unrelated maize doc must not be pushed as a match

def test_keyword_fallback_matches_when_most_label_words_appear():
    knowledge.CORPUS_PATH.write_text(json.dumps({"documents": [
        {"title": "Common rust in maize", "url": "https://example.org/rust", "text": "Reviewed notes on common rust symptoms in maize leaves."}]}))
    docs = knowledge.retrieve_for_labels(["Maize___Common_rust"])
    assert docs and docs[0]["matched_by"] == "text"
