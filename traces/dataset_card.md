---
license: cc-by-4.0
pretty_name: NoticeCheck Privacy-Safe Traces
task_categories:
  - text-classification
language:
  - en
  - ur
tags:
  - safety
  - scams
  - pakistan
  - deterministic-traces
  - privacy
configs:
  - config_name: default
    default: true
    data_files:
      - split: train
        path: data/seed/trace_samples.jsonl
  - config_name: operational
    data_files:
      - split: train
        path: data/*/*/*/*.jsonl
---

# NoticeCheck Privacy-Safe Traces

## Purpose

This dataset contains compact, deterministic metadata about NoticeCheck
message-review requests. It does not contain hidden model reasoning or
autonomous-agent trajectories.

The hosted application uses MiniCPM5-1B through Transformers on Hugging Face
ZeroGPU, with NVIDIA Nemotron-Parse v1.2 for supported screenshots. The same
pipeline can run locally on an NVIDIA GPU with Docker Compose. Creating a trace
never makes an additional AI model call. Traces only observe the existing
request path and convert it into allow-listed categories, booleans, and fixed
descriptions. For image submissions, the existing assessment's explanation and
red flags are inspected transiently for this mapping, but their text is not
stored. The trace mapper predicts the privacy-safe image category and tactics
directly from that result summary using deterministic English/Urdu evidence
rules.

## Fields

- Trace identity: random trace ID and UTC timestamp
- `input`: aggressively redacted, length-limited text for text submissions, or
  a fixed-template `image: ...` description
- `input_category`: deterministic category such as courier, bank, or FBR
- `urgency`: deterministic boolean urgency signal
- `result_summary`: deterministic summary of the mapped pattern, whether it is
  known or unclassified, and why the risk label matters
- `scam_tactics`: readable comma-separated tactics
- Flat result columns such as `risk_label` and `reply_draft_policy`

Every dataset cell is a scalar string, number, or boolean. No column contains a
dictionary or nested object, which keeps the Hugging Face table easy to read.
`trace_id` is the first serialized column, and all detected boolean signals are
combined into the single `scam_tactics` category column.

Records do not contain pipeline steps, cache fields, app commits, failure
details, request source, schema versions, size buckets, language hints, or
model runtime metadata.

## Privacy

The dataset never stores:

- Raw message text
- Screenshots, image bytes, or base64
- URLs, phone numbers, CNICs, names, addresses, account/card numbers, or
  tracking numbers
- Model explanations, red flags, safe-step text, reply drafts, or raw model
  output
- Exceptions, credentials, tokens, or endpoint headers

Text traces store an aggressively redacted form capped at 500 characters.
Regexes remove common URLs, emails, phones, CNICs, card/account numbers,
credentials, addresses, tracking IDs, long numbers, and title-case names or
entities. Regex redaction cannot guarantee removal of every possible
identifier, so users should opt out when submitting sensitive content.

Images store only fixed descriptions. Screenshots, OCR text, model explanations,
and model red flags are not stored. Users see a checked trace disclosure in the
app and may opt out before each request.

When image analysis fails before an assessment is available, new records use
`image: Assessment unavailable`. This keeps service failures separate from
successful assessments whose content is genuinely unclassified.

## Provenance

The default configuration contains the six reviewed public examples bundled
with NoticeCheck. The `operational` configuration contains privacy-safe runtime
traces and may include successful, rejected, or failed requests.
Trace generation itself does not invoke the model.

The seed rows are illustrative examples, not an evaluation split. All six
currently have the `Likely scam` label, so they must not be used to estimate
class balance, accuracy, recall, or real-world scam prevalence.

Operational rows intentionally preserve repeated requests. Consequently,
repeated examples, unclassified image descriptions, and incomplete `none`
assessments may be common. For training or evaluation, curate the
`operational` configuration by:

- exclude `risk_label: none`
- review or exclude unclassified image rows
- deduplicate on the privacy-safe `input` and result columns
- use a task-appropriate class-balancing strategy

The source repository includes `traces/scripts/analyze_trace_dataset.py` for
schema validation and a reproducible summary of these quality indicators.

## Limitations

- Regex signals and category detection are approximate.
- Runtime frequencies may reflect testing or repeated usage, not population
  prevalence.
- Regex redaction may miss unusual personal or confidential information.
- Novelty is not researched against external threat-intelligence sources.
- The dataset cannot reproduce original messages or screenshots.
- A risk label is safety guidance, not official verification.

## Links

- App: https://huggingface.co/spaces/build-small-hackathon/noticecheck
- Source: https://github.com/kingabzpro/local-notice-check
- Field notes: https://github.com/kingabzpro/local-notice-check/blob/main/docs/field-notes.md

## License

CC BY 4.0.
