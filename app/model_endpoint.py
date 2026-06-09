"""In-process llama.cpp model endpoint for local and ZeroGPU inference."""

from __future__ import annotations

import gc
import importlib.util
import json
import re
import threading
import time
from pathlib import Path
from typing import Any

import spaces
from huggingface_hub import hf_hub_download

from app.config import ModelConfig, model_config
from app.ocr import OCRRuntimeError, extract_text, ocr_installed
from app.prompts import SYSTEM_PROMPT
from app.schema import OUTPUT_SCHEMA, normalize_assessment

_MODEL: Any | None = None
_MODEL_KEY: ModelConfig | None = None
_MODEL_LOCK = threading.RLock()
_LAST_DIAGNOSTIC = ""


class ModelRuntimeError(RuntimeError):
    """A sanitized local model failure safe to expose through the API."""


def model_status() -> dict[str, Any]:
    config = model_config()
    installed = importlib.util.find_spec("llama_cpp") is not None
    configured = bool(config.model_path or (config.repo_id and config.filename))
    ready = installed and configured
    status = {
        "connected": ready,
        "label": (
            "Local models ready: MiniCPM5-1B Q8 + Nemotron OCR v2"
            if ready
            else "Local model setup required"
        ),
        "mode": "minicpm5_llama_cpp",
        "model": config.source,
        "reasoning": config.enable_thinking,
        "ocr": {
            "model": "nvidia/nemotron-ocr-v2",
            "installed": ocr_installed(),
            "languages": ["en", "zh", "ja", "ko", "ru"],
            "urdu_supported": False,
            "roman_urdu": "best_effort_latin_script",
        },
        "privacy": "Inputs stay in this process and are not sent to a model API.",
    }
    if _LAST_DIAGNOSTIC:
        status["diagnostic"] = _LAST_DIAGNOSTIC
    return status


def prepare_model_files() -> Path:
    """Download the GGUF on CPU before the first GPU allocation."""
    config = model_config()
    if config.model_path:
        path = Path(config.model_path).expanduser().resolve()
        if not path.is_file():
            raise ModelRuntimeError(f"MODEL_PATH does not exist: {path}")
        return path
    try:
        return Path(
            hf_hub_download(
                repo_id=config.repo_id,
                filename=config.filename,
            )
        )
    except Exception as exc:
        raise ModelRuntimeError("Unable to download the configured GGUF model.") from exc


def _build_model(config: ModelConfig) -> Any:
    try:
        from llama_cpp import Llama
    except ImportError as exc:
        raise ModelRuntimeError("llama-cpp-python is not installed.") from exc

    model_path = prepare_model_files()
    try:
        return Llama(
            model_path=str(model_path),
            n_ctx=config.n_ctx,
            n_batch=config.n_batch,
            n_threads=config.n_threads,
            n_gpu_layers=config.n_gpu_layers,
            chat_template_kwargs={
                "enable_thinking": config.enable_thinking,
            },
            verbose=config.verbose,
        )
    except Exception as exc:
        raise ModelRuntimeError("The local GGUF model could not be loaded.") from exc


def _get_persistent_model(config: ModelConfig) -> Any:
    global _MODEL, _MODEL_KEY
    with _MODEL_LOCK:
        if _MODEL is None or _MODEL_KEY != config:
            close_model()
            _MODEL = _build_model(config)
            _MODEL_KEY = config
        return _MODEL


def close_model() -> None:
    global _MODEL, _MODEL_KEY
    with _MODEL_LOCK:
        model, _MODEL, _MODEL_KEY = _MODEL, None, None
        if model is not None:
            close = getattr(model, "close", None)
            if callable(close):
                close()
        gc.collect()


def _parse_model_json(content: str) -> dict[str, Any]:
    candidate = re.sub(r"<think>.*?</think>", "", content, flags=re.I | re.S).strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.I)
        candidate = re.sub(r"\s*```$", "", candidate)
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, re.S)
        if not match:
            raise ValueError("Model did not return JSON.") from None
        value = json.loads(match.group(0))
    return normalize_assessment(value)


def _run_completion(
    model: Any,
    text: str,
    output_language: str,
) -> dict[str, Any]:
    language = (
        "Write all user-facing JSON values in clear Urdu script."
        if output_language == "ur"
        else "Write all user-facing JSON values in simple English."
    )
    prompt = (
        "Assess this Pakistani notice or message for scam risk. "
        f"{language}\n\nMessage text:\n{text.strip()}"
    )
    config = model_config()
    request: dict[str, Any] = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "top_p": 0.9,
        "max_tokens": 1200,
        "response_format": {
            "type": "json_object",
            "schema": OUTPUT_SCHEMA,
        },
    }
    completion = model.create_chat_completion(
        **request,
    )
    try:
        content = completion["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Model returned an invalid completion.") from exc
    if not content:
        raise ValueError("Model returned an empty response.")
    return _parse_model_json(str(content))


@spaces.GPU(duration=120)
def call_model(
    text: str,
    image_data_url: str = "",
    output_language: str = "en",
) -> dict[str, Any]:
    """Run one local inference inside a ZeroGPU allocation when available."""
    global _LAST_DIAGNOSTIC
    config = model_config()
    input_text = text.strip()
    if image_data_url:
        try:
            ocr_text = extract_text(image_data_url)
        except OCRRuntimeError as exc:
            raise ModelRuntimeError(str(exc)) from exc
        input_text = (
            f"{input_text}\n\nText extracted from screenshot:\n{ocr_text}"
            if input_text
            else ocr_text
        )
    if not input_text:
        raise ModelRuntimeError("No readable notice text was supplied.")
    attempts = config.max_attempts
    last_error: Exception | None = None
    for attempt in range(attempts):
        ephemeral_model: Any | None = None
        try:
            model = (
                _get_persistent_model(config)
                if config.keep_loaded
                else _build_model(config)
            )
            if not config.keep_loaded:
                ephemeral_model = model
            return _run_completion(model, input_text, output_language)
        except ModelRuntimeError:
            raise
        except (RuntimeError, ValueError) as exc:
            _LAST_DIAGNOSTIC = f"{type(exc).__name__}: {exc}"[:500]
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(config.retry_delay_seconds)
        finally:
            if ephemeral_model is not None:
                close = getattr(ephemeral_model, "close", None)
                if callable(close):
                    close()
                del ephemeral_model
                gc.collect()
    raise ModelRuntimeError("The local model returned an invalid response.") from last_error
