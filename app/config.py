"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "static"
EXAMPLE_CACHE_PATH = ROOT / "data" / "example_assessments.json"


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ModelConfig:
    repo_id: str
    filename: str
    model_path: str
    n_ctx: int
    n_batch: int
    n_threads: int
    n_gpu_layers: int
    max_attempts: int
    retry_delay_seconds: float
    verbose: bool
    keep_loaded: bool
    enable_thinking: bool

    @property
    def source(self) -> str:
        return self.model_path or f"{self.repo_id}/{self.filename}"


def model_config() -> ModelConfig:
    """Return llama.cpp settings for local and Hugging Face Space runs."""
    on_space = bool(os.getenv("SPACE_ID"))
    return ModelConfig(
        repo_id=os.getenv(
            "MODEL_REPO_ID",
            "openbmb/MiniCPM5-1B-GGUF",
        ).strip(),
        filename=os.getenv(
            "MODEL_FILENAME",
            "MiniCPM5-1B-Q8_0.gguf",
        ).strip(),
        model_path=os.getenv("MODEL_PATH", "").strip(),
        n_ctx=max(2048, int(os.getenv("MODEL_CONTEXT_SIZE", "8192"))),
        n_batch=max(128, int(os.getenv("MODEL_BATCH_SIZE", "512"))),
        n_threads=max(1, int(os.getenv("MODEL_THREADS", str(os.cpu_count() or 4)))),
        n_gpu_layers=int(os.getenv("MODEL_GPU_LAYERS", "0")),
        max_attempts=max(1, int(os.getenv("MODEL_MAX_ATTEMPTS", "2"))),
        retry_delay_seconds=max(
            0.0,
            float(os.getenv("MODEL_RETRY_DELAY_SECONDS", "1")),
        ),
        verbose=_env_bool("MODEL_VERBOSE", False),
        keep_loaded=_env_bool("MODEL_KEEP_LOADED", not on_space),
        enable_thinking=_env_bool("MODEL_ENABLE_THINKING", False),
    )
