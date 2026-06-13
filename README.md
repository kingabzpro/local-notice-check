<div align="center">

<img src="static/mark.svg" alt="NoticeCheck logo" width="88">

# NoticeCheck

**Review suspicious Pakistani messages and screenshots before you click, pay, or reply.**

[![Hugging Face Space](https://img.shields.io/badge/Live_Demo-Hugging_Face-FFD21E?logo=huggingface&logoColor=black)](https://huggingface.co/spaces/build-small-hackathon/noticecheck)
[![Docker](https://img.shields.io/badge/Run_Locally-Docker_Compose-2496ED?logo=docker&logoColor=white)](#run-locally)
[![CUDA](https://img.shields.io/badge/GPU-NVIDIA_CUDA-76B900?logo=nvidia&logoColor=white)](#requirements)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

[**Try the live demo**](https://huggingface.co/spaces/build-small-hackathon/noticecheck)
·
[**Read the field notes**](docs/field-notes.md)
·
[**View the trace dataset**](https://huggingface.co/datasets/build-small-hackathon/pakistan-notice-helper-traces)

</div>

![NoticeCheck demo](docs/app-demo.gif)

## About

NoticeCheck is the local-capable version of my earlier
[Pakistan Notice Helper](https://huggingface.co/spaces/build-small-hackathon/pakistan-notice-helper),
created for the Hugging Face Hackathon.

It reviews suspicious Pakistani SMS messages, bank alerts, bills, courier
notices, challans, emails, and screenshots. Each assessment provides:

- a clear risk label
- an evidence-based explanation
- warning signs and pressure tactics
- safer next steps
- a short reply draft when replying is appropriate

The hosted demo runs on Hugging Face ZeroGPU. The same Transformers pipeline can
run privately on a local NVIDIA GPU with Docker Compose.

## How It Works

```text
Text or screenshot
        |
        +--> NVIDIA Nemotron-Parse v1.2 extracts screenshot text
        |
        v
MiniCPM5-1B produces a structured risk assessment
        |
        v
Risk label, red flags, safe actions, and optional reply
```

| Component | Technology |
| --- | --- |
| Reasoning model | `openbmb/MiniCPM5-1B` |
| Screenshot OCR | `nvidia/NVIDIA-Nemotron-Parse-v1.2` |
| Inference | PyTorch and Transformers |
| Hosted compute | Hugging Face ZeroGPU |
| Local compute | NVIDIA CUDA through Docker Compose |
| Interface | Custom Gradio, HTML, CSS, and JavaScript |

## Run Locally

### Requirements

- Docker Engine with Docker Compose 2.30 or newer
- a supported NVIDIA GPU and current NVIDIA driver
- NVIDIA Container Toolkit on Linux
- enough disk space and VRAM for both models

Start the application:

```bash
docker compose up --build
```

Open <http://localhost:7860>.

The first startup downloads both models. Files are retained in a Docker volume,
so later starts do not download them again.

Optional `.env` values:

```dotenv
NOTICECHECK_PORT=7860
TRANSFORMERS_MODEL_REPO=openbmb/MiniCPM5-1B
MODEL_ENABLE_THINKING=0
HF_TOKEN=
```

Stop the application:

```bash
docker compose down
```

Remove the containers and downloaded model volumes:

```bash
docker compose down --volumes
```

## Privacy

Local Docker inference does not send notices or screenshots to a remote model
API. Trace publishing is optional and excludes raw text, screenshots, OCR text,
links, identifiers, and complete model responses.

See the [trace dataset card](traces/dataset_card.md) for the schema and privacy
rules.

## Language

The interface and generated assessments are English-only. Screenshot OCR may
detect other languages, but Urdu output is not currently supported.

## Project Links

- [Live Hugging Face Space](https://huggingface.co/spaces/build-small-hackathon/noticecheck)
- [Privacy-safe trace dataset](https://huggingface.co/datasets/build-small-hackathon/pakistan-notice-helper-traces)
- [Field notes: making NoticeCheck fully local](docs/field-notes.md)
- [LinkedIn project post](https://www.linkedin.com/posts/1abidaliawan_huggingfacehackathon-huggingface-ai-ugcPost-7471594790506192896--_53/)

## Safety

NoticeCheck is decision support, not proof that a sender is genuine. Never share
OTPs, PINs, passwords, CVVs, CNIC numbers, or card details. Verify suspicious
messages through an official website, app, statement, card, or independently
located helpline.

## License

Released under the [MIT License](LICENSE).
