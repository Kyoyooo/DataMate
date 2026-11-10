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
# Colab quick start (all in one)

**Run all, once.** It sets up everything: GPU check, vLLM, the project code, the training data, the model (downloaded if you do not have it yet),
a built-in fixture check, 30 training questions with your model, and the score. Results are saved to Google Drive.

Only one manual step: put **`train.zip`** (the training split you received, 128 MB) in `MyDrive/DataMate/` on Google Drive.
The model is an **example** (`Qwen/Qwen3-8B`): change `MODEL_REPO` to try another. Which model is used for the competition is the team lead's decision;
the license, release date and size must be checked on the model card (the notebook prints the parameter count).
""")

add("code", '''
MODEL_REPO = "Qwen/Qwen3-8B"          # EXAMPLE model, Hugging Face repo id
QUESTIONS  = 30                       # how many training questions to run
DRIVE      = "/content/drive/MyDrive/DataMate"
''')

add("code", '''
# 1. Basics: Drive, GPU
import json, os, shutil, subprocess, sys, time, zipfile
from pathlib import Path
T0 = time.time()
MODEL_NAME = MODEL_REPO.split("/")[-1]
def sh(cmd, tail=1500):
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True); print(r.stdout[-tail:], r.stderr[-800:])
    assert r.returncode == 0, f"failed: {cmd}"; return r.stdout
ENV = {**os.environ, "PYTHONPATH": "/content/DataMate/src", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONHASHSEED": "0"}
def run(args): return subprocess.run([sys.executable, "-m", *args], cwd="/content/DataMate", env=ENV, text=True, capture_output=True)

from google.colab import drive
drive.mount("/content/drive"); Path(DRIVE).mkdir(parents=True, exist_ok=True)
gpu = sh("nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv,noheader").strip()
gpu_name, gpu_mem, cap = [x.strip() for x in gpu.split(",")]
print("GPU:", gpu_name, "| compute capability", cap, "" if cap == "12.0" else "(not the competition GPU type: speed and memory numbers are only indicative)")
''')

add("code", '''
# 2. vLLM (the model server). Colab does not include it; this takes a few minutes the first time.
have = subprocess.run([sys.executable, "-c", "import vllm; print(vllm.__version__)"], capture_output=True, text=True)
if have.returncode != 0:
    sh("pip install -q vllm", tail=600)
    have = subprocess.run([sys.executable, "-c", "import vllm; print(vllm.__version__)"], capture_output=True, text=True)
assert have.returncode == 0, "vLLM is not importable. Try Runtime -> Restart session, then Run all again.\\n" + have.stderr[-500:]
print("vLLM", have.stdout.strip())
''')

add("code", '''
# 3. Project code and packages
shutil.rmtree("/content/DataMate", ignore_errors=True)
sh("git clone -q https://github.com/Kyoyooo/DataMate /content/DataMate")
sh("cd /content/DataMate && pip install -q -r requirements.in && pip install -q -e . --no-deps")
sys.path[:0] = ["/content/DataMate/tools", "/content/DataMate/src"]
import colab_helpers
print("commit:", sh("cd /content/DataMate && git rev-parse --short HEAD").strip())
''')

add("code", '''
# 4. Fixture check (no model needed). Must print PA = 1.0000
FX = "/content/out/fixture"; shutil.rmtree(FX, ignore_errors=True)
r = run(["datamate.run", "--dev", "--config", "config/dev.json", "--data-dir", "tests/fixtures/split_mini", "--result-dir", FX, "--set", "work_dir=/content/work/fixture"])
assert r.returncode == 0, r.stderr[-800:]
print(run(["datamate.eval.score", "--pred", f"{FX}/submission.jsonl", "--answers", "tests/fixtures/split_mini/answers.jsonl"]).stdout.splitlines()[0])
''')

add("code", '''
# 5. Training data: from Drive (MyDrive/DataMate/data/train/ if you have it, otherwise unzipped from MyDrive/DataMate/train.zip)
TRAIN = Path("/content/snap/train"); TRAIN.parent.mkdir(parents=True, exist_ok=True)
if not TRAIN.exists():
    folder, zip_path = Path(DRIVE) / "data/train", Path(DRIVE) / "train.zip"
    if folder.is_dir(): shutil.copytree(folder, TRAIN)
    else:
        assert zip_path.is_file(), f"Put train.zip into {DRIVE}/ on Google Drive, then run this cell again."
        with zipfile.ZipFile(zip_path) as z: z.extractall(TRAIN.parent)
assert (TRAIN / "answers.jsonl").is_file(), "this must be the TRAINING split (answers.jsonl present)"
print("training data:", TRAIN)
''')

add("code", '''
# 6. Model: use the copy on Drive, or download it once (EXAMPLE: MODEL_REPO) and keep a copy on Drive for next time
MODEL = Path("/content/snap/models") / MODEL_NAME; DRIVE_MODEL = Path(DRIVE) / "models" / MODEL_NAME
source = "already on local disk"
if not MODEL.exists():
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    if DRIVE_MODEL.is_dir(): shutil.copytree(DRIVE_MODEL, MODEL); source = "copied from Drive"
    else:
        source = "downloaded from Hugging Face"
        from huggingface_hub import snapshot_download
        snapshot_download(MODEL_REPO, local_dir=str(MODEL))
        shutil.copytree(MODEL, DRIVE_MODEL)
print(sh(f"python /content/DataMate/tools/count_params.py {MODEL}").splitlines()[0], "(limit for ALL models together: 15,000,000,000)")
print("model:", MODEL_REPO, "|", source, "| check license and release date on the model card")
''')

add("code", '''
# 7. Real run: 30 training questions. The model server starts automatically (memory limited to about 32 GB, like the competition GPU).
SUB = Path("/content/subset"); shutil.rmtree(SUB, ignore_errors=True)
print(colab_helpers.make_subset_split(TRAIN, SUB, 2, QUESTIONS), "questions selected")
OUT = Path("/content/out/subset"); shutil.rmtree(OUT, ignore_errors=True)
frac = round(min(0.95, 32 / (float(gpu_mem.split()[0]) / 1024)), 3)
sets = {"model.path": json.dumps(str(MODEL)), "serving.gpu_memory_utilization": frac, "work_dir": json.dumps("/content/work/subset")}
args = ["datamate.run", "--dev", "--config", "config/colab.json", "--data-dir", str(SUB), "--result-dir", str(OUT)]
for k, v in sets.items(): args += ["--set", f"{k}={v}"]
r = run(args); print(r.stderr[-1500:])
assert r.returncode == 0, "run failed: see /content/out/subset/logs/replica-0.log"
print(run(["datamate.eval.score", "--pred", f"{OUT}/submission.jsonl", "--answers", f"{SUB}/answers.jsonl"]).stdout)
print(f"done in {(time.time()-T0)/60:.1f} min. Results: {OUT}")
''')

add("code", '''
# 8. Save the results to Drive
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
