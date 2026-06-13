---
title: NoticeCheck
emoji: 🔎
author: kingabzpro
collaborators:
- Codex
colorFrom: indigo
colorTo: red
sdk: gradio
sdk_version: 6.17.3
app_file: app.py
python_version: 3.12
pinned: true
license: mit
tags:
  - track:backyard
  - sponsor:openbmb
  - sponsor:openai
  - sponsor:nvidia
  - achievement:offgrid
  - achievement:offbrand
  - transformers
  - minicpm5-1b
  - nemotron-parse
  - zerogpu
  - scam-detection
  - online-safety
  - pakistan
  - english
short_description: Review suspicious Pakistani messages before you act.
---

# NoticeCheck

This repository is the local version of the
[Pakistan Notice Helper Hugging Face Space](https://huggingface.co/spaces/build-small-hackathon/pakistan-notice-helper).
It keeps the same notice-checking purpose with a redesigned English interface.
The hosted demo uses Hugging Face ZeroGPU, while Docker Compose runs the models
on a local NVIDIA GPU.

**[Try the live demo](https://huggingface.co/spaces/build-small-hackathon/noticecheck)**

![NoticeCheck demo](docs/app-demo.gif)

NoticeCheck is a safety assistant for suspicious Pakistani messages, bills,
bank alerts, challans, courier notices, and screenshots. It returns:

- a risk label
- a short explanation based on visible evidence
- warning signs and safer next actions
- a brief reply draft when replying is appropriate

NoticeCheck does not verify the sender and does not provide legal or financial
advice. Find official contact details independently before paying, clicking,
replying, or sharing personal information.

## Runtime

```text
Text or screenshot
        |
        v
Custom Gradio Server frontend
        |
        +--> Nemotron-Parse v1.2 for screenshot text
        |
        v
MiniCPM5-1B through Transformers on ZeroGPU
        |
        v
Structured risk assessment
```

- **Reasoning:** `openbmb/MiniCPM5-1B` through Transformers
- **OCR:** `nvidia/NVIDIA-Nemotron-Parse-v1.2` through Transformers
- **Compute:** Hugging Face Spaces ZeroGPU
- **Interface:** redesigned custom HTML, CSS, and JavaScript
- **Language:** English only

The application does not use a remote model API and has no heuristic assessment
fallback. Model and OCR failures are returned explicitly.

Both models run through Transformers on the Hugging Face ZeroGPU deployment.

## Run Locally With Docker and CUDA

The included Compose setup runs the same Transformers pipeline entirely on a
local NVIDIA GPU. It does not use ZeroGPU or a remote inference API.

Prerequisites:

- Docker Engine with Docker Compose 2.30 or newer
- a supported NVIDIA GPU and current NVIDIA driver
- NVIDIA Container Toolkit when using Docker Engine on Linux
- enough GPU memory for MiniCPM5-1B and Nemotron-Parse v1.2

Start the application:

```bash
docker compose up --build
```

Open <http://localhost:7860>. The first startup takes longer because both model
repositories are downloaded. Downloads are retained in the
`huggingface-cache` Docker volume.

Optional environment overrides can be placed in a local `.env` file:

```dotenv
NOTICECHECK_PORT=7860
TRANSFORMERS_MODEL_REPO=openbmb/MiniCPM5-1B
MODEL_ENABLE_THINKING=0
HF_TOKEN=
```

Stop the application without deleting downloaded models:

```bash
docker compose down
```

To also remove the model cache and trace volumes:

```bash
docker compose down --volumes
```

## Repository Layout

```text
app.py                 Thin Space launcher
Dockerfile             Local CUDA image
compose.yaml           Local NVIDIA GPU deployment
app/
  cli.py               CLI and startup
  config.py            Environment configuration
  model_endpoint.py    Space Transformers inference
  ocr.py               Nemotron-Parse adapter
  server.py            Gradio/FastAPI routes
  service.py           Assessment orchestration
  trace.py             Trace subsystem adapter
static/                Custom frontend
traces/                Privacy-safe trace runtime and tools
experiments/           Preserved historical model experiments
tests/                 Application and trace tests
```

## English-Only Interface

This version intentionally uses an English-only interface and requests English
analysis from the model. Most notices and scam messages targeted by the project
contain English or English mixed with common local terms. The local model also
understands the task instructions and produces structured English results more
reliably than Urdu output.

Screenshot OCR may detect text from other languages, but the generated
assessment is intended to be in English. Urdu-language output is not currently
supported.

## Privacy-Safe Traces

Trace publishing is optional. Published records contain minimized,
deterministic metadata and exclude raw message text, OCR text, screenshots,
links, identifiers, and complete model responses.

```bash
python -m traces.scripts.analyze_trace_dataset
```

See [the trace dataset card](traces/dataset_card.md) for the schema and privacy
rules.

## Safety

- Redact CNIC numbers, account details, OTPs, PINs, and card information.
- Never trust a phone number or link solely because it appears in a message.
- Confirm through an official website, app, card, statement, or helpline you
  locate independently.
- Treat the output as decision support, not proof that a message is genuine.
