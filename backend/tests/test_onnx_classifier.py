"""Builds a tiny real ONNX model (channel means -> linear layer) to exercise OnnxClassifier end to end."""
import json

import pytest
from PIL import Image

np = pytest.importorskip("numpy")
onnx = pytest.importorskip("onnx")
pytest.importorskip("onnxruntime")
from onnx import TensorProto, helper, numpy_helper

from backend.classifier import OnnxClassifier, load_classifier

LABELS = ["Tomato___Late_blight", "Tomato___healthy", "Maize___Common_rust"]

def build_model(path, size=32):
    # class k scores high when channel k is bright: identity weights on the 3 channel means
    weights = numpy_helper.from_array(np.eye(3, dtype=np.float32) * 20.0, name="w")
    nodes = [helper.make_node("GlobalAveragePool", ["x"], ["pooled"]),
             helper.make_node("Flatten", ["pooled"], ["flat"], axis=1),
             helper.make_node("MatMul", ["flat", "w"], ["scores"])]
    graph = helper.make_graph(nodes, "tiny", [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, size, size])],
                              [helper.make_tensor_value_info("scores", TensorProto.FLOAT, [1, 3])], initializer=[weights])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.save(model, str(path))

@pytest.fixture
def files(tmp_path):
    build_model(tmp_path / "m.onnx")
    (tmp_path / "labels.json").write_text(json.dumps(LABELS))
    return tmp_path / "m.onnx", tmp_path / "labels.json"

def test_predicts_and_returns_sorted_probabilities(files):
    clf = OnnxClassifier(str(files[0]), str(files[1]), input_size=32, normalize="none")
    preds = clf.predict(Image.new("RGB", (80, 60), (250, 5, 5)))  # red image -> class 0
    assert preds[0].label == "Tomato___Late_blight" and preds[0].confidence > 0.9
    assert preds[0].confidence >= preds[1].confidence >= preds[2].confidence
    assert abs(sum(p.confidence for p in preds) - 1.0) < 1e-6

def test_label_count_mismatch_is_rejected(files, tmp_path):
    (tmp_path / "bad.json").write_text(json.dumps(["only", "two"]))
    with pytest.raises(ValueError):
        OnnxClassifier(str(files[0]), str(tmp_path / "bad.json"), input_size=32)

def test_load_classifier_from_env_and_graceful_failure(files, monkeypatch):
    monkeypatch.setenv("CLASSIFIER_MODEL_PATH", str(files[0]))
    monkeypatch.setenv("CLASSIFIER_LABELS_PATH", str(files[1]))
    monkeypatch.setenv("CLASSIFIER_INPUT_SIZE", "32")
    monkeypatch.setenv("CLASSIFIER_NORMALIZE", "none")
    assert load_classifier() is not None
    monkeypatch.setenv("CLASSIFIER_MODEL_PATH", "does-not-exist.onnx")
    assert load_classifier() is None
    monkeypatch.delenv("CLASSIFIER_MODEL_PATH")
    assert load_classifier() is None
