"""Language-model provider selection for ShambaSense AI.

LLM_PROVIDER=groq          (default) Groq-hosted model, key in GROQ_API_KEY, model in GROQ_MODEL.
LLM_PROVIDER=huggingface   Hugging Face Inference Providers (e.g. Gemma 4), token in HF_TOKEN,
                           model in HF_MODEL, optional HF_INFERENCE_PROVIDER (default "auto").

DIAGNOSE_USE_VISION=true   Let the model also look at the uploaded photo in /diagnose. Only honoured
                           for the huggingface provider, because it needs a vision-capable model.
                           The photo then leaves this server (see README, Data / privacy).
"""
import base64
import io
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

from PIL import Image

DEFAULT_HF_MODEL = "google/gemma-4-E4B-it"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
MAX_VISION_SIDE = 1024

# Gemma 4's thinking mode can wrap reasoning as <|channel>thought ... <channel|>; never show it to farmers.
_THOUGHT_BLOCK = re.compile(r"<\|channel\>\s*thought.*?<channel\|>", re.DOTALL)
_STRAY_TAGS = re.compile(r"<\|?/?(?:channel|think)\|?>")


@dataclass
class LLMConfig:
    provider: str          # "groq" | "huggingface"
    model: str
    client: Optional[Any]  # None when no credentials are configured
    vision: bool           # photo is sent to the model in /diagnose


def _env_true(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def load_llm() -> LLMConfig:
    """Build the configured client. Never raises, so the API still starts without credentials."""
    raw = os.getenv("LLM_PROVIDER", "groq").strip().lower()
    provider = "huggingface" if raw in {"huggingface", "hf"} else "groq"
    if raw not in {"groq", "huggingface", "hf"}:
        print(f"Unknown LLM_PROVIDER '{raw}'; falling back to groq.")

    if provider == "huggingface":
        model = os.getenv("HF_MODEL", DEFAULT_HF_MODEL)
        token = os.getenv("HF_TOKEN")
        client = None
        if token:
            try:
                from huggingface_hub import InferenceClient
                client = InferenceClient(api_key=token, provider=os.getenv("HF_INFERENCE_PROVIDER", "auto"), timeout=60)
            except Exception as exc:
                print("Hugging Face client could not be created:", type(exc).__name__)
        return LLMConfig("huggingface", model, client, _env_true("DIAGNOSE_USE_VISION"))

    model = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    key = os.getenv("GROQ_API_KEY")
    client = None
    try:
        from groq import Groq
        client = Groq(api_key=key) if key else None
    except ImportError:
        pass
    if _env_true("DIAGNOSE_USE_VISION"):
        print("DIAGNOSE_USE_VISION ignored: it needs LLM_PROVIDER=huggingface with a vision-capable model.")
    return LLMConfig("groq", model, client, False)


def request_kwargs(provider: str, model: str, messages: list, max_tokens: int, temperature: float) -> dict:
    """Chat-completion arguments; the two SDKs name the token limit differently."""
    kwargs = {"model": model, "messages": messages, "temperature": temperature}
    kwargs["max_tokens" if provider == "huggingface" else "max_completion_tokens"] = max_tokens
    return kwargs


def clean_answer(text: Optional[str]) -> str:
    """Strip any leaked reasoning blocks and surrounding whitespace."""
    if not text:
        return ""
    text = _THOUGHT_BLOCK.sub("", text)
    return _STRAY_TAGS.sub("", text).strip()


def image_data_url(image: Image.Image) -> str:
    """Re-encode as a downsized JPEG data URL. Re-encoding also drops EXIF data such as GPS location."""
    copy = image.convert("RGB")
    copy.thumbnail((MAX_VISION_SIDE, MAX_VISION_SIDE))
    buffer = io.BytesIO()
    copy.save(buffer, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
