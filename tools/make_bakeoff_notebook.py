#!/usr/bin/env python3
"""Generate notebooks/BAKEOFF_G4.ipynb (kept as code so it is reviewable as text)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

cells: list[tuple[str, str]] = []


def add(kind: str, text: str) -> None:
    cells.append((kind, text.strip("\n")))


add("markdown", """
# Model bake-off (GPU part only)

**Run all, once.** This notebook only does what needs the GPU: it serves each candidate model and runs the same held-out training businesses twice,
then runs the determinism experiments (batch size, prefix cache, `VLLM_BATCH_INVARIANT`, structured outputs) on a small subset.
Everything is saved to Google Drive under `DataMate/bakeoff/`.

**The analysis runs on your own computer, without a GPU:**
`python tools/bakeoff_report.py --runs <downloaded bakeoff folder>` prints PA, determinism and throughput per candidate, and the experiment table.
Licence, release date and parameter count are checked there too (`--verify`).

Only manual step: put `train.zip` into `MyDrive/DataMate/`. The candidates below are **examples**; the model decision is the team lead's.
""")

add("code", '''
CANDIDATES = ["Qwen/Qwen3-8B"]          # EXAMPLES (Hugging Face repo ids). Add more, e.g. "Qwen/Qwen3-14B-FP8"
VLLM_VERSION = "0.10.1.1"               # same vLLM as the reference base image (M4-01)
FOLD = 0                                # held-out = whole businesses of this fold (0..4)
DETERMINISM_QUESTIONS_PER_BUSINESS = 6  # size of the subset for the determinism experiments
DRIVE = "/content/drive/MyDrive/DataMate"
''')

add("code", '''
# 1. Basics: Drive, GPU, vLLM, project code
import json, os, re, shutil, subprocess, sys, time, zipfile
from pathlib import Path
T0 = time.time()
def sh(cmd, tail=1200):
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True); print(r.stdout[-tail:], r.stderr[-600:])
    assert r.returncode == 0, f"failed: {cmd}"; return r.stdout
from google.colab import drive
drive.mount("/content/drive"); Path(DRIVE).mkdir(parents=True, exist_ok=True)
gpu_name, gpu_mem, cap = [x.strip() for x in sh("nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv,noheader").strip().split(",")]
TOTAL_GIB = float(gpu_mem.split()[0]) / 1024
print("GPU:", gpu_name, "| compute capability", cap, "" if cap == "12.0" else "(not the competition GPU type: results are only indicative)")
shutil.rmtree("/content/DataMate", ignore_errors=True)
sh("git clone -q https://github.com/Kyoyooo/DataMate /content/DataMate")
sys.path[:0] = ["/content/DataMate/tools"]
import bakeoff, colab_helpers
# vLLM pinned to the base image version, in its own Python 3.12 environment (Colab's Python is too new for it)
PY, PYINFO = colab_helpers.ensure_vllm_env(VLLM_VERSION, Path("/content/DataMate")); print(PYINFO)
COMMIT = sh("cd /content/DataMate && git rev-parse HEAD").strip(); print("commit:", COMMIT)
''')

add("code", '''
# 2. Training data (from MyDrive/DataMate/train.zip) and the held-out businesses
TRAIN = Path("/content/snap/train"); TRAIN.parent.mkdir(parents=True, exist_ok=True)
if not TRAIN.exists():
    zp = Path(DRIVE) / "train.zip"; assert zp.is_file(), f"Put train.zip into {DRIVE}/ on Google Drive, then run this cell again."
    with zipfile.ZipFile(zp) as z: z.extractall(TRAIN.parent)
SPLIT, DET = Path("/content/heldout"), Path("/content/det_subset")
for d in (SPLIT, DET): shutil.rmtree(d, ignore_errors=True)
held_out = bakeoff.make_fold_split(TRAIN, SPLIT, FOLD, 5)
bakeoff.make_fold_split(TRAIN, DET, FOLD, 5, DETERMINISM_QUESTIONS_PER_BUSINESS)
print(len(held_out), "held-out businesses")
''')

add("code", '''
# 3. Models: from Drive, or downloaded once (EXAMPLES) and kept on Drive
from huggingface_hub import snapshot_download
MODELS = {}
for repo in CANDIDATES:
    name = repo.split("/")[-1]; local = Path("/content/snap/models") / name; saved = Path(DRIVE) / "models" / name
    if not local.exists():
        local.parent.mkdir(parents=True, exist_ok=True)
        if saved.is_dir(): shutil.copytree(saved, local)
        else: snapshot_download(repo, local_dir=str(local)); shutil.copytree(local, saved)
    MODELS[name] = local
print(list(MODELS))
''')

add("code", '''
# 4. Run helper: the model server starts automatically (memory limited to about 32 GB, like the competition GPU)
OUT_ROOT = Path(DRIVE) / "bakeoff" / time.strftime("%Y-%m-%d-%H%M"); (OUT_ROOT / "runs").mkdir(parents=True, exist_ok=True)
ENV = {**os.environ, "PYTHONPATH": "/content/DataMate/src", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONHASHSEED": "0"}
def run_once(name, tag, split, **over):
    out = Path("/content/runs") / f"{name}-{tag}"; shutil.rmtree(out, ignore_errors=True)
    serving = {"gpu_memory_utilization": bakeoff.gpu_memory_fraction(TOTAL_GIB, 32.0), "max_num_seqs": over.pop("max_num_seqs", 64),
               "enable_prefix_caching": over.pop("enable_prefix_caching", True), "env": over.pop("env", {}),
               "vllm_command": [PY, "-m", colab_helpers.VLLM_MODULE]}
    cfg = {"work_dir": f"/content/work/{name}-{tag}", "model": {"path": str(MODELS[name]), "structured_outputs": over.pop("structured_outputs", True)},
           "serving": {**json.loads(Path("/content/DataMate/config/colab.json").read_text())["serving"], **serving},
           "concurrency": {"questions_per_replica": over.pop("questions_per_replica", 24), "setup_workers": 4}, "exec_limits": {"workers": 8},
           "solver": {"tokenizer": "model"}}
    assert not over, over
    p = Path("/content/configs") / f"{name}-{tag}.json"; p.parent.mkdir(exist_ok=True); p.write_text(json.dumps(cfg))
    t = time.time(); r = subprocess.run([PY, "-m", "datamate.run", "--config", str(p), "--data-dir", str(split), "--result-dir", str(out)],
                                        cwd="/content/DataMate", env=ENV, text=True, capture_output=True)
    print(f"{name} {tag}: exit {r.returncode}, {time.time()-t:.0f}s", r.stderr[-300:])
    if out.exists(): shutil.copytree(out, OUT_ROOT / "runs" / out.name, dirs_exist_ok=True)   # keep even failed runs
    return r.returncode
''')

add("code", '''
# 5. Each candidate: two identical runs on the held-out businesses
status = {}
for name in MODELS:
    status[f"{name}-A1"] = run_once(name, "A1", SPLIT); status[f"{name}-A2"] = run_once(name, "A2", SPLIT)
''')

add("code", '''
# 6. Determinism experiments on the first candidate: each variant twice on the small subset
VARIANTS = {"baseline": {}, "serial": {"max_num_seqs": 1, "questions_per_replica": 1}, "no-prefix-cache": {"enable_prefix_caching": False},
            "batch-invariant": {"env": {"VLLM_BATCH_INVARIANT": "1"}}, "no-structured-outputs": {"structured_outputs": False}}
first = next(iter(MODELS))
for v, over in VARIANTS.items():
    status[f"{first}-D-{v}-1"] = run_once(first, f"D-{v}-1", DET, **dict(over)); status[f"{first}-D-{v}-2"] = run_once(first, f"D-{v}-2", DET, **dict(over))
''')

add("code", '''
# 7. Save a description of what ran, then download the folder (or open it from Drive on your computer)
shutil.copy(SPLIT / "answers.jsonl", OUT_ROOT / "answers.jsonl"); shutil.copy(DET / "answers.jsonl", OUT_ROOT / "answers_det.jsonl")
(OUT_ROOT / "meta.json").write_text(json.dumps({"commit": COMMIT, "python_env": PYINFO, "gpu": gpu_name, "compute_capability": cap, "candidates": CANDIDATES,
    "models": {k: str(v.name) for k, v in MODELS.items()}, "variants": list(VARIANTS), "fold": FOLD, "exit_codes": status,
    "minutes": round((time.time() - T0) / 60, 1)}, indent=2))
print("saved to", OUT_ROOT, "\\nNext, on your own computer: python tools/bakeoff_report.py --runs <that folder> --verify")
''')


def build() -> dict:
    nb_cells = []
    for kind, text in cells:
        c = {"cell_type": kind, "metadata": {}, "source": text.splitlines(keepends=True)}
        if kind == "code":
            c.update(execution_count=None, outputs=[])
        nb_cells.append(c)
    return {"cells": nb_cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python",
            "name": "python3"}, "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "notebooks" / "BAKEOFF_G4.ipynb"
    out.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}", file=sys.stderr)
