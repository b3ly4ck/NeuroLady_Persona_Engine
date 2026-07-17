"""Image-runner settings — model choice, params, window, paths all config-driven (NFR-008-10).

Environment prefix IMAGE_ (e.g. IMAGE_BACKEND=comfyui-aio). The benchmark verdict
(developer files/image_benchmark_report.md) fixed the production backend: Rapid-AIO v23 via
headless ComfyUI with --disable-smart-memory; swapping models is a config change (FR-008-03).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class ImageRunnerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IMAGE_", env_file=".env", extra="ignore")

    # Model backend behind the fixed job API (FR-008-03): "comfyui-aio" (prod) | "fake" (tests).
    backend: str = "comfyui-aio"
    # ComfyUI serving pieces (benchmark-validated path).
    comfy_dir: str = str(REPO_ROOT / "image/comfyui")
    comfy_python: str = str(REPO_ROOT / "image/.venv/bin/python")
    comfy_port: int = 8188
    workflow_path: str = str(REPO_ROOT / "image/bench_workflow_aio.json")
    checkpoint_name: str = "Qwen-Rapid-AIO-NSFW-v23.safetensors"
    # Default generation params (job payload overrides; FR-008-06). 4 steps per the benchmark.
    default_steps: int = 4
    default_cfg: float = 1.0
    default_width: int = 1024
    default_height: int = 1024
    # Media library root (§6.3): assets land in <media_root>/<slug>/photos/<MED-id>.png.
    media_root: str = str(REPO_ROOT / "media")
    # Night/media window in the persona's local time (§6.1): [start, end) hours.
    window_start_hour: int = 1
    window_end_hour: int = 8
    # Retry/backoff (FR-008-13) + resume staleness (FR-008-14).
    max_attempts: int = 3
    backoff_base_s: float = 30.0
    stale_running_s: float = 3600.0
    # Timeouts for one generation round-trip (first gen includes lazy checkpoint load).
    first_gen_timeout_s: float = 1200.0
    gen_timeout_s: float = 600.0
    # GPU handoff commands (§6.1; FR-008-15) — shell commands the scheduler runs around the batch.
    # Empty string = no-op (e.g. when the chat model is managed externally / in tests).
    chat_unload_cmd: str = ""
    chat_reload_cmd: str = ""


@lru_cache
def get_image_settings() -> ImageRunnerSettings:
    return ImageRunnerSettings()
