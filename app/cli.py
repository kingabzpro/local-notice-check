"""Command-line entrypoint for the Space and local development."""

from __future__ import annotations

import argparse
import json
import os
import sys

from app.model_endpoint import (
    ModelRuntimeError,
    call_model,
    close_model,
    model_status,
    prepare_model_files,
)
from app.ocr import close_ocr
from app.schema import REQUIRED_FIELDS, normalize_assessment
from app.server import app
from app.service import analyze_notice, sanitize_model_guidance
from app.trace import start_trace_worker


def run_self_tests() -> None:
    normalized = normalize_assessment(
        {
            "risk_label": "high",
            "simple_explanation": "This message uses a phishing link.",
            "red_flags": ["Suspicious link"],
            "safe_next_steps": ["Use the official app."],
            "reply_draft": "I will verify independently.",
        }
    )
    assert normalized["risk_label"] == "Likely scam"
    assert normalized["reply_draft"] == ""
    sanitized = sanitize_model_guidance(
        {
            "safe_next_steps": [
                "Find the official number on verified social media.",
                "Report this to the National Cyber Security Authority.",
                "Do not click the link.",
            ]
        }
    )
    sanitized_text = " ".join(sanitized["safe_next_steps"]).lower()
    assert "social media" not in sanitized_text
    assert "cyber security authority" not in sanitized_text
    cached = analyze_notice(example_id="text-bank", save_trace=False)
    assert cached["ok"] is True
    assert cached["source"] == "cached_local_example"
    assert analyze_notice("", "", save_trace=False)["ok"] is False
    print("Self-tests passed.")


def test_endpoint() -> None:
    if not model_status()["connected"]:
        raise ModelRuntimeError("The local llama.cpp runtime is not ready.")
    sample = (
        "PAKISTAN POST: Pay Rs. 85 now at http://pakpost-delivery.example/verify "
        "or your parcel will be destroyed today."
    )
    result = call_model(sample)
    missing = REQUIRED_FIELDS - result.keys()
    if missing:
        raise ModelRuntimeError(
            "Model response is missing: " + ", ".join(sorted(missing))
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("Local model test passed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--test-endpoint", action="store_true")
    parser.add_argument("--download-model", action="store_true")
    default_host = "0.0.0.0" if os.getenv("SPACE_ID") else "127.0.0.1"
    parser.add_argument(
        "--host",
        default=os.getenv("GRADIO_SERVER_NAME", default_host),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
    )
    args = parser.parse_args()
    try:
        if args.self_test:
            run_self_tests()
            return 0
        if args.test_endpoint:
            test_endpoint()
            return 0
        if args.download_model:
            print(prepare_model_files())
            return 0
        start_trace_worker()
        app.launch(server_name=args.host, server_port=args.port)
        return 0
    except (ModelRuntimeError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        close_model()
        close_ocr()
