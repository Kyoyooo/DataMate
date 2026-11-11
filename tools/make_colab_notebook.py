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
# Colab runs: smoke test, full training run, public test

**Run all.** This notebook does only what needs the GPU: vLLM, the model (downloaded if you do not have it yet), a smoke test
on 30 training questions and, if switched on, the full training run and the public test. Both long runs save every finished
part to Drive; after a disconnect, *Run all* again with the same run names continues where it stopped.
Results are saved to Google Drive. Everything else (tests, the fixture check, scoring, parameter count, licence check) is done on your own computer without a GPU.

Only one manual step: put **`train.zip`** (the training split you received, 128 MB) in `MyDrive/DataMate/` on Google Drive.
The model is an **example** (`Qwen/Qwen3-8B`): change `MODEL_REPO` to try another. Which model is used for the competition is the team lead's decision;
the license, release date and size must be checked on the model card (the notebook prints the parameter count).

**Full training run (TASKS L-06).** `RUN_FULL_TRAINING = True`: all training questions through the evaluation harness, one
fold of whole businesses at a time; PA by type and reason code, an error analysis and a runtime projection are saved to Drive.

**Public test (Round 1).** `RUN_PUBLIC_TEST = True` and the public test zip (`PUBLIC_ZIP`) in `MyDrive/DataMate/`: runs a few
businesses at a time and merges one `submission.jsonl` for the Round 1 leaderboard (reference only). Never tune prompts or rules
on public-test questions, and never commit its data or results (the repository is public).
""")

add("code", '''
MODEL_REPO = "Qwen/Qwen3-8B"          # EXAMPLE model, Hugging Face repo id
VLLM_VERSION = "0.10.1.1"             # same vLLM as the reference base image (M4-01)
QUESTIONS  = 30                       # how many training questions to run
DRIVE      = "/content/drive/MyDrive/DataMate"
BRANCH     = "main"                   # code branch to run (recorded in the results)
RUN_FULL_TRAINING = False             # True: all training questions, fold by fold (TASKS L-06)
TRAIN_RUN  = "train-full-1"           # results go to MyDrive/DataMate/runs/<TRAIN_RUN>/; same name = resume, new name = fresh run
FOLDS      = 5                        # whole-business folds (the harness rule); more folds = smaller parts, more model loads
RUN_PUBLIC_TEST = False               # True: also run the public test (Round 1)
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
COMMIT = sh("cd /content/DataMate && git rev-parse HEAD").strip()
print("branch:", BRANCH, "| commit:", COMMIT[:12])
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
def run_sets(work):  # the same settings for every run in this notebook: config/colab.json + model, memory, vLLM command
    sets = {"model.path": json.dumps(str(MODEL)), "serving.gpu_memory_utilization": frac, "work_dir": json.dumps(work),
            "serving.vllm_command": json.dumps([PY, "-m", colab_helpers.VLLM_MODULE])}
    return [x for k, v in sets.items() for x in ("--set", f"{k}={v}")]
def run_split(data_dir, out_dir, work):
    return run(["datamate.run", "--dev", "--config", "config/colab.json", "--data-dir", str(data_dir),
                "--result-dir", str(out_dir), *run_sets(work)])
IDENTITY = {"commit": COMMIT, "model": MODEL_REPO, "config": "config/colab.json", "gpu_memory_utilization": frac}
ABOUT = {"branch": BRANCH, "gpu": gpu, "python_env": PYINFO}
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
# 8. Full training run (only if RUN_FULL_TRAINING): every training question, one fold of whole businesses at a time,
#    through the evaluation harness. A fold with DONE on Drive is not run again (resume after a disconnect).
if RUN_FULL_TRAINING:
    TDEST = Path(DRIVE) / "runs" / TRAIN_RUN; TDEST.mkdir(parents=True, exist_ok=True)
    TOUT = Path("/content/out") / TRAIN_RUN; TOUT.mkdir(parents=True, exist_ok=True)
    tmeta = colab_helpers.run_meta(TDEST, **IDENTITY, folds=FOLDS, split="training")
    tmeta.update(ABOUT); tmeta.setdefault("folds_done", {})
    HARNESS = ["datamate.eval.harness", "run", "--config", "config/colab.json", "--data-dir", str(TRAIN),
               "--answers", str(TRAIN / "answers.jsonl"), "--out", str(TOUT), "--folds", str(FOLDS), "--dev",
               *run_sets(f"/content/work/{TRAIN_RUN}")]
    for k in range(FOLDS):
        saved, local = TDEST / f"fold{k}", TOUT / f"fold{k}"
        if (saved / "DONE").is_file():
            if not local.exists(): shutil.copytree(saved, local)
            print(f"fold {k} already done"); continue
        shutil.rmtree(local, ignore_errors=True); shutil.rmtree(f"/content/work/{TRAIN_RUN}", ignore_errors=True)
        t = time.time(); r = run(HARNESS + ["--fold", str(k)])
        print(f"fold {k}/{FOLDS}: exit {r.returncode} in {(time.time()-t)/60:.1f} min\\n", r.stdout[-1200:], r.stderr[-800:])
        if local.exists(): shutil.rmtree(saved, ignore_errors=True); shutil.copytree(local, saved)
        assert r.returncode == 0, f"fold {k} failed: see {saved}/logs/; Run all again to retry it"
        tmeta["folds_done"][str(k)] = {"minutes": round((time.time() - t) / 60, 1), "finished": time.strftime("%Y-%m-%d %H:%M")}
        colab_helpers.save_meta(TDEST, tmeta); (saved / "DONE").write_text("harness exit 0\\n")
    r = run(HARNESS + ["--all-folds", "--resume"]); print(r.stdout[-3000:], r.stderr[-800:])
    assert r.returncode == 0, "the merged evaluation failed"
    shutil.copy(TOUT / "run_record.json", TDEST / "run_record.json"); colab_helpers.save_meta(TDEST, tmeta)
else:
    print("full training run skipped (RUN_FULL_TRAINING = False)")
''')

add("code", '''
# 9. Training results: PA by type, error analysis (TASKS L-14) and runtime projection (TASKS M4-08), saved to Drive
if RUN_FULL_TRAINING:
    rep = json.loads((TOUT / "run_record.json").read_text())["report"]
    print(f"PA {rep['pa']:.4f} on {rep['n']} questions: {rep['correct']} correct, {rep['wrong']} wrong, {rep['abstain']} abstain")
    for t, c in sorted(rep["by_type"].items()): print(f"  {t:14s} {c}")
    ea = subprocess.run([PY, "tools/error_analysis.py", *[x for k in range(FOLDS) for x in ("--run", str(TOUT / f"fold{k}"))],
                         "--answers", str(TRAIN / "answers.jsonl"), "--markdown", str(TDEST / "error_analysis.md")],
                        cwd="/content/DataMate", env=ENV, text=True, capture_output=True)
    print(ea.stdout[:3000], ea.stderr[-500:])
    proj = rep["projected_s"]
    projection = {"gpu": gpu_name, "servers": 1, "model_loads": FOLDS, "questions": rep["n"],
                  "hours_500": round(proj["500"] / 3600, 2), "hours_1000": round(proj["1000"] / 3600, 2),
                  "note": "one Colab server, model loaded once per fold; two RTX 5090 servers are expected to be roughly "
                          "twice as fast; indicative only until measured on 2 x RTX 5090"}
    (TDEST / "projection.json").write_text(json.dumps(projection, indent=2))
    print("projection (6 h limit, aim <= 3 h):", projection)
    print("saved to", TDEST)
''')

add("code", '''
# 10. Public test data (only if RUN_PUBLIC_TEST): from MyDrive/DataMate/data/public_test/ or MyDrive/DataMate/<PUBLIC_ZIP>
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
# 11. Public test run, chunk by chunk. A chunk that already has DONE on Drive is not run again (resume after a disconnect).
#    The model server starts and stops inside each chunk. Each chunk keeps its own genuine logs and run.json;
#    only submission.jsonl is merged, in the order of questions.jsonl.
if RUN_PUBLIC_TEST:
    DEST = Path(DRIVE) / "runs" / PUBLIC_RUN; DEST.mkdir(parents=True, exist_ok=True)
    meta = colab_helpers.run_meta(DEST, **IDENTITY, businesses_per_chunk=BUSINESSES_PER_CHUNK, split="public test")
    meta.update(ABOUT); meta.setdefault("chunks", {})
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
        colab_helpers.save_meta(DEST, meta); done.write_text("precheck passed\\n")
    n = colab_helpers.merge_chunk_submissions(PUB, [DEST / c.name for c in CHUNKS], DEST / "submission.jsonl")
    meta["merged_questions"] = n; colab_helpers.save_meta(DEST, meta)
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
