FROM pytorch/pytorch:2.9.1-cuda12.8-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/root/.cache/huggingface

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        build-essential \
        git \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY . .

RUN if grep -RIl \
        --include='*.png' \
        --include='*.jpg' \
        --include='*.jpeg' \
        --include='*.gif' \
        --include='*.webp' \
        'version https://git-lfs.github.com/spec/v1' static | grep -q .; then \
        echo >&2 "ERROR: Git LFS image assets are missing. Run 'git lfs pull' before building."; \
        exit 1; \
    fi

EXPOSE 7860

CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "7860"]
