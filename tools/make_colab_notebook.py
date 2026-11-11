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

**Run all, once.** This notebook does only what needs the GPU: vLLM, the model (downloaded if you do not have it yet) and 30 training questions.
Results are saved to Google Drive. Everything else (tests, the fixture check, scoring, parameter count, licence check) is done on your own computer without a GPU.

Only one manual step: put **`train.zip`** (the training split you received, 128 MB) in `MyDrive/DataMate/` on Google Drive.
The model is an **example** (`Qwen/Qwen3-8B`): change `MODEL_REPO` to try another. Which model is used for the competition is the team lead's decision;
the license, release date and size must be checked on the model card (the notebook prints the parameter count).

**Optional public test (Round 1).** Set `RUN_PUBLIC_TEST = True` and put the public test zip (`PUBLIC_ZIP`) in `MyDrive/DataMate/`.
After the 30 training questions (the smoke test), the public test runs a few businesses at a time; each finished chunk is saved to Drive,
so after a disconnect, *Run all* again continues with the next chunk. The merged `submission.jsonl` is for the Round 1 leaderboard only
(reference). Never tune prompts or rules on public-test questions, and never commit its data or results (the repository is public).
""")

add("code", '''
MODEL_REPO = "Qwen/Qwen3-8B"          # EXAMPLE model, Hugging Face repo id
VLLM_VERSION = "0.10.1.1"             # same vLLM as the reference base image (M4-01)
QUESTIONS  = 30                       # how many training questions to run
DRIVE      = "/content/drive/MyDrive/DataMate"
BRANCH     = "main"                   # code branch to run (recorded in the results)
RUN_PUBLIC_TEST = False               # True: also run the public test (Round 1) after the training smoke test
PUBLIC_ZIP = "public_test.zip"        # in MyDrive/DataMate/ (or an unzipped copy in MyDrive/DataMate/data/public_test/)
PUBLIC_RUN = "public-1"               # results go to MyDrive/DataMate/runs/<PUBLIC_RUN>/; same name = resume, new name = fresh run
BUSINESSES_PER_CHUNK = 5              # whole businesses per chunk (a disconnect loses at most the running chunk)
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
def run(args): return subprocess.run([PY, "-m", *args], cwd="/content/DataMate", env=ENV, text=True, capture_output=True)

from google.colab import drive
drive.mount("/content/drive"); Path(DRIVE).mkdir(parents=True, exist_ok=True)
gpu = sh("nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv,noheader").strip()
gpu_name, gpu_mem, cap = [x.strip() for x in gpu.split(",")]
print("GPU:", gpu_name, "| compute capability", cap, "" if cap == "12.0" else "(not the competition GPU type: speed and memory numbers are only indicative)")
assert float(cap) >= 8.0 and float(gpu_mem.split()[0]) / 1024 >= 22, (
    f"{gpu_name} ({gpu_mem}, cc {cap}) cannot serve the model: Runtime -> Change runtime type -> G4 (Blackwell, like the RTX 5090) or A100")
''')

add("code", '''
# 2. Project code
shutil.rmtree("/content/DataMate", ignore_errors=True)
sh(f"git clone -q --branch {BRANCH} https://github.com/Kyoyooo/DataMate /content/DataMate")
sys.path[:0] = ["/content/DataMate/tools"]
import colab_helpers
print("commit:", sh("cd /content/DataMate && git rev-parse --short HEAD").strip())
''')

add("code", '''
# 3. vLLM (the model server) pinned to the base image version, in its own Python 3.12 environment
#    (Colab's Python is too new for it). First time: a few minutes.
PY, PYINFO = colab_helpers.ensure_vllm_env(VLLM_VERSION, Path("/content/DataMate"))
print(PYINFO)
''')

add("code", '''
# 4. Training data: from Drive (MyDrive/DataMate/data/train/ if you have it, otherwise unzipped from MyDrive/DataMate/train.zip)
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
# 5. Model: use the copy on Drive, or download it once (EXAMPLE: MODEL_REPO) and keep a copy on Drive for next time
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
print("model:", MODEL_REPO, "|", source)
''')

add("code", '''
# 6. Real run: 30 training questions. The model server starts automatically (memory limited to about 32 GB, like the competition GPU).
SUB = Path("/content/subset"); shutil.rmtree(SUB, ignore_errors=True)
print(colab_helpers.make_subset_split(TRAIN, SUB, 2, QUESTIONS), "questions selected")
OUT = Path("/content/out/subset"); shutil.rmtree(OUT, ignore_errors=True)
frac = round(min(0.95, 32 / (float(gpu_mem.split()[0]) / 1024)), 3)
def run_split(data_dir, out_dir, work):
    sets = {"model.path": json.dumps(str(MODEL)), "serving.gpu_memory_utilization": frac, "work_dir": json.dumps(work),
            "serving.vllm_command": json.dumps([PY, "-m", colab_helpers.VLLM_MODULE])}
    args = ["datamate.run", "--dev", "--config", "config/colab.json", "--data-dir", str(data_dir), "--result-dir", str(out_dir)]
    for k, v in sets.items(): args += ["--set", f"{k}={v}"]
    return run(args)
r = run_split(SUB, OUT, "/content/work/subset"); print(r.stderr[-1500:])
assert r.returncode == 0, "run failed: see /content/out/subset/logs/replica-0.log"
print(f"done in {(time.time()-T0)/60:.1f} min. Results: {OUT}")
''')

add("code", '''
# 7. Save the results to Drive
dest = Path(DRIVE) / "runs" / time.strftime("%Y-%m-%d-%H%M"); shutil.copytree(OUT, dest); shutil.copy(SUB / "answers.jsonl", dest / "answers.jsonl")
print("saved to", dest, "\\nScore it on your own computer (no GPU needed): python -m datamate.eval.score --pred <dest>/submission.jsonl --answers <dest>/answers.jsonl")
''')


add("code", '''
# 8. Public test data (only if RUN_PUBLIC_TEST): from MyDrive/DataMate/data/public_test/ or MyDrive/DataMate/<PUBLIC_ZIP>
if RUN_PUBLIC_TEST:
    PUB_ROOT = Path("/content/snap/public")
    if not PUB_ROOT.exists():
        folder, zip_path = Path(DRIVE) / "data/public_test", Path(DRIVE) / PUBLIC_ZIP
        if folder.is_dir(): shutil.copytree(folder, PUB_ROOT)
        else:
            assert zip_path.is_file(), f"Put {PUBLIC_ZIP} into {DRIVE}/ on Google Drive, then run this cell again."
            with zipfile.ZipFile(zip_path) as z: z.extractall(PUB_ROOT)
    found = sorted(q.parent for q in PUB_ROOT.rglob("questions.jsonl") if (q.parent / "rulebook.md").is_file())
    assert len(found) == 1, f"expected one split folder (questions.jsonl + rulebook.md) under {PUB_ROOT}, found {found}"
    PUB = found[0]
    assert not (PUB / "answers.jsonl").exists(), "this has answers.jsonl: it is a training split, not the public test"
    CHUNKS = colab_helpers.make_business_chunks(PUB, Path("/content/public_chunks"), BUSINESSES_PER_CHUNK)
    print("public test:", PUB, "|", sum(1 for x in (PUB / "questions.jsonl").open(encoding="utf-8-sig") if x.strip()),
          "questions in", len(CHUNKS), "chunks")
else:
    print("public test skipped (RUN_PUBLIC_TEST = False)")
''')

add("code", '''
# 9. Public test run, chunk by chunk. A chunk that already has DONE on Drive is not run again (resume after a disconnect).
#    The model server starts and stops inside each chunk. Each chunk keeps its own genuine logs and run.json;
#    only submission.jsonl is merged, in the order of questions.jsonl.
if RUN_PUBLIC_TEST:
    DEST = Path(DRIVE) / "runs" / PUBLIC_RUN; DEST.mkdir(parents=True, exist_ok=True)
    commit = sh("cd /content/DataMate && git rev-parse HEAD").strip()
    meta_path = DEST / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {"chunks": {}}
    if meta.get("commit", commit) != commit or meta.get("model", MODEL_REPO) != MODEL_REPO:
        raise SystemExit(f"{DEST} was started with commit {meta.get('commit')} / model {meta.get('model')}: "
                         "use a new PUBLIC_RUN name instead of mixing code or model versions in one submission")
    meta.update(commit=commit, branch=BRANCH, model=MODEL_REPO, config="config/colab.json", gpu=gpu, python_env=PYINFO,
                gpu_memory_utilization=frac, businesses_per_chunk=BUSINESSES_PER_CHUNK, split="public test")
    for chunk in CHUNKS:
        done = DEST / chunk.name / "DONE"
        if done.is_file(): print(chunk.name, "already done"); continue
        out = Path("/content/out/public") / chunk.name; shutil.rmtree(out, ignore_errors=True)
        t = time.time(); r = run_split(chunk, out, f"/content/work/public/{chunk.name}")
        print(chunk.name, f"exit {r.returncode} in {(time.time()-t)/60:.1f} min", r.stderr[-600:])
        pre = subprocess.run([PY, "tools/precheck.py", "--data-dir", str(chunk), "--result-dir", str(out)],
                             cwd="/content/DataMate", env=ENV, text=True, capture_output=True)
        print(pre.stdout[-800:])
        shutil.rmtree(DEST / chunk.name, ignore_errors=True); shutil.copytree(out, DEST / chunk.name)
        assert r.returncode == 0 and pre.returncode == 0, f"{chunk.name} failed: see {DEST / chunk.name}/logs/; Run all again to retry it"
        meta["chunks"][chunk.name] = {"minutes": round((time.time() - t) / 60, 1), "finished": time.strftime("%Y-%m-%d %H:%M")}
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False)); done.write_text("precheck passed\\n")
    n = colab_helpers.merge_chunk_submissions(PUB, [DEST / c.name for c in CHUNKS], DEST / "submission.jsonl")
    meta["merged_questions"] = n; meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print(f"merged {n} answers -> {DEST / 'submission.jsonl'} (upload this file for the Round 1 leaderboard)")
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
