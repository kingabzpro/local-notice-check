"""Analyze local or Hugging Face privacy-safe trace JSONL files."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from traces.runtime import DATASET_REPO, validate_trace


def load_records(paths: list[Path]) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    trace_ids: set[str] = set()
    for path in paths:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{path}:{line_number}: invalid JSON: {exc}")
                continue
            if not isinstance(record, dict):
                errors.append(f"{path}:{line_number}: Trace must be an object.")
                continue
            trace_id = record.get("trace_id")
            if trace_id in trace_ids:
                errors.append(f"{path}:{line_number}: Duplicate trace ID: {trace_id}")
            elif isinstance(trace_id, str):
                trace_ids.add(trace_id)
            errors.extend(
                f"{path}:{line_number}: {error}"
                for error in validate_trace(record)
            )
            records.append(record)
    return records, errors


def summarize(records: list[dict[str, Any]], file_count: int) -> dict[str, Any]:
    inputs = Counter(
        record.get("input")
        for record in records
        if isinstance(record.get("input"), str)
    )
    duplicate_rows = sum(count - 1 for count in inputs.values() if count > 1)
    return {
        "files": file_count,
        "rows": len(records),
        "unique_inputs": len(inputs),
        "duplicate_input_rows": duplicate_rows,
        "duplicate_input_rate": (
            round(duplicate_rows / len(records), 4) if records else 0
        ),
        "unclassified_images": sum(
            record.get("input")
            == "image: Unclassified content with no mapped signals"
            for record in records
        ),
        "unavailable_image_assessments": sum(
            record.get("input") == "image: Assessment unavailable"
            for record in records
        ),
        "incomplete_assessments": sum(
            record.get("risk_label") == "none" for record in records
        ),
        "risk_labels": dict(Counter(
            str(record.get("risk_label", "[missing]")) for record in records
        ).most_common()),
        "input_categories": dict(Counter(
            str(record.get("input_category", "[missing]")) for record in records
        ).most_common()),
        "input_types": dict(Counter(
            record["input"].split(":", 1)[0]
            for record in records
            if isinstance(record.get("input"), str)
        ).most_common()),
        "top_repeated_inputs": [
            {"count": count, "input": input_value}
            for input_value, count in inputs.most_common(10)
            if count > 1
        ],
    }


def hub_paths(repo_id: str, directory: Path) -> list[Path]:
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ImportError as exc:
        raise RuntimeError(
            "Install huggingface_hub to analyze a Hub dataset."
        ) from exc
    api = HfApi()
    filenames = [
        name
        for name in api.list_repo_files(repo_id, repo_type="dataset")
        if name.endswith(".jsonl")
    ]
    return [
        Path(hf_hub_download(
            repo_id,
            filename,
            repo_type="dataset",
            local_dir=directory,
        ))
        for filename in filenames
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--repo-id", default=DATASET_REPO)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    with TemporaryDirectory() as directory:
        paths = args.paths or hub_paths(args.repo_id, Path(directory))
        records, errors = load_records(paths)
        report = summarize(records, len(paths))
    report["validation_errors"] = len(errors)

    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Files: {report['files']}")
        print(f"Rows: {report['rows']}")
        print(f"Validation errors: {report['validation_errors']}")
        print(f"Unique inputs: {report['unique_inputs']}")
        print(
            "Repeated-input rows: "
            f"{report['duplicate_input_rows']} "
            f"({report['duplicate_input_rate']:.1%})"
        )
        print(f"Unclassified images: {report['unclassified_images']}")
        print(
            "Unavailable image assessments: "
            f"{report['unavailable_image_assessments']}"
        )
        print(f"Incomplete assessments: {report['incomplete_assessments']}")
        print(f"Risk labels: {report['risk_labels']}")
        print(f"Input categories: {report['input_categories']}")
        if errors:
            print("\n".join(errors), file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
