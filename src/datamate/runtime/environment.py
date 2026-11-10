"""Environment fingerprint and model record for run.json (SPEC §8.5, TASKS M4-07). Owner: M4.

Everything is read from the live process and files; nothing is assumed. Missing pieces are
``null`` (e.g. no GPU on a CPU host), never invented. Package versions come from
``importlib.metadata`` without importing the heavy libraries.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any

PACKAGES = ("duckdb", "pydantic", "torch", "vllm", "transformers", "tokenizers", "openai",
            "numpy", "pandas")
ENV_KEYS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "PYTHONHASHSEED", "NCCL_P2P_DISABLE",
            "VLLM_BATCH_INVARIANT", "CUDA_VERSION", "CUDA_VISIBLE_DEVICES")


def _version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _gpus() -> list[dict[str, str]] | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,driver_version,memory.total,compute_cap",
             "--format=csv,noheader"], capture_output=True, text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    keys = ("index", "name", "driver_version", "memory_total", "compute_cap")
    return [dict(zip(keys, (x.strip() for x in line.split(",")), strict=False))
            for line in out.splitlines() if line.strip()]


def fingerprint(roots: tuple[Path, ...] = (Path("/code"),)) -> dict[str, Any]:
    lock = next((p for r in roots for p in (r / "requirements.lock",) if p.is_file()), None)
    info = next((p for r in roots for p in (r / "BUILD_INFO.json",) if p.is_file()), None)
    return {
        "python": platform.python_version(), "platform": platform.platform(),
        "machine": platform.machine(), "cpu_count": os.cpu_count(),
        "packages": {n: _version(n) for n in PACKAGES},
        "gpus": _gpus(),
        "env": {k: os.environ.get(k) for k in ENV_KEYS},
        "lock_sha256": _sha256_file(lock) if lock else None,
        "build_info": json.loads(info.read_text(encoding="utf-8")) if info else None,
    }


def model_record(path: str | None, served_name: str, backend: str,
                 revision: str | None) -> dict[str, Any]:
    """Which weights ran: file list with sizes and, if shipped, the hash of ``SHA256SUMS``."""
    rec: dict[str, Any] = {"path": path, "served_model_name": served_name, "backend": backend,
                           "revision": revision, "files": None, "sha256sums_sha256": None}
    if path and Path(path).is_dir():
        root = Path(path)
        files = sorted(p for p in root.rglob("*") if p.is_file())
        rec["files"] = [{"path": str(p.relative_to(root)), "size": p.stat().st_size}
                        for p in files][:500]
        sums = root / "SHA256SUMS"
        rec["sha256sums_sha256"] = _sha256_file(sums) if sums.is_file() else None
    return rec
