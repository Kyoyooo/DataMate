#!/usr/bin/env python3
"""Generate notebooks/colab_bootstrap.ipynb (kept as code so it is reviewable as text)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

cells: list[tuple[str, str]] = []


def add(kind: str, text: str) -> None:
    cells.append((kind, text.strip("\n")))


add("markdown", """
# Colab quick start

Set the three values in the first cell, then **Runtime → Run all**. It sets up the project, checks it on the built-in fixture,
runs 30 training questions with your model, and prints the score. Training data only. Nothing is downloaded except the code and a few pip packages.

Put on Google Drive: `DataMate/data/train/` (training split) and `DataMate/models/<your model folder>/`.
""")

add("code", '''
MODEL_NAME = "YOUR_MODEL_FOLDER"                       # folder name under MyDrive/DataMate/models
DRIVE = "/content/drive/MyDrive/DataMate"
QUESTIONS = 30                                         # how many training questions to run
''')

add("code", '''
import json, os, shutil, subprocess, sys, time
from pathlib import Path
T0 = time.time()
def sh(cmd):
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True); print(r.stdout[-1500:], r.stderr[-800:])
    assert r.returncode == 0, f"failed: {cmd}"; return r.stdout
def run(args, **kw): return subprocess.run([sys.executable, "-m", *args], cwd="/content/DataMate", env=ENV, text=True, capture_output=True, **kw)
ENV = {**os.environ, "PYTHONPATH": "/content/DataMate/src", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONHASHSEED": "0"}

from google.colab import drive
drive.mount("/content/drive")
gpu = sh("nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv,noheader").strip()
name, mem, cap = [x.strip() for x in gpu.split(",")]
print("GPU:", name, "| compute capability", cap, "" if cap == "12.0" else "(not the competition GPU type: speed and memory numbers are only indicative)")
''')

add("code", '''
# Project code + packages
shutil.rmtree("/content/DataMate", ignore_errors=True)
sh("git clone -q https://github.com/Kyoyooo/DataMate /content/DataMate")
sh("cd /content/DataMate && pip install -q -r requirements.in && pip install -q -e . --no-deps")
sys.path[:0] = ["/content/DataMate/tools", "/content/DataMate/src"]
import colab_helpers
print("commit:", sh("cd /content/DataMate && git rev-parse --short HEAD").strip())
''')

add("code", '''
# Fixture check (no model): must say PA = 1.0000
FX = "/content/out/fixture"; shutil.rmtree(FX, ignore_errors=True)
r = run(["datamate.run", "--dev", "--config", "config/dev.json", "--data-dir", "tests/fixtures/split_mini", "--result-dir", FX, "--set", "work_dir=/content/work/fixture"])
assert r.returncode == 0, r.stderr[-800:]
print(run(["datamate.eval.score", "--pred", f"{FX}/submission.jsonl", "--answers", "tests/fixtures/split_mini/answers.jsonl"]).stdout.splitlines()[0])
''')

add("code", '''
# Copy data and model from Drive to local disk
TRAIN, MODEL = Path("/content/snap/train"), Path("/content/snap/models") / MODEL_NAME
for src, dst in ((Path(DRIVE) / "data/train", TRAIN), (Path(DRIVE) / "models" / MODEL_NAME, MODEL)):
    assert src.is_dir(), f"not found on Drive: {src}"
    if not dst.exists(): dst.parent.mkdir(parents=True, exist_ok=True); shutil.copytree(src, dst)
SUB = Path("/content/subset"); shutil.rmtree(SUB, ignore_errors=True)
print(colab_helpers.make_subset_split(TRAIN, SUB, 2, QUESTIONS), "questions selected")
''')

add("code", '''
# Real run: the model is started automatically (about 32 GB of GPU memory, like the competition GPU)
OUT = Path("/content/out/subset"); shutil.rmtree(OUT, ignore_errors=True)
frac = round(min(0.95, 32 / (float(mem.split()[0]) / 1024)), 3)
sets = {"model.path": json.dumps(str(MODEL)), "serving.gpu_memory_utilization": frac, "work_dir": json.dumps("/content/work/subset")}
args = ["datamate.run", "--dev", "--config", "config/colab.json", "--data-dir", str(SUB), "--result-dir", str(OUT)]
for k, v in sets.items(): args += ["--set", f"{k}={v}"]
r = run(args); print(r.stderr[-1500:])
assert r.returncode == 0, "run failed: see /content/out/subset/logs/replica-0.log"
print(run(["datamate.eval.score", "--pred", f"{OUT}/submission.jsonl", "--answers", f"{SUB}/answers.jsonl"]).stdout)
print(f"done in {(time.time()-T0)/60:.1f} min. Results: {OUT}")
''')

add("code", '''
# Save the results to Drive
dest = Path(DRIVE) / "runs" / time.strftime("%Y-%m-%d-%H%M"); shutil.copytree(OUT, dest); print("saved to", dest)
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
    out = Path(__file__).resolve().parents[1] / "notebooks" / "colab_bootstrap.ipynb"
    out.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}", file=sys.stderr)
