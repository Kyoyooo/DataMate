#!/usr/bin/env python3
"""Generate notebooks/BAKEOFF_G4.ipynb (kept in code so the notebook is reviewable as text)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

MD, CODE = "markdown", "code"
cells: list[tuple[str, str]] = []


def add(kind: str, text: str) -> None:
    cells.append((kind, text.strip("\n")))


add(MD, """
# BAKEOFF_G4 — model bake-off and determinism investigation (TASKS M3-01, M3-08)

**Purpose.** Produce *evidence* for the lead's DEC-3 (model and base image). This notebook **does not decide DEC-3**.
For each candidate it (1) verifies revision, license, release date and parameter count, (2) serves it with vLLM on one
GPU capped to the memory of an RTX 5090 (32 GB), (3) measures PA on **whole held-out training businesses**, (4) runs the
same configuration twice to measure determinism, (5) measures throughput, and (6) runs a determinism investigation matrix
(max_num_seqs, prefix caching, VLLM_BATCH_INVARIANT, structured outputs).

**Reproducibility.** It runs the production entry point (`python -m datamate.run`, no `--dev`) from a **pinned commit on `main`**
(`REPO_COMMIT`, 40 hex characters; the first code cell refuses to run otherwise). It replaces the earlier exploratory L4 notebook, which
ran on sm_89, used unmerged contracts/templates and checked neither licenses nor release dates.

**Hardware caveat.** Valid evidence for the target needs a Blackwell GPU (compute capability 12.0, Colab **G4**). On any other GPU
(L4 = 8.9, A100 = 8.0) the notebook still runs but marks every result `NOT TARGET HARDWARE`.

**Held-out rule.** No prompt, threshold or few-shot example may be tuned on the evaluated businesses. The bank is off (`solver.fewshot_bank_path = null`).
Never point `TRAIN_DIR` at public or private test data (the notebook refuses a split without `answers.jsonl`; test data has none).
""")

add(CODE, '''
# ---- Parameters (edit only this cell) -------------------------------------------------------
REPO_URL    = "https://github.com/Kyoyooo/DataMate"
REPO_COMMIT = "REPLACE_WITH_40_HEX_COMMIT_ON_MAIN"      # must be a commit that is on main
TRAIN_DIR   = "/content/drive/MyDrive/DataMate/data/train"   # training split with answers.jsonl
WORK_DIR    = "/content/bakeoff"
FOLD, FOLDS = 0, 5                 # held-out = businesses of fold FOLD (SPEC §7.14: sha256 rank mod 5)
MAX_PER_BUSINESS = None            # None = all questions of the held-out businesses
DET_SUBSET_PER_BUSINESS = 6        # questions per business in the determinism matrix (time)
MEMORY_CAP_GIB = 32.0              # RTX 5090 memory to emulate
REPLICAS = 1                       # Colab has one GPU
# Candidates: every field must be filled from the model card at a fixed commit. `revision` = 40-hex commit sha.
CANDIDATES = [
    # {"name": "qwen3-8b",  "repo": "Qwen/Qwen3-8B",  "revision": "<40-hex>", "dtype": "bfloat16", "quantization": None, "reasoning_parser": None},
    # {"name": "qwen3-14b-fp8", "repo": "Qwen/Qwen3-14B-FP8", "revision": "<40-hex>", "dtype": "auto", "quantization": None, "reasoning_parser": None},
]
''')

add(CODE, '''
import re, subprocess, sys, json, os, shutil, time
assert re.fullmatch(r"[0-9a-f]{40}", REPO_COMMIT), "set REPO_COMMIT to the 40-hex commit of main under test"
assert CANDIDATES, "fill CANDIDATES (name, repo, 40-hex revision)"
assert os.path.isfile(f"{TRAIN_DIR}/answers.jsonl"), "TRAIN_DIR must be a TRAINING split (answers.jsonl present)"
def sh(cmd, **kw):
    print("$", cmd); r = subprocess.run(cmd, shell=True, text=True, capture_output=True, **kw)
    print(r.stdout[-3000:], r.stderr[-1500:]); return r
''')

add(MD, "## 1. Environment (record it; compare with the target)")
add(CODE, '''
r = sh("nvidia-smi --query-gpu=index,name,driver_version,memory.total,compute_cap --format=csv,noheader")
gpus = [x.split(", ") for x in r.stdout.strip().splitlines()]
assert gpus, "no GPU"
COMPUTE_CAP = gpus[0][4].strip(); TOTAL_GIB = float(gpus[0][3].split()[0]) / 1024
TARGET_HW = COMPUTE_CAP == "12.0"
print("compute capability", COMPUTE_CAP, "->", "TARGET HARDWARE" if TARGET_HW else "NOT TARGET HARDWARE (results are indicative only)")
''')

add(CODE, '''
shutil.rmtree("/content/DataMate", ignore_errors=True)
sh(f"git clone {REPO_URL} /content/DataMate && cd /content/DataMate && git checkout {REPO_COMMIT}")
head = sh("cd /content/DataMate && git rev-parse HEAD").stdout.strip()
assert head == REPO_COMMIT, (head, REPO_COMMIT)
assert sh(f"cd /content/DataMate && git merge-base --is-ancestor {REPO_COMMIT} origin/main").returncode == 0, "commit is not on main"
# project layer only; vLLM / torch / transformers come from the Colab image (record versions below)
sh("cd /content/DataMate && pip install -q 'duckdb>=1.1,<2' 'pydantic>=2.7,<3' && pip install -q -e . --no-deps")
sys.path.insert(0, "/content/DataMate/tools"); sys.path.insert(0, "/content/DataMate/src")
import bakeoff
sh("pip list 2>/dev/null | grep -iE '^(vllm|torch|transformers|huggingface|duckdb|pydantic) '")
''')

add(MD, """
## 2. Candidate verification (revision, license, release date, parameters)
`first_commit_date` is the date of the earliest commit of the repository: an **upper bound** on the public release date.
A human must still confirm the release date and license terms on the model card; `UNVERIFIED` is never treated as pass.
""")
add(CODE, '''
from huggingface_hub import HfApi, snapshot_download
api, verified, MODEL_DIRS = HfApi(), [], {}
for spec in CANDIDATES:
    d = snapshot_download(spec["repo"], revision=spec["revision"], local_dir=f"{WORK_DIR}/models/{spec['name']}")
    MODEL_DIRS[spec["name"]] = d
    info = api.model_info(spec["repo"], revision=spec["revision"])
    commits = api.list_repo_commits(spec["repo"])
    first = min(c.created_at for c in commits).date().isoformat()
    hub = {"license": (info.card_data.license if info.card_data else None), "sha": info.sha, "first_commit_date": first}
    out = json.loads(sh(f"python /content/DataMate/tools/count_params.py {d} --json").stdout or "{}")
    verified.append(bakeoff.verify_candidate(spec, hub, out.get("parameters")))
import pandas as pd
pd.DataFrame(verified)[["name", "revision_fixed", "license", "license_text", "release_date", "first_commit_date", "parameters", "param_limit", "all_pass"]]
''')

add(MD, "## 3. Held-out split (whole businesses)")
add(CODE, '''
SPLIT = f"{WORK_DIR}/heldout_fold{FOLD}"
shutil.rmtree(SPLIT, ignore_errors=True)
held_out = bakeoff.make_fold_split(__import__("pathlib").Path(TRAIN_DIR), __import__("pathlib").Path(SPLIT), FOLD, FOLDS, MAX_PER_BUSINESS)
print(len(held_out), "held-out businesses:", held_out)
ANSWERS = __import__("pathlib").Path(SPLIT) / "answers.jsonl"
''')

add(MD, """
## 4. Run helper
Production entry point with a generated config; every serving value is explicit and recorded in `run.json`. The server memory is capped with
`gpu_memory_utilization = 32 GiB / total memory` so that KV-cache capacity resembles an RTX 5090.
""")
add(CODE, '''
from pathlib import Path
def make_config(cand, tag, **over):
    cfg = {
      "work_dir": f"{WORK_DIR}/work/{cand['name']}-{tag}",
      "model": {"backend": "http", "path": MODEL_DIRS[cand["name"]], "revision": cand["revision"],
                "structured_outputs": over.pop("structured_outputs", True)},
      "serving": {"mode": "managed", "replicas": REPLICAS, "dtype": cand.get("dtype", "bfloat16"),
                  "quantization": cand.get("quantization"), "reasoning_parser": cand.get("reasoning_parser"),
                  "max_model_len": 16384, "max_num_seqs": over.pop("max_num_seqs", 64),
                  "gpu_memory_utilization": bakeoff.gpu_memory_fraction(TOTAL_GIB, MEMORY_CAP_GIB),
                  "enable_prefix_caching": over.pop("enable_prefix_caching", True),
                  "env": over.pop("env", {}), "startup_timeout_s": 1800},
      "concurrency": {"questions_per_replica": over.pop("questions_per_replica", 24), "setup_workers": 4},
      "exec_limits": {"workers": 8},
      "solver": {"tokenizer": "model", "template_version": "v1", "fewshot_bank_path": None},
    }
    assert not over, over
    p = Path(WORK_DIR) / "configs" / f"{cand['name']}-{tag}.json"; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2)); return p

def run_once(cand, tag, split=SPLIT, **over):
    out = Path(WORK_DIR) / "runs" / f"{cand['name']}-{tag}"; shutil.rmtree(out, ignore_errors=True)
    cfg = make_config(cand, tag, **over)
    t = time.time()
    r = subprocess.run([sys.executable, "-m", "datamate.run", "--config", str(cfg), "--data-dir", split, "--result-dir", str(out)],
                       cwd="/content/DataMate", text=True, capture_output=True,
                       env={**os.environ, "PYTHONPATH": "/content/DataMate/src", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                            "PYTHONHASHSEED": "0", "VLLM_NO_USAGE_STATS": "1", "DO_NOT_TRACK": "1"})
    print(tag, "exit", r.returncode, f"{time.time()-t:.0f}s", r.stderr[-600:])
    return out, r.returncode
''')

add(MD, "## 5. Per candidate: two identical runs → PA, determinism, throughput")
add(CODE, '''
results = {}
for cand, ver in zip(CANDIDATES, verified):
    a, ca = run_once(cand, "A1"); b, cb = run_once(cand, "A2")
    if ca or cb: results[cand["name"]] = {"verification": ver, "error": f"exit codes {ca},{cb}"}; continue
    results[cand["name"]] = {"verification": ver, "target_hardware": TARGET_HW, "run_a": bakeoff.run_summary(a, ANSWERS),
                             "determinism": bakeoff.compare_determinism(a, b, ANSWERS)}
Path(WORK_DIR, "bakeoff_results.json").write_text(json.dumps(results, indent=2, default=str))
for n, r in results.items():
    print(n, "PA", (r.get("run_a") or {}).get("pa"), "| identical-output rate", (r.get("determinism") or {}).get("identical_output_rate"),
          "| answers changed", (r.get("determinism") or {}).get("answers_changed"), "| dPA", (r.get("determinism") or {}).get("delta_pa"))
''')

add(MD, """
## 6. Determinism investigation
Hypotheses for output drift at temperature 0 (seen on the L4 exploration: identical requests produced different raw text and some different answers):
batch composition (continuous batching with concurrent requests changes floating-point reduction order), prefix caching (cache hit vs miss changes the
computation path), kernel non-invariance (`VLLM_BATCH_INVARIANT=1` where the installed vLLM supports it), and structured-output masking.
Each variant below is run **twice** on the same small subset with the same concurrency; the table reports how often an *identical request* gave a *different raw output*.
A variant that fails to start (e.g. unsupported env var) is recorded as an error, never silently skipped.
""")
add(CODE, '''
DET = f"{WORK_DIR}/det_subset"; shutil.rmtree(DET, ignore_errors=True)
bakeoff.make_fold_split(Path(TRAIN_DIR), Path(DET), FOLD, FOLDS, DET_SUBSET_PER_BUSINESS)
VARIANTS = {
  "baseline (seqs=64, prefix cache on)": {},
  "serial (max_num_seqs=1, 1 worker)": {"max_num_seqs": 1, "questions_per_replica": 1},
  "prefix caching off": {"enable_prefix_caching": False},
  "VLLM_BATCH_INVARIANT=1": {"env": {"VLLM_BATCH_INVARIANT": "1"}},
  "structured outputs off": {"structured_outputs": False},
}
cand = CANDIDATES[0]   # repeat the cell for other candidates if time allows
matrix = []
for name, over in VARIANTS.items():
    tag = re.sub(r"\\W+", "-", name)[:24]
    a, ca = run_once(cand, f"D-{tag}-1", DET, **dict(over)); b, cb = run_once(cand, f"D-{tag}-2", DET, **dict(over))
    if ca or cb:
        matrix.append({"variant": name, "error": f"exit {ca},{cb}"}); continue
    d = bakeoff.compare_determinism(a, b)
    matrix.append({"variant": name, "identical_output_rate": d["identical_output_rate"], "calls_same_request": d["calls_same_request"],
                   "different_output": d["calls_same_request_different_output"], "answers_changed": d["answers_changed"],
                   "submissions_identical": d["submissions_byte_identical"], "wall_s": bakeoff.throughput(a)["wall_s"]})
pd.DataFrame(matrix)
''')

add(MD, """
## 7. Hand-off
Save `bakeoff_results.json` and the table above to the shared Drive folder and attach them to the DEC-3 record (`docs/runbooks/bakeoff.md`).
Report to the lead: per-candidate PA with its 95% interval over questions, the determinism rate, projected 500-question time on 2 GPUs (per-GPU throughput x 2 only if
`REPLICAS = 1` here), every `UNVERIFIED` / `FAIL` flag, whether the hardware was the target, and which determinism variant (if any) removed the drift.
**No model is selected by this notebook.**
""")
add(CODE, '''
print(json.dumps({"commit": REPO_COMMIT, "target_hardware": TARGET_HW, "compute_capability": COMPUTE_CAP,
                  "candidates": [v["name"] for v in verified], "all_verified": all(v["all_pass"] for v in verified)}, indent=2))
''')


def build() -> dict:
    nb_cells = []
    for kind, text in cells:
        lines = text.splitlines(keepends=True)
        c = {"cell_type": kind, "metadata": {}, "source": lines}
        if kind == CODE:
            c.update(execution_count=None, outputs=[])
        nb_cells.append(c)
    return {"cells": nb_cells, "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python",
            "name": "python3"}, "language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "notebooks" / "BAKEOFF_G4.ipynb"
    out.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}", file=sys.stderr)
