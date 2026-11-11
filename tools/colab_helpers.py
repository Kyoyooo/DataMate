"""Helpers for the Colab notebooks: a small training subset, and the pinned vLLM environment."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def make_subset_split(split_dir: Path, out_dir: Path, per_business: int, max_questions: int) -> int:
    if not (split_dir / "answers.jsonl").is_file():
        raise ValueError("training splits only: answers.jsonl is missing")
    by_biz: dict[str, list[str]] = {}
    for line in (split_dir / "questions.jsonl").read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            by_biz.setdefault(json.loads(line)["business_id"], []).append(line)
    chosen: list[str] = []
    for biz in sorted(by_biz):
        chosen += by_biz[biz][:per_business]
        if len(chosen) >= max_questions:
            break
    chosen = chosen[:max_questions]
    ids = {json.loads(x)["id"] for x in chosen}
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("data", "rulebook.md", "calendar.csv"):
        if (split_dir / name).exists() and not (out_dir / name).exists():
            os.symlink((split_dir / name).resolve(), out_dir / name)
    (out_dir / "questions.jsonl").write_text("\n".join(chosen) + "\n", encoding="utf-8")
    answers = [x for x in (split_dir / "answers.jsonl").read_text(encoding="utf-8").splitlines()
               if x.strip() and json.loads(x)["id"] in ids]
    (out_dir / "answers.jsonl").write_text("\n".join(answers) + "\n", encoding="utf-8")
    return len(chosen)


# ---------------------------------------------------------------- pinned vLLM environment
# Colab's own Python (3.13 as of 2026-11) cannot install vllm 0.10.1.1, whose wheels declare
# Requires-Python <3.13; the reference base image runs Python 3.12 with torch 2.7.1+cu128.
# So the notebooks build a separate Python 3.12 environment with uv and run datamate and the
# vLLM servers from it. cu128 is required for Blackwell (sm_120) GPUs.

VENV = Path("/content/py312")
PYTHON = "3.12"
TORCH_BACKEND = "cu128"
VLLM_MODULE = "vllm.entrypoints.openai.api_server"
_PROBE = ("import json, platform, torch, vllm; print(json.dumps({'python': platform.python_version(), "
          "'vllm': vllm.__version__, 'torch': torch.__version__, 'cuda': torch.version.cuda, "
          "'arch_list': torch.cuda.get_arch_list(), 'cuda_available': torch.cuda.is_available(), "
          "'capability': '.'.join(map(str, torch.cuda.get_device_capability())) if torch.cuda.is_available() else None}))")


def venv_python(venv: Path = VENV) -> Path:
    return venv / "bin" / "python"


def vllm_env_commands(version: str, project: Path, venv: Path = VENV, *, create: bool,
                      host_python: str = sys.executable) -> list[list[str]]:
    """Commands that build (or update) the pinned environment; pure, so it is CPU-testable."""
    py = str(venv_python(venv))
    cmds = [[host_python, "-m", "pip", "install", "-q", "uv"]]
    if create:
        cmds.append([host_python, "-m", "uv", "venv", "--python", PYTHON, str(venv)])
    cmds.append([host_python, "-m", "uv", "pip", "install", "--python", py, f"--torch-backend={TORCH_BACKEND}",
                 f"vllm=={version}", "-r", str(project / "requirements.in")])
    cmds.append([host_python, "-m", "uv", "pip", "install", "--python", py, "--no-deps", "-e", str(project)])
    return cmds


def check_env(info: dict | None, version: str) -> list[str]:
    """Problems with a probed environment (empty list = usable)."""
    if not info:
        return ["the environment cannot import torch and vllm"]
    problems = []
    if info.get("vllm") != version:
        problems.append(f"vllm {info.get('vllm')} != pinned {version}")
    if not str(info.get("python", "")).startswith(PYTHON + "."):
        problems.append(f"python {info.get('python')} != {PYTHON}")
    if not info.get("cuda_available"):
        problems.append("torch sees no CUDA GPU")
    elif info.get("capability") == "12.0" and "sm_120" not in (info.get("arch_list") or []):
        problems.append(f"torch {info.get('torch')} has no sm_120 kernels (needs a CUDA 12.8 build)")
    return problems


def probe_env(py: Path, run=subprocess.run) -> dict | None:
    if not py.exists():
        return None
    r = run([str(py), "-c", _PROBE], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def ensure_vllm_env(version: str, project: Path, venv: Path = VENV, run=subprocess.run) -> tuple[str, dict]:
    """Return (interpreter path, probe info) of a Python 3.12 environment with ``vllm==version``,
    the project's requirements and the project itself. Builds it on the first call; afterwards
    it only re-installs the project (a fresh clone may have new requirements)."""
    py = venv_python(venv)
    info = probe_env(py, run)
    need_vllm = info is None or info.get("vllm") != version
    cmds = vllm_env_commands(version, project, venv, create=not py.exists())
    if not need_vllm:  # keep the environment; refresh only the project and its requirements
        cmds = [cmds[0], [cmds[-2][0], "-m", "uv", "pip", "install", "--python", str(py), "-r",
                          str(project / "requirements.in")], cmds[-1]]
    for cmd in cmds:
        r = run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"failed: {' '.join(cmd)}\n{(r.stdout or '')[-1500:]}\n{(r.stderr or '')[-1500:]}")
    info = probe_env(py, run)
    problems = check_env(info, version)
    if problems:
        raise RuntimeError("pinned vLLM environment is not usable: " + "; ".join(problems))
    return str(py), info  # type: ignore[return-value]
