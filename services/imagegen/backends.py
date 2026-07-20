"""Model backends behind the fixed job API (FR-008-03, NFR-008-09).

A backend turns a GenerationJob into raw image bytes — nothing else. Swapping models is a config
change (`ImageRunnerSettings.backend`); callers never import model code (§6.2c). The production
backend drives a headless ComfyUI server over HTTP, so torch/CUDA stay in image/.venv
(NFR-008-07); this module itself is stdlib-only.

Benchmark-hardened details (developer files/image_benchmark_report.md):
- `--disable-smart-memory` — without it the second consecutive generation OOMs at text-encode;
- references are staged into ComfyUI's input dir (LoadImage resolves names against it);
- /history status is checked for execution errors (a silent poll loop hides them);
- the server is torn down in `close()` even on failure so no leaked GPU memory starves the chat
  model (FR-008-16).
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Protocol

from services.imagegen.config import ImageRunnerSettings
from services.imagegen.contract import GenerationJob


class GenerationFailed(RuntimeError):
    """One generation attempt failed (model error / OOM / timeout) — retryable (FR-008-13)."""


class ModelBackend(Protocol):
    """The whole surface a model must implement — generate bytes, then release the GPU."""

    def load(self) -> None: ...
    def generate(self, job: GenerationJob) -> bytes: ...
    def close(self) -> None: ...


# ── production backend: Rapid-AIO v23 via headless ComfyUI (benchmark verdict) ──────────────────


class ComfyUIBackend:
    """Drives the AIO checkpoint through a ComfyUI server process (the A path of the benchmark)."""

    def __init__(self, settings: ImageRunnerSettings) -> None:
        self._s = settings
        self._proc: subprocess.Popen | None = None
        self._out_dir = Path(settings.media_root) / ".comfy_out"
        self._first_gen_done = False

    # -- lifecycle (FR-008-16: clean bring-up / tear-down) --

    def load(self) -> None:
        s = self._s
        self._out_dir.mkdir(parents=True, exist_ok=True)
        self._proc = subprocess.Popen(
            [s.comfy_python, str(Path(s.comfy_dir) / "main.py"),
             "--port", str(s.comfy_port), "--disable-smart-memory",
             "--output-directory", str(self._out_dir)],
            cwd=s.comfy_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(self._url("/system_stats"), timeout=3)
                return
            except Exception:
                time.sleep(3)
        raise GenerationFailed("ComfyUI server did not become ready")

    def close(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    # -- generation --

    def generate(self, job: GenerationJob) -> bytes:
        wf = self._build_workflow(job)
        before = set(self._out_dir.glob("*.png"))
        pid = self._submit(wf)
        timeout = self._s.gen_timeout_s if self._first_gen_done else self._s.first_gen_timeout_s
        self._wait(pid, timeout)
        self._first_gen_done = True
        new = sorted(set(self._out_dir.glob("*.png")) - before)
        if not new:
            raise GenerationFailed("ComfyUI reported success but produced no output file")
        data = new[-1].read_bytes()
        for p in new:  # the archive copy is written by store.py; the staging dir stays clean
            p.unlink(missing_ok=True)
        return data

    # -- internals --

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self._s.comfy_port}{path}"

    def _build_workflow(self, job: GenerationJob) -> dict:
        wf = copy.deepcopy(json.loads(Path(self._s.workflow_path).read_text()))
        staged = self._stage_references(job)
        for node in wf.values():
            inp = node.get("inputs", {})
            for key in list(inp):
                if inp[key] == "__PROMPT__":
                    inp[key] = job.prompt
                elif inp[key] == "__REFERENCE__":
                    inp[key] = staged[0]
                elif inp[key] == "__STEPS__":
                    inp[key] = job.params.steps
                elif inp[key] == "__SEED__":
                    inp[key] = job.params.seed
            if node.get("class_type") == "KSampler":
                inp["cfg"] = job.params.cfg
            if node.get("class_type") == "EmptySD3LatentImage":
                inp["width"], inp["height"] = job.params.width, job.params.height
            if node.get("class_type") == "CheckpointLoaderSimple":
                inp["ckpt_name"] = self._s.checkpoint_name
        # extra anchors → image2/image3 ("Picture 2/3"), after the base graph is filled in
        self._bind_extra_references(wf, staged)
        return wf

    # The serving node binds image1..image3 → "Picture 1..3" (architecture.md §4.3b).
    MAX_REFERENCES = 3

    def _stage_references(self, job: GenerationJob) -> list[str]:
        """Copy ALL of the job's references into ComfyUI's input dir, in order; return staged names.

        FR-008-05: every supplied anchor must reach the model, not just the first — dropping the
        full-body anchor would throw away the anatomy signal F-009 selected. Capped at the node's
        3-image limit. Missing/absent reference → defined error (TC-FR-008-05-02)."""
        if not job.references:
            raise GenerationFailed("job has no reference image (text-to-image path not enabled)")
        comfy_input = Path(self._s.comfy_dir) / "input"
        comfy_input.mkdir(exist_ok=True)
        staged: list[str] = []
        for idx, ref in enumerate(job.references[: self.MAX_REFERENCES]):
            src = Path(ref)
            if not src.is_absolute():
                src = Path(self._s.media_root).parent / src
            if not src.exists():
                raise GenerationFailed(f"reference image not found: {src}")
            name = f"job_{job.job_key}_{idx}{src.suffix or '.png'}"
            shutil.copy2(src, comfy_input / name)
            staged.append(name)
        return staged

    def _bind_extra_references(self, wf: dict, staged: list[str]) -> None:
        """Wire references 2..N into the encoder's image2/image3 slots (FR-008-05).

        The workflow JSON ships one LoadImage (image1) as the base; extra anchors get their own
        LoadImage nodes wired into the *positive* TextEncodeQwenImageEditPlus, which the node then
        presents to the model as "Picture 2"/"Picture 3" — matching the directive F-010 emits.
        """
        if len(staged) < 2:
            return
        positive = next(
            (nid for nid, n in wf.items()
             if n.get("class_type") == "TextEncodeQwenImageEditPlus"
             and n.get("inputs", {}).get("image1") is not None),
            None,
        )
        if positive is None:
            return
        next_id = max((int(k) for k in wf if k.isdigit()), default=0)
        for slot, name in enumerate(staged[1:self.MAX_REFERENCES], start=2):
            next_id += 1
            loader = str(next_id)
            wf[loader] = {"class_type": "LoadImage", "inputs": {"image": name}}
            wf[positive]["inputs"][f"image{slot}"] = [loader, 0]

    def _submit(self, wf: dict) -> str:
        req = urllib.request.Request(
            self._url("/prompt"), data=json.dumps({"prompt": wf}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception as exc:
            raise GenerationFailed(f"ComfyUI submit failed: {exc}") from exc
        if "prompt_id" not in resp:
            raise GenerationFailed(f"ComfyUI rejected the workflow: {resp}")
        return resp["prompt_id"]

    def _wait(self, pid: str, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                hist = json.loads(urllib.request.urlopen(
                    self._url(f"/history/{pid}"), timeout=10).read())
            except Exception as exc:
                raise GenerationFailed(f"ComfyUI history poll failed: {exc}") from exc
            if pid in hist:
                status = hist[pid].get("status", {})
                if status.get("status_str") == "error":
                    raise GenerationFailed(f"ComfyUI execution error: {status}")
                return
            time.sleep(1)
        raise GenerationFailed("ComfyUI generation timed out")


# ── registry: config name → backend (FR-008-03 model swap without code change) ──────────────────


def build_backend(settings: ImageRunnerSettings) -> ModelBackend:
    name = settings.backend.strip().lower()
    if name == "comfyui-aio":
        return ComfyUIBackend(settings)
    if name == "fake":  # tests / dry runs
        from services.imagegen.testing import FakeBackend
        return FakeBackend()
    raise ValueError(f"unknown image backend: {settings.backend!r}")
