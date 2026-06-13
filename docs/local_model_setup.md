# Local CUDA model setup

The Docker Compose deployment runs the application completely locally:

- `openbmb/MiniCPM5-1B` through Transformers
- `nvidia/NVIDIA-Nemotron-Parse-v1.2` through Transformers
- PyTorch CUDA on one local NVIDIA GPU

It does not set `SPACE_ID`, request ZeroGPU, or call a remote inference API.
Internet access is required on the first run to download model files from
Hugging Face.

## Prerequisites

Use a Linux amd64 Docker host with:

- Docker Engine and Docker Compose 2.30 or newer
- an NVIDIA GPU supported by CUDA 12.8
- a current NVIDIA driver
- NVIDIA Container Toolkit configured for Docker

On Windows, use Docker Desktop with its WSL 2 backend and an NVIDIA driver that
supports CUDA in WSL.

If `git lfs` is unavailable on Ubuntu or Debian, install it first with
`sudo apt-get update && sudo apt-get install -y git-lfs`.

Confirm that NVIDIA Container Toolkit is configured and the GPU is visible
inside Docker:

```bash
docker run --rm --gpus all \
  pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime \
  python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

The command must report `True` and print the NVIDIA GPU name. If it fails,
install or repair NVIDIA Container Toolkit before starting NoticeCheck.

## Start

Clone the GitHub repository, fetch its Git LFS interface assets, verify CUDA
inside Docker, and start the application:

```bash
git clone https://github.com/kingabzpro/local-notice-check.git
cd local-notice-check

git lfs install
git lfs pull

docker run --rm --gpus all \
  pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime \
  python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"

docker compose up --build
```

The startup process preloads Nemotron-Parse before opening port `7860`, so the
first health check may take several minutes. MiniCPM5-1B loads on the first
non-cached assessment. Model files persist in the `huggingface-cache` volume.

Open <http://localhost:7860>.

## Configuration

Compose sets these required values:

```text
MODEL_RUNTIME=transformers
REQUIRE_CUDA=1
HF_HOME=/root/.cache/huggingface
```

Optional `.env` values:

```dotenv
NOTICECHECK_PORT=7860
TRANSFORMERS_MODEL_REPO=openbmb/MiniCPM5-1B
MODEL_ENABLE_THINKING=0
HF_TOKEN=
```

`REQUIRE_CUDA=1` prevents accidental CPU fallback. If Docker cannot expose the
GPU, model status reports that CUDA is unavailable and startup fails while
preloading OCR.

## Operations

View logs:

```bash
docker compose logs --follow noticecheck
```

Check the GPU from the application image:

```bash
docker compose run --rm noticecheck python -c \
  "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

Stop containers while retaining downloaded models:

```bash
docker compose down
```

Delete containers and persistent model/trace data:

```bash
docker compose down --volumes
```
