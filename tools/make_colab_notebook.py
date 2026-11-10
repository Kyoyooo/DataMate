#!/usr/bin/env python3
"""Generate notebooks/colab_bootstrap.ipynb (kept in code so the notebook is reviewable as text)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []


def add(kind: str, text: str) -> None:
    cells.append((kind, text.strip("\n")))


add(MD, """
# colab_bootstrap — fresh Colab session to a scored run (TASKS M4-02)

**Goal.** From a fresh Colab GPU session reach a scored run in **≤ 20 minutes**: mount the Drive snapshots, verify their `SHA256SUMS`,
install the project at a **pinned commit on `main`**, run the fixture (plumbing check, scripted model, must score 13/13), then run a small
**training** subset with the real model through the production pipeline and score it.

**Not a benchmark.** A 30-question subset says whether the whole path works on this GPU; it is not an accuracy or runtime claim.
Evidence for model choice comes from `BAKEOFF_G4.ipynb`; two-run comparison and full runs use the same commands with a bigger subset.

**Drive layout (R2: every snapshot has a `SHA256SUMS`).**
```
DataMate/data/train/            questions.jsonl, answers.jsonl, rulebook.md, calendar.csv, data/<business>/…, SHA256SUMS
DataMate/models/<MODEL_NAME>/   weights, tokenizer, configs, SHA256SUMS
DataMate/runs/                  outputs are copied here
```
Create a missing `SHA256SUMS` once: either on a trusted copy (`python tools/colab_helpers.py create <dir>`) or by setting `CREATE_MISSING_SUMS = True` for the first session (trust on first use; it protects later sessions).

**Rules.** Training data only (the notebook refuses a split without `answers.jsonl`). No downloads of model weights here: the model must already be on Drive.
Overrides are passed as `--dev --set key=value`, so they are recorded in `run.json`.
""")

add(CODE, '''
# ---- Parameters (edit only this cell) -------------------------------------------------------
REPO_URL    = "https://github.com/Kyoyooo/DataMate"
REPO_COMMIT = "REPLACE_WITH_40_HEX_COMMIT_ON_MAIN"
DRIVE_ROOT  = "/content/drive/MyDrive/DataMate"
MODEL_NAME  = "REPLACE_WITH_MODEL_DIR_NAME"       # directory under DRIVE_ROOT/models
MODEL_REVISION = None                             # 40-hex commit of the model, recorded in run.json
MEMORY_CAP_GIB = 32.0                             # emulate an RTX 5090
PER_BUSINESS, MAX_QUESTIONS = 2, 30               # training subset
TIME_BUDGET_MIN = 20
# First session only: if a snapshot has no SHA256SUMS yet, create it from the copied files and store it on Drive
# (trust on first use: it protects LATER sessions, not this one). Leave False once the sums exist.
CREATE_MISSING_SUMS = False
''')

add(CODE, '''
import json, os, re, shutil, subprocess, sys, time
T0 = time.time()
assert re.fullmatch(r"[0-9a-f]{40}", REPO_COMMIT), "set REPO_COMMIT to the 40-hex commit of main under test"
assert MODEL_NAME != "REPLACE_WITH_MODEL_DIR_NAME", "set MODEL_NAME"
def sh(cmd, check=False, tail=2500):
    print("$", cmd); r = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    print(r.stdout[-tail:], r.stderr[-1200:])
    if check: assert r.returncode == 0, f"failed: {cmd}"
    return r
def lap(label): print(f"[{(time.time()-T0)/60:5.1f} min] {label}")
''')

add(MD, "## 1. GPU and Drive")
add(CODE, '''
r = sh("nvidia-smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv,noheader", check=True)
name, driver, mem, cap = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")]
TOTAL_GIB = float(mem.split()[0]) / 1024
TARGET_HW = cap == "12.0"
print("GPU", name, "| compute capability", cap, "->", "TARGET HARDWARE" if TARGET_HW else "NOT TARGET HARDWARE: results are indicative only")
from google.colab import drive
drive.mount("/content/drive")
lap("drive mounted")
''')

add(MD, "## 2. Project at the pinned commit")
add(CODE, '''
shutil.rmtree("/content/DataMate", ignore_errors=True)
sh(f"git clone {REPO_URL} /content/DataMate", check=True)
sh(f"cd /content/DataMate && git checkout {REPO_COMMIT}", check=True)
assert sh("cd /content/DataMate && git rev-parse HEAD").stdout.strip() == REPO_COMMIT
assert sh(f"cd /content/DataMate && git merge-base --is-ancestor {REPO_COMMIT} origin/main").returncode == 0, "commit is not on main"
# Project layer only: vLLM, torch and transformers come from the Colab image (versions are recorded in run.json).
sh("cd /content/DataMate && pip install -q -r requirements.in && pip install -q -e . --no-deps", check=True)
sys.path[:0] = ["/content/DataMate/tools", "/content/DataMate/src"]
import colab_helpers
sh("pip list 2>/dev/null | grep -iE '^(vllm|torch|transformers|duckdb|pydantic) '")
lap("project installed")
''')

add(MD, "## 3. Snapshots: copy to local disk, verify SHA256SUMS")
add(CODE, '''
from pathlib import Path
LOCAL = Path("/content/snap"); LOCAL.mkdir(exist_ok=True)
TRAIN, MODEL = LOCAL / "train", LOCAL / "models" / MODEL_NAME
for src, dst in ((Path(DRIVE_ROOT) / "data" / "train", TRAIN), (Path(DRIVE_ROOT) / "models" / MODEL_NAME, MODEL)):
    assert src.is_dir(), f"missing on Drive: {src}"
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True); shutil.copytree(src, dst)
    if not (dst / "SHA256SUMS").is_file():
        assert CREATE_MISSING_SUMS, (f"{src} has no SHA256SUMS. Set CREATE_MISSING_SUMS = True for the first session "
                                     f"(or run: python tools/colab_helpers.py create <dir> on a trusted copy), then set it back to False.")
        n_files = colab_helpers.create_sums(dst); shutil.copy(dst / "SHA256SUMS", src / "SHA256SUMS")
        print(f"created SHA256SUMS for {dst} ({n_files} files) and saved it to Drive: this session is NOT verified against an independent hash list")
    problems = colab_helpers.check_sums(dst)
    assert not problems, f"{dst}: snapshot does not match its SHA256SUMS: {problems[:5]}"
    print("verified", dst)
assert (TRAIN / "answers.jsonl").is_file(), "TRAIN must be a training split"
lap("snapshots verified")
''')

add(MD, """
## 4. Fixture run (scripted model, CPU path) — must score 13/13
This checks the install and the pipeline plumbing, independent of the GPU and the model.
""")
add(CODE, '''
FX = "/content/out/fixture"; shutil.rmtree(FX, ignore_errors=True)
env = {**os.environ, "PYTHONPATH": "/content/DataMate/src"}
r = subprocess.run([sys.executable, "-m", "datamate.run", "--dev", "--config", "config/dev.json", "--data-dir", "tests/fixtures/split_mini",
                    "--result-dir", FX, "--set", "work_dir=/content/work/fixture"], cwd="/content/DataMate", env=env, text=True, capture_output=True)
print(r.stderr[-800:]); assert r.returncode == 0
s = subprocess.run([sys.executable, "-m", "datamate.eval.score", "--pred", f"{FX}/submission.jsonl", "--answers", "/content/DataMate/tests/fixtures/split_mini/answers.jsonl"],
                   cwd="/content/DataMate", env=env, text=True, capture_output=True).stdout
print(s.splitlines()[0]); assert "PA = 1.0000" in s and "correct=13" in s, "fixture must score 13/13"
lap("fixture OK")
''')

add(MD, "## 5. Model checks (parameter count, tokenizer) — no GPU needed")
add(CODE, '''
cp = sh(f"python /content/DataMate/tools/count_params.py {MODEL}")
from datamate.llm.tokenizer import load_tokenizer, count_tokens
tok = load_tokenizer(str(MODEL)); assert tok is not None, "tokenizer could not be loaded from the model directory (local files only)"
print("tokenizer", tok.name, "| tokens in a Vietnamese sentence:", count_tokens(tok, "Doanh thu tháng này là bao nhiêu?"))
''')

add(MD, """
## 6. First scored run: training subset, real model, production pipeline
`--dev --set …` only to override paths and the memory cap (recorded in `run.json`); the serving, concurrency and decoding values come from `config/colab.json`.
""")
add(CODE, '''
import colab_helpers
SUB = Path("/content/subset"); shutil.rmtree(SUB, ignore_errors=True)
n = colab_helpers.make_subset_split(TRAIN, SUB, PER_BUSINESS, MAX_QUESTIONS); print(n, "questions")
sys.path.insert(0, "/content/DataMate/tools"); import bakeoff
OUT = Path("/content/out/subset"); shutil.rmtree(OUT, ignore_errors=True)
sets = {"model.path": json.dumps(str(MODEL)), "model.revision": json.dumps(MODEL_REVISION),
        "serving.gpu_memory_utilization": bakeoff.gpu_memory_fraction(TOTAL_GIB, MEMORY_CAP_GIB), "work_dir": json.dumps("/content/work/subset")}
cmd = [sys.executable, "-m", "datamate.run", "--dev", "--config", "config/colab.json", "--data-dir", str(SUB), "--result-dir", str(OUT)]
for k, v in sets.items(): cmd += ["--set", f"{k}={v}"]
env = {**os.environ, "PYTHONPATH": "/content/DataMate/src", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONHASHSEED": "0",
       "VLLM_NO_USAGE_STATS": "1", "DO_NOT_TRACK": "1"}
t = time.time(); r = subprocess.run(cmd, cwd="/content/DataMate", env=env, text=True, capture_output=True)
print("exit", r.returncode, f"{time.time()-t:.0f}s"); print(r.stderr[-1500:])
assert r.returncode == 0, "run failed: read /content/out/subset/logs/replica-0.log and progress.log"
lap("subset run done")
''')

add(CODE, '''
sc = subprocess.run([sys.executable, "-m", "datamate.eval.score", "--pred", str(OUT/"submission.jsonl"), "--answers", str(SUB/"answers.jsonl")],
                    cwd="/content/DataMate", env=env, text=True, capture_output=True).stdout
print(sc)
pc = subprocess.run(["bash", "tools/precheck.sh", "--data-dir", str(SUB), "--result-dir", str(OUT)], cwd="/content/DataMate",
                    env={**env, "PYTHON": sys.executable}, text=True, capture_output=True); print(pc.stdout)
run = json.load(open(OUT / "logs/run.json"))
print("by reason:", run["counts"]["by_reason"]); print("replica load ms:", run["timings"]["replica_load_ms"], "| total ms:", run["total_ms"])
assert pc.returncode == 0, "precheck failed"
''')

add(MD, "## 7. Save outputs to Drive and check the time budget")
add(CODE, '''
head = sh("cd /content/DataMate && git rev-parse --short HEAD").stdout.strip()
dest = Path(DRIVE_ROOT) / "runs" / f"{time.strftime('%Y-%m-%d')}-{head}-bootstrap"
shutil.copytree(OUT, dest / "subset", dirs_exist_ok=True); shutil.copytree(FX, dest / "fixture", dirs_exist_ok=True)
(dest / "notes.json").write_text(json.dumps({"commit": REPO_COMMIT, "gpu": name, "compute_capability": cap, "target_hardware": TARGET_HW,
    "model": MODEL_NAME, "model_revision": MODEL_REVISION, "questions": n, "elapsed_min": round((time.time()-T0)/60, 1)}, indent=2))
elapsed = (time.time() - T0) / 60
print("saved to", dest); lap("finished")
print("WITHIN BUDGET" if elapsed <= TIME_BUDGET_MIN else f"OVER the {TIME_BUDGET_MIN}-minute target: see the lap times above")
''')


def build() -> dict:
    nb_cells = []
    for kind, text in cells:
        c = {"cell_type": kind, "metadata": {}, "source": text.splitlines(keepends=True)}
        if kind == CODE:
            c.update(execution_count=None, outputs=[])
        nb_cells.append(c)
    return {"cells": nb_cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python",
            "name": "python3"}, "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "notebooks" / "colab_bootstrap.ipynb"
    out.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}", file=sys.stderr)
