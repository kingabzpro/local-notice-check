"""Nemotron Parse v1.2 adapter for screenshot text extraction."""

from __future__ import annotations

import base64
import gc
import io
import re
import sys
import threading
from pathlib import Path
from typing import Any

from PIL import Image

MODEL_ID = "nvidia/NVIDIA-Nemotron-Parse-v1.2"
TASK_PROMPT = "</s><s><predict_bbox><predict_classes><output_markdown><predict_no_text_in_pic>"

SUPPORTED_IMAGE_PATTERN = re.compile(
    r"^data:image/(?:png|jpeg|jpg|webp);base64,(.+)$",
    re.I | re.S,
)

_MODEL: Any | None = None
_PROCESSOR: Any | None = None
_GEN_CONFIG: Any | None = None
_POSTPROCESSING: Any | None = None
_LOCK = threading.RLock()


class OCRRuntimeError(RuntimeError):
    """A sanitized OCR failure safe to expose through the API."""


def ocr_installed() -> bool:
    try:
        from transformers import AutoModel, AutoProcessor  # noqa: F401

        return True
    except ImportError:
        return False


def decode_image_data_url(image_data_url: str) -> bytes:
    match = SUPPORTED_IMAGE_PATTERN.match(image_data_url)
    if not match:
        raise OCRRuntimeError("Unsupported image data.")
    try:
        image_bytes = base64.b64decode(match.group(1), validate=True)
    except (ValueError, TypeError) as exc:
        raise OCRRuntimeError("Invalid image data.") from exc
    if not image_bytes:
        raise OCRRuntimeError("The uploaded image is empty.")
    return image_bytes


def _load_postprocessing() -> Any:
    """Download the repo's postprocessing helpers and import them."""
    global _POSTPROCESSING
    if _POSTPROCESSING is not None:
        return _POSTPROCESSING
    try:
        from huggingface_hub import snapshot_download

        repo_dir = snapshot_download(repo_id=MODEL_ID, allow_patterns=["*.py"])
        if repo_dir not in sys.path:
            sys.path.insert(0, repo_dir)
        import postprocessing

        _POSTPROCESSING = postprocessing
        return postprocessing
    except Exception as exc:
        return None


def _get_model() -> tuple[Any, Any, Any]:
    global _MODEL, _PROCESSOR, _GEN_CONFIG
    with _LOCK:
        if _MODEL is not None:
            return _MODEL, _PROCESSOR, _GEN_CONFIG
        try:
            import torch
            from transformers import AutoModel, AutoProcessor, GenerationConfig
        except ImportError as exc:
            raise OCRRuntimeError(
                "Transformers is not installed."
            ) from exc
        try:
            _MODEL = (
                AutoModel.from_pretrained(MODEL_ID, trust_remote_code=True, dtype="auto")
                .to("cuda" if torch.cuda.is_available() else "cpu")
                .eval()
            )
            _PROCESSOR = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
            _GEN_CONFIG = GenerationConfig.from_pretrained(MODEL_ID, trust_remote_code=True)
        except Exception as exc:
            _MODEL = None
            _PROCESSOR = None
            _GEN_CONFIG = None
            raise OCRRuntimeError(
                f"Nemotron-Parse-v1.2 model could not be loaded: {exc}"
            ) from exc
        return _MODEL, _PROCESSOR, _GEN_CONFIG


def extract_text(image_data_url: str) -> str:
    """Extract text from a screenshot using Nemotron-Parse-v1.2."""
    image_bytes = decode_image_data_url(image_data_url)
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as exc:
        raise OCRRuntimeError("Could not open the uploaded image.") from exc

    model, processor, gen_config = _get_model()
    pp = _load_postprocessing()

    try:
        import torch

        device = next(model.parameters()).device
        dtype = next(model.parameters()).dtype

        inputs = processor(
            images=[image], text=TASK_PROMPT, return_tensors="pt", add_special_tokens=False
        )
        inputs = {
            k: (v.to(device, dtype) if torch.is_floating_point(v) else v.to(device))
            for k, v in inputs.items()
        }
        with torch.no_grad():
            outputs = model.generate(**inputs, generation_config=gen_config)
        generated_text = processor.batch_decode(outputs, skip_special_tokens=True)[0]

        if pp is not None:
            try:
                classes, bboxes, texts = pp.extract_classes_bboxes(generated_text)
                texts = [
                    pp.postprocess_text(t, cls=c, text_format="markdown")
                    for t, c in zip(texts, classes)
                ]
                text = "\n\n".join(t.strip() for t in texts if t.strip())
            except Exception:
                text = generated_text.strip()
        else:
            text = generated_text.strip()

        if not text:
            raise OCRRuntimeError("No readable text was found in the screenshot.")
        return text
    except OCRRuntimeError:
        raise
    except Exception as exc:
        raise OCRRuntimeError("Nemotron-Parse could not read the screenshot.") from exc


def preload_ocr() -> None:
    """Download and load the OCR model at startup."""
    _load_postprocessing()
    _get_model()


def close_ocr() -> None:
    """Release cached model for local shutdown or explicit cleanup."""
    global _MODEL, _PROCESSOR, _GEN_CONFIG, _POSTPROCESSING
    with _LOCK:
        _MODEL = None
        _PROCESSOR = None
        _GEN_CONFIG = None
        _POSTPROCESSING = None
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass
