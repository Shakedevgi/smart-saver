"""Centralised runtime configuration.

All tunables live here so we never sprinkle magic numbers / hard-coded paths
across the codebase. Override any value at runtime via environment variables
(prefix `SMART_SAVER_`) or a `.env` file in the project root.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime settings for the ingestion pipeline."""

    model_config = SettingsConfigDict(
        env_prefix="SMART_SAVER_",
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------ paths
    project_root: Path = PROJECT_ROOT
    tmp_dir: Path = PROJECT_ROOT / "data" / "tmp"

    # ----------------------------------------------------------- http client
    http_timeout_sec: int = 20
    # Modern-Chrome UA. Required for Facebook (and a few other social
    # hosts) that serve a JS "Redirecting…" interstitial to anything that
    # smells like a bot. With this UA they fall back to a static page that
    # still carries readable og: meta tags.
    http_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )
    http_accept_language: str = "en-US,en;q=0.9"

    # ---------------------------------------------------------------- whisper
    whisper_model: str = "base"           # tiny | base | small | medium | large-v3
    whisper_device: str = "cpu"           # cpu | cuda | metal (when supported)
    whisper_compute_type: str = "int8"    # int8 / int8_float16 / float16 / float32
    whisper_language: str | None = None   # None = auto-detect

    # -------------------------------------------------------------------- ocr
    ocr_languages: list[str] = Field(default_factory=lambda: ["en"])
    # "auto" picks the best torch backend available at runtime:
    #     Apple Silicon → "mps"   (Metal, ~3-5× faster than CPU on M-series)
    #     NVIDIA CUDA   → "cuda"
    #     otherwise     → cpu
    # Override with an explicit value if you want to force a backend.
    ocr_device: str = "auto"              # auto | cpu | mps | cuda
    frame_sample_interval_sec: float = 2.0
    ocr_min_confidence: float = 0.4
    ocr_max_frames: int = 60              # safety cap for very long videos

    # ------------------------------------------------------------- ollama / llm
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3"          # `ollama pull llama3` first
    ollama_temperature: float = 0.2       # low → more deterministic JSON
    ollama_num_ctx: int | None = None     # None = let Ollama pick the default
    ollama_request_timeout_sec: float = 120.0
    llm_max_input_chars: int = 12_000     # truncate aggregated_text before send

    # --------------------------------------------------------- vector storage
    chroma_path: Path = PROJECT_ROOT / "data" / "chroma"
    chroma_collection: str = "smart_saver_items"
    # Cosine distance threshold for semantic search (0.0 = perfect match,
    # 1.0 = completely unrelated). Results above this score are dropped so
    # irrelevant items never surface when nothing in the library is close
    # enough to the query.
    search_distance_threshold: float = 0.85
    # Which embedding backend Chroma should use.
    #   "default"  → chromadb's bundled ONNX all-MiniLM-L6-v2 (no daemon, ~80 MB)
    #   "ollama"   → call the local Ollama daemon; needs `ollama pull <model>`
    embedding_backend: str = "default"
    ollama_embed_model: str = "nomic-embed-text"
    chroma_telemetry: bool = False        # disable anonymized telemetry by default

    # ---------------------------------------------------------- http api server
    # 127.0.0.1 is safe for the iOS Simulator (shares host loopback).
    # Set SMART_SAVER_API_HOST=0.0.0.0 to expose on the LAN for a physical device.
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    api_cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    # ----------------------------------------------------------------- logging
    log_level: str = "INFO"


settings = Settings()
settings.tmp_dir.mkdir(parents=True, exist_ok=True)
