"""Crop-disease image classification for ShambaSense AI.

Design notes
- The project package includes an ONNX model and labels for pepper, potato, and tomato classes.
  It is not loaded automatically: configure CLASSIFIER_MODEL_PATH and CLASSIFIER_LABELS_PATH.
  If no model is configured or the runtime cannot load it, /diagnose returns 503 with guidance.
- The packaged label set does not cover maize, beans, or all crops. Do not present its output as a
  general-purpose crop detector or treat a prediction as a confirmed diagnosis.
- Any object with a ``predict(image) -> list[Prediction]`` method can be plugged in (tests use a
  fake). OnnxClassifier is the built-in backend for ONNX models.
- Uploaded images are decoded in memory only; nothing is written to disk.
"""
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, UnidentifiedImageError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


@dataclass(frozen=True)
class Prediction:
    label: str
    confidence: float  # 0..1

    @property
    def display_label(self) -> str:
        return display_label(self.label)


def display_label(label: str) -> str:
    """'Tomato___Late_blight' -> 'Tomato - Late blight' (PlantVillage-style class names)."""
    parts = [p.replace("_", " ").strip() for p in label.split("___") if p.strip()]
    return " - ".join(parts) if parts else label


def load_image(data: bytes) -> Image.Image:
    """Decode untrusted upload bytes into an RGB image, or raise ValueError."""
    if not data:
        raise ValueError("The uploaded file is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("The image is larger than 5 MB.")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError, ValueError):
        raise ValueError("The file is not a readable JPEG, PNG or WebP image.")
    if min(image.size) < 32:
        raise ValueError("The image is too small to analyse. Please upload a clearer photo.")
    return image.convert("RGB")


class OnnxClassifier:
    """Image classifier backed by an ONNX model (single image input, class scores/probabilities out)."""

    def __init__(self, model_path: str, labels_path: str, input_size: int = 224, normalize: str = "imagenet"):
        import numpy as np  # local import keeps the module importable without the ML extras
        import onnxruntime as ort

        self._np = np
        labels = json.loads(Path(labels_path).read_text(encoding="utf-8"))
        if not isinstance(labels, list) or not labels or not all(isinstance(x, str) for x in labels):
            raise ValueError("Labels file must be a non-empty JSON list of class-name strings.")
        self.labels = labels
        self.input_size = input_size
        self.normalize = normalize
        self.session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        out_dim = self.session.get_outputs()[0].shape[-1]
        if isinstance(out_dim, int) and out_dim != len(labels):
            raise ValueError(f"Model has {out_dim} outputs but the labels file has {len(labels)} classes.")

    def _preprocess(self, image: Image.Image):
        np = self._np
        arr = np.asarray(image.resize((self.input_size, self.input_size), Image.BILINEAR), dtype=np.float32) / 255.0
        if self.normalize == "imagenet":
            arr = (arr - np.array(IMAGENET_MEAN, dtype=np.float32)) / np.array(IMAGENET_STD, dtype=np.float32)
        return arr.transpose(2, 0, 1)[None, ...].astype(np.float32)  # NCHW

    def _to_probabilities(self, scores):
        np = self._np
        scores = scores.astype(np.float64).reshape(-1)
        if scores.min() >= 0.0 and scores.max() <= 1.0 and abs(scores.sum() - 1.0) < 1e-3:
            return scores  # model already outputs probabilities
        exp = np.exp(scores - scores.max())
        return exp / exp.sum()

    def predict(self, image: Image.Image, top_k: int = 3) -> list[Prediction]:
        scores = self.session.run(None, {self.input_name: self._preprocess(image)})[0]
        probs = self._to_probabilities(scores)
        order = probs.argsort()[::-1][: max(1, top_k)]
        return [Prediction(self.labels[i], float(probs[i])) for i in order]


def load_classifier() -> Optional[OnnxClassifier]:
    """Build the configured classifier, or return None (never raises, so the API still starts)."""
    model_path = os.getenv("CLASSIFIER_MODEL_PATH")
    labels_path = os.getenv("CLASSIFIER_LABELS_PATH")
    if not model_path or not labels_path:
        return None
    try:
        return OnnxClassifier(
            model_path,
            labels_path,
            input_size=int(os.getenv("CLASSIFIER_INPUT_SIZE", "224")),
            normalize=os.getenv("CLASSIFIER_NORMALIZE", "imagenet").lower(),
        )
    except Exception as exc:  # missing file, missing onnxruntime, label/output mismatch...
        print("Crop classifier could not be loaded:", type(exc).__name__, exc)
        return None
