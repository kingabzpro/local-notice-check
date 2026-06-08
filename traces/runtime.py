"""Fast, deterministic, privacy-safe pipeline tracing."""

from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRACE_ROOT = Path(os.getenv("TRACE_DIR", ROOT / "traces"))
PENDING_DIR = TRACE_ROOT / "pending"
DATASET_REPO = os.getenv(
    "HF_TRACE_DATASET_REPO",
    "build-small-hackathon/pakistan-notice-helper-traces",
)
BATCH_SIZE = max(1, int(os.getenv("TRACE_BATCH_SIZE", "20")))
FLUSH_SECONDS = max(1.0, float(os.getenv("TRACE_FLUSH_SECONDS", "60")))
MAX_QUEUE_SIZE = max(1, int(os.getenv("TRACE_MAX_QUEUE_SIZE", "5000")))

RISK_LABELS = {
    "Looks normal",
    "Verify first",
    "Suspicious",
    "Likely scam",
    "Inappropriate",
    "none",
}
SIGNAL_PATTERNS = {
    "otp": r"\b(?:otp|one[- ]time (?:pin|password)|verification code)\b|او ٹی پی",
    "cnic": r"\bcnic\b|شناختی کارڈ",
    "credentials": (
        r"\b(?:pin|password|cvv|card details?|bank details?)\b|"
        r"پاس ورڈ|کارڈ کی تفصیلات"
    ),
    "link": (
        r"(?:https?://|www\.|bit\.ly|tinyurl\.|cutt\.ly|\.xyz\b|\.top\b)|"
        r"\b(?:link|url|domain)\b|لنک"
    ),
    "urgency": (
        r"\b(?:urgent|immediately|today|now|within \d+|last warning)\b|"
        r"فوری|فوراً|آج|آخری وارننگ"
    ),
    "payment": (
        r"\b(?:pay|payment|fee|fine|transfer|send money|rs\.?|pkr)\b|"
        r"ادائیگی|جرمانہ|رقم"
    ),
    "refund_or_prize": (
        r"\b(?:refund|prize|winner|lottery|cashback|reward)\b|"
        r"انعام|ریفنڈ|قرعہ اندازی"
    ),
    "courier": (
        r"\b(?:parcel|courier|delivery|pakistan post|leopards|tcs|customs)\b|"
        r"پارسل|کوریئر|ڈیلیوری|پاکستان پوسٹ"
    ),
    "challan": (
        r"\b(?:challan|traffic fine|traffic violation|e-challan)\b|"
        r"چالان|ٹریفک جرمانہ"
    ),
    "account_threat": (
        r"\b(?:account|sim|service|electricity)\b.{0,50}"
        r"\b(?:block|blocked|suspend|closed|disconnect)\b"
    ),
    "off_platform_contact": (
        r"\b(?:move|continue|contact|chat|message)\b.{0,50}"
        r"\b(?:whatsapp|telegram|outside|another (?:app|platform)|phone number)\b|"
        r"\bwhatsapp\b|واٹس ایپ"
    ),
    "impersonation": (
        r"\b(?:claims? to be|pretends? to be|impersonat(?:e|es|ing|ion)|"
        r"fake (?:sender|branding|authority)|unverified (?:sender|identity)|"
        r"(?:sender )?identity is unverified|official branding)\b|جعلی|نقالی"
    ),
}
EXAMPLE_PROFILES = {
    "text-courier": ("text", "courier", {"link", "urgency", "payment", "courier"}),
    "text-fbr": ("text", "fbr", {"cnic", "credentials", "urgency", "refund_or_prize"}),
    "text-bank": ("text", "bank", {"otp", "urgency", "account_threat"}),
    "image-courier": ("image", "courier", {"link", "urgency", "courier"}),
    "image-mobile": ("image", "marketplace", {"credentials"}),
    "image-traffic": ("image", "traffic_challan", {"link", "urgency", "payment", "challan"}),
}
RESULT_GUIDANCE = {
    "Looks normal": (
        "No strong scam indicators were found, but verify through an official "
        "channel."
    ),
    "Verify first": (
        "Limited or ambiguous warning signs were found; verify independently."
    ),
    "Suspicious": (
        "Multiple warning signs were found; use caution and verify independently."
    ),
    "Likely scam": (
        "Strong scam indicators were found; avoid payments, links, and sharing "
        "credentials."
    ),
    "Inappropriate": "The content was not suitable for a scam-risk assessment.",
    "none": "No completed assessment result was available.",
}
CATEGORY_DISPLAY_NAMES = {
    "fbr": "FBR",
    "bank": "bank",
    "wallet": "mobile-wallet",
    "utility": "utility",
    "traffic_challan": "traffic-challan",
    "courier": "courier",
    "customs": "customs",
    "university": "education",
    "job": "job",
    "marketplace": "marketplace",
    "unknown": "unclassified",
}
SENSITIVE_VALUE_PATTERN = re.compile(
    r"\b(?:password|passcode|pin|otp|cvv|account(?: number)?|card(?: number)?|"
    r"tracking(?: id| number)?|consignment(?: id| number)?|reference(?: id| number)?)"
    r"\s*(?:is|:|#|-)?\s*[A-Za-z0-9@._/-]{2,}",
    re.I,
)
TITLE_CASE_PATTERN = re.compile(r"\b[A-Z][a-z]{2,}\b")
TRACE_FIELDS = (
    "trace_id",
    "timestamp",
    "input",
    "input_category",
    "urgency",
    "scam_tactics",
    "result_summary",
    "risk_label",
    "reply_draft_policy",
)
REPLY_DRAFT_POLICIES = {"allowed", "suppressed", "not_applicable"}
RESIDUAL_IDENTIFIER_PATTERNS = {
    "URL": re.compile(r"https?://|www\.", re.I),
    "email": re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    "CNIC": re.compile(r"\b\d{5}-\d{7}-\d\b"),
    "phone number": re.compile(r"(?<!\d)(?:\+?92[- ]?|0)?3\d{2}[- ]?\d{7}(?!\d)"),
    "account number": re.compile(r"\bPK\d{2}[A-Z0-9]{10,30}\b", re.I),
    "card number": re.compile(r"(?<!\d)(?:\d[ -]?){12,19}(?!\d)"),
}
CATEGORY_TERMS = (
    ("fbr", ("fbr", "taxpayer", "tax refund", "revenue board", "ایف بی آر", "ٹیکس")),
    (
        "bank",
        (
            "bank",
            "banking",
            "hbl",
            "ubl",
            "meezan",
            "alfalah",
            "debit card",
            "credit card",
            "بینک",
        ),
    ),
    (
        "wallet",
        (
            "easypaisa",
            "easy paisa",
            "jazzcash",
            "mobile wallet",
            "ایزی پیسہ",
            "جاز کیش",
        ),
    ),
    (
        "utility",
        (
            "electricity",
            "gas bill",
            "utility bill",
            "lesco",
            "k-electric",
            "meter",
            "بجلی",
            "گیس بل",
        ),
    ),
    (
        "traffic_challan",
        (
            "challan",
            "traffic fine",
            "traffic violation",
            "e-challan",
            "vehicle fine",
            "چالان",
            "ٹریفک جرمانہ",
        ),
    ),
    (
        "courier",
        (
            "parcel",
            "package",
            "courier",
            "delivery",
            "shipment",
            "consignment",
            "pakistan post",
            "leopards",
            "tcs",
            "پارسل",
            "کوریئر",
            "ڈیلیوری",
            "پاکستان پوسٹ",
        ),
    ),
    ("customs", ("customs", "custom duty", "import duty", "کسٹمز")),
    (
        "university",
        (
            "university",
            "admission",
            "scholarship",
            "student portal",
            "tuition",
            "hec",
            "یونیورسٹی",
            "داخلہ",
            "اسکالرشپ",
        ),
    ),
    (
        "job",
        (
            "job",
            "salary",
            "recruiter",
            "recruitment",
            "employment",
            "interview",
            "work from home",
            "نوکری",
            "تنخواہ",
        ),
    ),
    (
        "marketplace",
        (
            "buyer",
            "seller",
            "marketplace",
            "listing",
            "product",
            "whatsapp",
            "move the conversation",
            "خریدار",
            "فروخت",
            "واٹس ایپ",
        ),
    ),
)


def detect_signals(text: str, example_id: str = "") -> dict[str, bool]:
    detected = {
        name: bool(re.search(pattern, text or "", re.I | re.S))
        for name, pattern in SIGNAL_PATTERNS.items()
    }
    profile = EXAMPLE_PROFILES.get(example_id)
    if profile:
        for name in profile[2]:
            detected[name] = True
    return detected


def detect_category(text: str, signals: dict[str, bool], example_id: str = "") -> str:
    profile = EXAMPLE_PROFILES.get(example_id)
    if profile:
        return profile[1]
    if signals["challan"]:
        return "traffic_challan"
    lowered = (text or "").lower()
    for category, terms in CATEGORY_TERMS:
        if any(term in lowered for term in terms):
            return category
    if signals["courier"]:
        return "courier"
    return "unknown"


def safe_description(category: str, signals: dict[str, bool]) -> str:
    category_labels = {
        "fbr": "FBR-style",
        "bank": "Bank-style",
        "wallet": "Wallet-style",
        "utility": "Utility-style",
        "traffic_challan": "Traffic-challan-style",
        "courier": "Courier-style",
        "customs": "Customs-style",
        "university": "Education-style",
        "job": "Job-style",
        "marketplace": "Marketplace-style",
        "unknown": "Unclassified",
    }
    signal_labels = {
        "otp": "OTP",
        "cnic": "CNIC",
        "credentials": "credential",
        "link": "link",
        "urgency": "urgency",
        "payment": "payment",
        "refund_or_prize": "refund-or-prize",
        "courier": "courier",
        "challan": "challan",
        "account_threat": "account-threat",
        "off_platform_contact": "off-platform-contact",
        "impersonation": "impersonation",
    }
    active = [signal_labels[name] for name, enabled in signals.items() if enabled][:4]
    suffix = f" with {', '.join(active)} signals" if active else " with no mapped signals"
    return f"{category_labels[category]} content{suffix}"


def redact_text(text: str) -> str:
    value = re.sub(r"\s+", " ", text or "").strip()
    value = SENSITIVE_VALUE_PATTERN.sub(
        lambda match: match.group(0).split()[0] + " [REDACTED]",
        value,
    )
    replacements = (
        (r"https?://\S+|www\.\S+", "[LINK]"),
        (r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[EMAIL]"),
        (r"\b\d{5}-\d{7}-\d\b", "[CNIC]"),
        (r"(?<!\d)(?:\+?92[- ]?|0)?3\d{2}[- ]?\d{7}(?!\d)", "[PHONE]"),
        (r"\bPK\d{2}[A-Z0-9]{10,30}\b", "[ACCOUNT]"),
        (r"(?<!\d)(?:\d[ -]?){12,19}(?!\d)", "[CARD_NUMBER]"),
        (r"\b\d{3,}\b", "[NUMBER]"),
        (
            r"\b(?:address|location|house|street|road|flat)\b"
            r"[^,.;]{0,60}",
            "[ADDRESS]",
        ),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.I)
    value = TITLE_CASE_PATTERN.sub("[NAME_OR_ENTITY]", value)
    value = re.sub(
        r"(?:\[[A-Z_]+\]\s*){2,}",
        lambda match: match.group(0).strip() + " ",
        value,
    )
    return value[:500] or "[EMPTY]"


def result_summary(
    risk_label: str,
    category: str,
    signals: dict[str, bool],
) -> str:
    pattern = safe_description(category, signals)
    novelty = (
        "Unclassified pattern; this does not confirm a new scam type."
        if category == "unknown"
        else f"Known {CATEGORY_DISPLAY_NAMES[category]} pattern."
    )
    return f"{risk_label}: {pattern}. {novelty} {RESULT_GUIDANCE[risk_label]}"


def assessment_evidence(assessment: dict[str, Any] | None) -> str:
    """Return transient model evidence used only for allow-list classification."""
    if not isinstance(assessment, dict):
        return ""
    values: list[str] = [str(assessment.get("simple_explanation", ""))]
    red_flags = assessment.get("red_flags", [])
    if isinstance(red_flags, list):
        values.extend(str(item) for item in red_flags)
    return " ".join(values)[:4000]


def structured_assessment_profile(
    assessment: dict[str, Any] | None,
) -> tuple[str, dict[str, bool]] | None:
    if not isinstance(assessment, dict):
        return None
    category = assessment.get("trace_category")
    tactics = assessment.get("trace_tactics")
    if category not in CATEGORY_DISPLAY_NAMES or not isinstance(tactics, list):
        return None
    if any(tactic not in SIGNAL_PATTERNS for tactic in tactics):
        return None
    return category, {
        name: name in tactics
        for name in SIGNAL_PATTERNS
    }


def build_input_profile(
    text: str,
    image_data_url: str,
    example_id: str = "",
    assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = EXAMPLE_PROFILES.get(example_id)
    if profile:
        input_type = profile[0]
    elif image_data_url:
        input_type = "image"
    else:
        input_type = "text"
    structured_profile = (
        structured_assessment_profile(assessment)
        if input_type == "image" and not example_id
        else None
    )
    classification_text = text
    if input_type == "image" and not example_id:
        classification_text = " ".join(
            part for part in (text, assessment_evidence(assessment)) if part
        )
    signals = detect_signals(classification_text, example_id)
    category = detect_category(classification_text, signals, example_id)
    if structured_profile:
        structured_category, structured_signals = structured_profile
        confirmed_tactics = {
            name
            for name, enabled in structured_signals.items()
            if enabled and signals[name]
        }
        if (
            category == "unknown"
            and structured_category != "unknown"
            and confirmed_tactics
        ):
            category = structured_category
    tactics = [name for name, enabled in signals.items() if enabled]
    if input_type == "image" and not assessment and not example_id:
        input_description = "image: Assessment unavailable"
    else:
        input_description = f"image: {safe_description(category, signals)}"
    return {
        "input": (
            f"text: {redact_text(text)}"
            if input_type == "text"
            else input_description
        ),
        "input_category": category,
        "urgency": signals["urgency"],
        "scam_tactics": ", ".join(tactics) if tactics else "none",
    }


def build_trace_record(
    *,
    text: str,
    image_data_url: str,
    example_id: str,
    assessment: dict[str, Any] | None,
) -> dict[str, Any]:
    trace_id = str(uuid.uuid4())
    risk_label = str((assessment or {}).get("risk_label", "none"))
    if risk_label not in RISK_LABELS:
        risk_label = "none"
    input_profile = build_input_profile(
        text,
        image_data_url,
        example_id,
        assessment,
    )
    category = input_profile["input_category"]
    tactic_values = (
        []
        if input_profile["scam_tactics"] == "none"
        else input_profile["scam_tactics"].split(", ")
    )
    signals = {name: name in tactic_values for name in SIGNAL_PATTERNS}
    assessment = assessment or {}
    return {
        "trace_id": trace_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **input_profile,
        "result_summary": result_summary(risk_label, category, signals),
        "risk_label": risk_label,
        "reply_draft_policy": (
            "allowed"
            if risk_label in {"Verify first", "Suspicious"}
            else "suppressed"
            if risk_label != "none"
            else "not_applicable"
        ),
    }


def validate_trace(record: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["Trace must be an object."]
    required = set(TRACE_FIELDS)
    missing = required - record.keys()
    if missing:
        errors.append("Missing fields: " + ", ".join(sorted(missing)))
    unexpected = record.keys() - required
    if unexpected:
        errors.append("Unexpected fields: " + ", ".join(sorted(unexpected)))
    if record and next(iter(record)) != "trace_id":
        errors.append("trace_id must be the first column.")
    trace_id = record.get("trace_id")
    try:
        parsed_trace_id = uuid.UUID(trace_id) if isinstance(trace_id, str) else None
        if parsed_trace_id is None or str(parsed_trace_id) != trace_id:
            raise ValueError
    except (ValueError, AttributeError):
        errors.append("Trace ID must be a canonical UUID.")
    timestamp = record.get("timestamp")
    try:
        parsed_timestamp = (
            datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else None
        )
        if (
            parsed_timestamp is None
            or parsed_timestamp.utcoffset() != timezone.utc.utcoffset(None)
        ):
            raise ValueError
    except (ValueError, TypeError):
        errors.append("Timestamp must be an ISO 8601 UTC value.")
    input_value = record.get("input")
    if not (
        isinstance(input_value, str)
        and (
            input_value.startswith("text: ")
            or input_value.startswith("image: ")
        )
    ):
        errors.append("Input must use a fixed text: or image: description.")
    elif len(input_value) > 506:
        errors.append("Input exceeds the 500-character content limit.")
    else:
        for label, pattern in RESIDUAL_IDENTIFIER_PATTERNS.items():
            if pattern.search(input_value):
                errors.append(f"Input contains an unredacted {label}.")
    if record.get("input_category") not in CATEGORY_DISPLAY_NAMES:
        errors.append("Invalid input category.")
    if not isinstance(record.get("urgency"), bool):
        errors.append("Urgency must be boolean.")
    tactics = record.get("scam_tactics")
    tactic_values: list[str] = []
    if not isinstance(tactics, str):
        errors.append("Scam tactics must be a string.")
    else:
        tactic_values = [] if tactics == "none" else tactics.split(", ")
        if (
            any(value not in SIGNAL_PATTERNS for value in tactic_values)
            or len(tactic_values) != len(set(tactic_values))
        ):
            errors.append("Invalid scam tactics.")
    result = record.get("result_summary")
    if not isinstance(result, str) or not result or len(result) > 500:
        errors.append("Result summary must be a non-empty string of at most 500 characters.")
    if record.get("risk_label") not in RISK_LABELS:
        errors.append("Invalid risk label.")
    if record.get("reply_draft_policy") not in REPLY_DRAFT_POLICIES:
        errors.append("Invalid reply draft policy.")
    risk_label = record.get("risk_label")
    category = record.get("input_category")
    if risk_label in RISK_LABELS and category in CATEGORY_DISPLAY_NAMES:
        expected_policy = (
            "allowed"
            if risk_label in {"Verify first", "Suspicious"}
            else "suppressed"
            if risk_label != "none"
            else "not_applicable"
        )
        if record.get("reply_draft_policy") != expected_policy:
            errors.append("Reply draft policy does not match the risk label.")
        signals = {name: name in tactic_values for name in SIGNAL_PATTERNS}
        expected_summary = result_summary(risk_label, category, signals)
        if result != expected_summary:
            errors.append("Result summary does not match the deterministic fields.")
        if isinstance(input_value, str) and input_value.startswith("image: "):
            expected_input = f"image: {safe_description(category, signals)}"
            unavailable_input = (
                risk_label == "none"
                and input_value == "image: Assessment unavailable"
            )
            if input_value != expected_input and not unavailable_input:
                errors.append("Image input does not match the deterministic fields.")
    if any(isinstance(value, (dict, list)) for value in record.values()):
        errors.append("Trace columns must contain scalar values only.")
    forbidden_keys = {
        "schema_version",
        "app_commit",
        "request_source",
        "pipeline_steps",
        "cache",
        "failure",
        "text_byte_bucket",
        "text_character_bucket",
        "image_size_bucket",
        "language_hint",
        "modal",
        "exception_text_stored",
        "identifiers_stored",
        "input_storage",
        "raw_image_stored",
        "raw_input_stored",
        "raw_model_output_stored",
        "red_flag_count",
        "reply_draft_returned",
        "safe_next_step_count",
        "signal_account_threat",
        "signal_challan",
        "signal_cnic",
        "signal_courier",
        "signal_credentials",
        "signal_link",
        "signal_otp",
        "signal_payment",
        "signal_refund_or_prize",
        "raw_input",
        "raw_text",
        "image_data_url",
        "raw_model_output",
        "reply_draft",
        "simple_explanation",
        "error",
        "exception",
        "url",
        "phone",
        "account_number",
    }

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key.lower() in forbidden_keys:
                    errors.append(f"Forbidden field: {key}")
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(record)
    return sorted(set(errors))


class TracePublisher:
    def __init__(self) -> None:
        self.queue: queue.Queue[dict[str, Any]] = queue.Queue(MAX_QUEUE_SIZE)
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.counters = {
            "queued": 0,
            "persisted": 0,
            "uploaded": 0,
            "upload_failures": 0,
            "dropped": 0,
        }

    def enqueue(self, record: dict[str, Any]) -> str:
        if validate_trace(record):
            with self.lock:
                self.counters["dropped"] += 1
            return "invalid"
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            with self.lock:
                self.counters["dropped"] += 1
            return "dropped"
        with self.lock:
            self.counters["queued"] += 1
        self._ensure_worker()
        return "queued"

    def status(self) -> dict[str, Any]:
        with self.lock:
            counters = dict(self.counters)
        counters.update(
            {
                "queue_size": self.queue.qsize(),
                "pending_shards": len(list(PENDING_DIR.glob("*.jsonl")))
                if PENDING_DIR.exists()
                else 0,
                "dataset_repo": DATASET_REPO,
            }
        )
        return counters

    def _ensure_worker(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(
                target=self._worker,
                name="privacy-safe-trace-publisher",
                daemon=True,
            )
            self.thread.start()

    def _worker(self) -> None:
        batch: list[dict[str, Any]] = []
        deadline: float | None = None
        self._upload_pending()
        while True:
            timeout = (
                max(0.05, deadline - time.monotonic())
                if deadline is not None
                else FLUSH_SECONDS
            )
            try:
                record = self.queue.get(timeout=timeout)
                batch.append(record)
                if deadline is None:
                    deadline = time.monotonic() + FLUSH_SECONDS
            except queue.Empty:
                pass
            if batch and (
                len(batch) >= BATCH_SIZE
                or (deadline is not None and time.monotonic() >= deadline)
            ):
                self._persist_batch(batch)
                batch = []
                deadline = None
                self._upload_pending()

    def _persist_batch(self, records: list[dict[str, Any]]) -> None:
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        pending_count = self._pending_record_count()
        capacity = max(0, MAX_QUEUE_SIZE - pending_count)
        if capacity == 0:
            with self.lock:
                self.counters["dropped"] += len(records)
            return
        accepted = records[:capacity]
        dropped = len(records) - len(accepted)
        if dropped:
            with self.lock:
                self.counters["dropped"] += dropped
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        filename = f"trace-{timestamp}-{uuid.uuid4().hex[:8]}.jsonl"
        final_path = PENDING_DIR / filename
        temporary_path = final_path.with_suffix(".tmp")
        content = "".join(
            json.dumps(record, ensure_ascii=True) + "\n"
            for record in accepted
        )
        temporary_path.write_text(content, encoding="utf-8")
        os.replace(temporary_path, final_path)
        with self.lock:
            self.counters["persisted"] += len(accepted)

    def _pending_record_count(self) -> int:
        if not PENDING_DIR.exists():
            return 0
        count = 0
        for path in PENDING_DIR.glob("*.jsonl"):
            try:
                count += sum(
                    1
                    for line in path.read_text(encoding="utf-8").splitlines()
                    if line
                )
            except OSError:
                continue
        return count

    def _upload_pending(self) -> None:
        token = os.getenv("HF_TOKEN", "").strip()
        if not token or not PENDING_DIR.exists():
            return
        try:
            from huggingface_hub import HfApi

            api = HfApi(token=token)
            for path in sorted(PENDING_DIR.glob("*.jsonl")):
                date_path = datetime.now(timezone.utc).strftime("%Y/%m/%d")
                uploaded = False
                for attempt in range(3):
                    try:
                        api.upload_file(
                            path_or_fileobj=str(path),
                            path_in_repo=f"data/{date_path}/{path.name}",
                            repo_id=DATASET_REPO,
                            repo_type="dataset",
                            commit_message=f"Add privacy-safe trace shard {path.name}",
                        )
                        uploaded = True
                        break
                    except Exception:
                        if attempt < 2:
                            time.sleep(2**attempt)
                if not uploaded:
                    with self.lock:
                        self.counters["upload_failures"] += 1
                    return
                count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)
                path.unlink(missing_ok=True)
                with self.lock:
                    self.counters["uploaded"] += count
        except Exception:
            with self.lock:
                self.counters["upload_failures"] += 1


PUBLISHER = TracePublisher()


def start_trace_worker() -> None:
    PUBLISHER._ensure_worker()


def queue_trace(**kwargs: Any) -> tuple[str, str]:
    record = build_trace_record(**kwargs)
    return record["trace_id"], PUBLISHER.enqueue(record)


def trace_status() -> dict[str, Any]:
    return PUBLISHER.status()
