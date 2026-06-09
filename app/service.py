"""Notice assessment orchestration."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from app import model_endpoint
from app.config import EXAMPLE_CACHE_PATH
from app.schema import normalize_assessment
from app.trace import queue_trace


def load_example_cache() -> dict[str, dict[str, Any]]:
    try:
        document = json.loads(EXAMPLE_CACHE_PATH.read_text(encoding="utf-8"))
        examples = document["examples"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid example cache: {exc}") from exc
    if not isinstance(examples, dict):
        raise RuntimeError("Invalid example cache: examples must be an object.")
    return {
        str(example_id): normalize_assessment(assessment)
        for example_id, assessment in examples.items()
    }


EXAMPLE_ASSESSMENTS = load_example_cache()


def parse_model_json(
    content: str,
    telemetry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse model JSON; retained as a testable public helper."""
    telemetry = telemetry if telemetry is not None else {}
    candidate = content.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.I)
        candidate = re.sub(r"\s*```$", "", candidate)
    parse_started = time.perf_counter()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", candidate, re.S)
        if not match:
            raise ValueError("Model did not return JSON.") from None
        value = json.loads(match.group(0))
    telemetry["parse_ms"] = (time.perf_counter() - parse_started) * 1000
    telemetry["parse_completed"] = True
    normalize_started = time.perf_counter()
    try:
        result = normalize_assessment(value)
    finally:
        telemetry["normalize_ms"] = (
            time.perf_counter() - normalize_started
        ) * 1000
    telemetry["normalize_completed"] = True
    return result


def sanitize_model_guidance(assessment: dict[str, Any]) -> dict[str, Any]:
    """Replace unsafe or invented verification advice."""
    replacements = {
        "social media": (
            "Use contact details from an independently located official website, "
            "app, card, or statement."
        ),
        "national anti-fraud centre": (
            "Use the relevant service's official reporting channel if needed."
        ),
        "national cyber security centre": (
            "Use the relevant service's official reporting channel if needed."
        ),
    }
    sanitized_steps: list[str] = []
    for item in assessment["safe_next_steps"]:
        lowered = item.lower()
        named_reporting_body = "report" in lowered and any(
            phrase in lowered
            for phrase in (
                "authority",
                "centre",
                "center",
                "cybercrime unit",
                "cyber security",
                "anti-fraud",
            )
        )
        replacement = (
            "Use the relevant service's official reporting channel if needed."
            if named_reporting_body
            else next(
                (value for phrase, value in replacements.items() if phrase in lowered),
                item,
            )
        )
        if replacement not in sanitized_steps:
            sanitized_steps.append(replacement)
    assessment["safe_next_steps"] = sanitized_steps
    return assessment


def analyze_notice(
    text: str = "",
    image_data_url: str = "",
    example_id: str = "",
    save_trace: bool = True,
    output_language: str = "en",
) -> dict[str, Any]:
    """Analyze supplied input with the local model and optionally queue a trace."""
    text = (text or "").strip()
    image_data_url = image_data_url or ""
    example_id = (example_id or "").strip()
    output_language = "ur" if output_language == "ur" else "en"

    def finish(response: dict[str, Any]) -> dict[str, Any]:
        if save_trace:
            try:
                trace_id, queued = queue_trace(
                    text=text,
                    image_data_url=image_data_url,
                    example_id=example_id,
                    assessment=response.get("assessment"),
                )
                response["trace"] = {"trace_id": trace_id, "status": queued}
            except Exception:
                response["trace"] = {"trace_id": "", "status": "failed"}
        else:
            response["trace"] = {"trace_id": "", "status": "disabled"}
        return response

    valid_example = example_id in EXAMPLE_ASSESSMENTS
    if not text and not image_data_url and not valid_example:
        return finish(
            {
                "ok": False,
                "error": "Paste a message or upload a screenshot to continue.",
                "status": model_endpoint.model_status(),
            }
        )

    if valid_example:
        return finish(
            {
                "ok": True,
                "assessment": dict(EXAMPLE_ASSESSMENTS[example_id]),
                "status": model_endpoint.model_status(),
                "source": "cached_local_example",
            }
        )

    status = model_endpoint.model_status()
    if not status["connected"]:
        return finish(
            {
                "ok": False,
                "error": (
                    "The model runtime is not ready. Install the configured "
                    "backend and check the model configuration."
                ),
                "error_code": "modelConfigurationError",
                "status": status,
            }
        )

    try:
        result = model_endpoint.call_model(text, image_data_url, output_language)
        return finish(
            {
                "ok": True,
                "assessment": sanitize_model_guidance(result),
                "status": status,
                "source": "local_model",
            }
        )
    except model_endpoint.ModelRuntimeError as exc:
        if image_data_url and "Nemotron-Parse" in str(exc):
            message = str(exc)
            error_code = "ocrUnavailableError"
        elif image_data_url and "No readable text" in str(exc):
            message = str(exc)
            error_code = "ocrNoTextError"
        else:
            message = "The local model is unavailable or could not be loaded."
            error_code = "modelUnavailableError"
    except (RuntimeError, ValueError) as exc:
        exc_text = str(exc)
        if "ZeroGPU quota" in exc_text or "exceeded your ZeroGPU" in exc_text:
            message = "GPU quota exceeded. Please try again later or authenticate with a Hugging Face token for more quota."
            error_code = "gpuQuotaError"
        else:
            message = "The local model returned an invalid response. Please try again."
            error_code = "modelInvalidError"

    return finish(
        {
            "ok": False,
            "error": message,
            "error_code": error_code,
            "status": {**status, "connected": False, "label": "Local model unavailable"},
        }
    )
