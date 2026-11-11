#!/usr/bin/env python3
"""Generate notebooks/GPU_CHECK.ipynb: one Colab session that collects every GPU-only acceptance
check of Phase 2 (M3-02, M3-03, M3-04, M3-05, M3-13, M4-02, M4-03, M4-07/M4-19, L-05 evidence).

The notebook only runs things that need the GPU or the model weights and saves raw results to
Google Drive. The verdicts are computed on a CPU machine by ``tools/gpu_check_report.py``.
Kept as code so the notebook is reviewable as text: never hand-edit the .ipynb.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

cells: list[tuple[str, str]] = []


def add(kind: str, text: str) -> None:
    cells.append((kind, text.strip("\n")))


add("markdown", """
# GPU check: every model-dependent Phase 2 acceptance check in one session

**Run all, once** (about 40-60 minutes on a Blackwell Colab GPU, most of it model loading and the two training runs).
The only manual step: put **`train.zip`** (the training split) into `MyDrive/DataMate/` on Google Drive.

What runs, in order (each step saves its raw output to Drive under `DataMate/gpu_check/<time>/`):

| Step | Evidence for |
|---|---|
| fixture run with the real model, calls recorded | M3-02 real HTTP calls, M3-13 recording |
| 2 identical runs on 2 questions of every training business | M3-04 parse validity, M3-05 solve rate, determinism, PA, M4-02 time to first scored result |
| a small run with thinking on | M4-19 / SC-7 thinking logs |
| a run where the model server is killed mid-run | M4-03 restart |
| schema budget with the real tokenizer over all 3,000 training questions (CPU, in the background) | M3-03, M1-10 |
| parameter count, `nvidia-smi`, `pip freeze` | 15 B limit, environment record |

Then, **on your own computer** (no GPU): download the folder and run
`python tools/gpu_check_report.py --runs <folder>`. It prints PASS / FAIL / NOT RUN per task.

`MODEL_REPO` is an **example**; choosing the competition model (DEC-3) is the team lead's decision.
""")

add("code", '''
MODEL_REPO       = "Qwen/Qwen3-8B"   # EXAMPLE candidate (Hugging Face repo id)
VLLM_VERSION     = "0.10.1.1"        # same vLLM as the reference base image vllm/vllm-openai:v0.10.1.1 (M4-01)
PER_BUSINESS     = 2                 # training questions per business for the two identical runs (30 businesses)
THINKING_QUESTIONS = 10              # 0 = skip the thinking-on run
REASONING_PARSER = "qwen3"           # vLLM reasoning parser of the model family (needed when thinking is on)
RESTART_CHECK    = True              # kill the model server once during a run (M4-03)
CONTEXT_CHECK    = True              # real-tokenizer schema budget over all training questions (CPU, background)
DRIVE            = "/content/drive/MyDrive/DataMate"
''')

add("code", '''
# 1. Basics: Drive, GPU, folders
import json, os, shutil, signal, subprocess, sys, time, zipfile
from pathlib import Path
T0 = time.time(); TIMES = {}
def mark(name): TIMES[name] = round(time.time() - T0, 1); print(f"[{TIMES[name]/60:.1f} min] {name}")
def sh(cmd, tail=1500):
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True); print(r.stdout[-tail:], r.stderr[-800:])
    assert r.returncode == 0, f"failed: {cmd}"; return r.stdout
from google.colab import drive
drive.mount("/content/drive")
OUT = Path(DRIVE) / "gpu_check" / time.strftime("%Y-%m-%d-%H%M"); (OUT / "runs").mkdir(parents=True, exist_ok=True); (OUT / "env").mkdir()
gpu_name, gpu_mem, cap = [x.strip() for x in sh("nvidia-smi --query-gpu=name,memory.total,compute_cap --format=csv,noheader").strip().split(",")]
TOTAL_GIB = float(gpu_mem.split()[0]) / 1024
(OUT / "env" / "nvidia-smi.txt").write_text(sh("nvidia-smi", tail=0))
print("GPU:", gpu_name, "| compute capability", cap, "" if cap == "12.0" else "(NOT the competition GPU type: speed/memory are indicative only)")
''')

add("code", '''
# 2. vLLM pinned to the base image version (a different version would make the check meaningless)
have = subprocess.run([sys.executable, "-c", "import vllm; print(vllm.__version__)"], capture_output=True, text=True)
if have.returncode != 0 or have.stdout.strip() != VLLM_VERSION:
    sh(f"pip install -q vllm=={VLLM_VERSION}", tail=600)
    have = subprocess.run([sys.executable, "-c", "import vllm; print(vllm.__version__)"], capture_output=True, text=True)
assert have.returncode == 0 and have.stdout.strip() == VLLM_VERSION, (
    "vLLM is not importable at the pinned version. Runtime -> Restart session, then Run all again.\\n" + have.stderr[-500:])
print("vLLM", have.stdout.strip()); mark("vllm ready")
''')

add("code", '''
# 3. Project code (current main) and its packages
shutil.rmtree("/content/DataMate", ignore_errors=True)
sh("git clone -q https://github.com/Kyoyooo/DataMate /content/DataMate")
sh("cd /content/DataMate && pip install -q -r requirements.in && pip install -q -e . --no-deps")
COMMIT = sh("cd /content/DataMate && git rev-parse HEAD").strip()
sys.path[:0] = ["/content/DataMate/tools", "/content/DataMate/src"]
import colab_helpers, bakeoff
ENV = {**os.environ, "PYTHONPATH": "/content/DataMate/src", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONHASHSEED": "0"}
(OUT / "env" / "pip-freeze.txt").write_text(sh(f"{sys.executable} -m pip freeze --all", tail=0))
print("commit", COMMIT)
''')

add("code", '''
# 4. Training data (MyDrive/DataMate/train.zip) and the model (Drive copy, or downloaded once and kept on Drive)
TRAIN = Path("/content/snap/train"); TRAIN.parent.mkdir(parents=True, exist_ok=True)
if not TRAIN.exists():
    zp = Path(DRIVE) / "train.zip"; assert zp.is_file(), f"Put train.zip into {DRIVE}/ on Google Drive, then run this cell again."
    with zipfile.ZipFile(zp) as z: z.extractall(TRAIN.parent)
assert (TRAIN / "answers.jsonl").is_file(), "this must be the TRAINING split (answers.jsonl present)"
MODEL_NAME = MODEL_REPO.split("/")[-1]
MODEL = Path("/content/snap/models") / MODEL_NAME; SAVED = Path(DRIVE) / "models" / MODEL_NAME
if not MODEL.exists():
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    if SAVED.is_dir(): shutil.copytree(SAVED, MODEL)
    else:
        from huggingface_hub import snapshot_download
        snapshot_download(MODEL_REPO, local_dir=str(MODEL)); shutil.copytree(MODEL, SAVED)
(OUT / "env" / "count_params.json").write_text(sh(f"{sys.executable} /content/DataMate/tools/count_params.py {MODEL} --json", tail=400))
mark("data and model ready")
''')

add("code", '''
# 5. Background CPU job: real-tokenizer schema budget over all training questions (M3-03 / M1-10)
CTX = None
if CONTEXT_CHECK:
    cmd = (f"cd /content/DataMate && {sys.executable} tools/audit_m1.py --split-dir {TRAIN} --output-dir /content/audit --role train"
           f" && {sys.executable} tools/check_m1_context.py --audit-dir /content/audit --questions {TRAIN}/questions.jsonl"
           f" --output {OUT}/context_check.json --tokenizer-dir {MODEL}")
    CTX = subprocess.Popen(cmd, shell=True, env=ENV, stdout=open(OUT / "context_check.log", "w"), stderr=subprocess.STDOUT)
    print("context check started in the background")
''')

add("code", '''
# 6. Run helper. The model server starts and stops inside each run (managed serving, memory capped at about 32 GB).
STATUS = {}
FRAC = bakeoff.gpu_memory_fraction(TOTAL_GIB, 32.0)
def run_case(tag, split, background=False, **sets):
    out = Path("/content/runs") / tag; shutil.rmtree(out, ignore_errors=True)
    base = {"model.path": json.dumps(str(MODEL)), "serving.gpu_memory_utilization": FRAC, "work_dir": json.dumps(f"/content/work/{tag}")}
    args = [sys.executable, "-m", "datamate.run", "--dev", "--config", "config/colab.json", "--data-dir", str(split), "--result-dir", str(out)]
    for k, v in {**base, **sets}.items(): args += ["--set", f"{k}={v}"]
    if background:
        return subprocess.Popen(args, cwd="/content/DataMate", env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True), out
    started = time.time(); r = subprocess.run(args, cwd="/content/DataMate", env=ENV, text=True, capture_output=True)
    STATUS[tag] = {"exit": r.returncode, "seconds": round(time.time() - started, 1)}
    (out / "stderr.txt").parent.mkdir(parents=True, exist_ok=True); (out / "stderr.txt").write_text(r.stdout + r.stderr)
    shutil.copytree(out, OUT / "runs" / tag, dirs_exist_ok=True)
    print(tag, STATUS[tag], r.stderr[-400:]); return out
SUB = Path("/content/subset"); shutil.rmtree(SUB, ignore_errors=True)
print(colab_helpers.make_subset_split(TRAIN, SUB, PER_BUSINESS, PER_BUSINESS * 30), "training questions selected")
shutil.copy(SUB / "answers.jsonl", OUT / "answers.jsonl")
(OUT / "subset").mkdir(exist_ok=True); shutil.copy(SUB / "questions.jsonl", OUT / "subset" / "questions.jsonl")
''')

add("code", '''
# 7. Fixture with the real model; every call recorded (M3-02, M3-13). The fixture is synthetic: its recording may be committed.
run_case("fixture", Path("/content/DataMate/tests/fixtures/split_mini"),
         **{"model.record_path": json.dumps(str(OUT / "split_mini.recorded.jsonl"))})
mark("fixture done")
''')

add("code", '''
# 8. Two identical runs on the training subset (M3-04, M3-05, determinism, PA, M4-02 time to first scored result)
run_case("train-A1", SUB); mark("first scored training run")
run_case("train-A2", SUB); mark("second identical run")
''')

add("code", '''
# 9. Thinking on (M4-19 / SC-7): thinking must be logged exactly as generated
if THINKING_QUESTIONS:
    TH = Path("/content/subset_think"); shutil.rmtree(TH, ignore_errors=True)
    colab_helpers.make_subset_split(TRAIN, TH, 1, THINKING_QUESTIONS)
    (OUT / "subset_think").mkdir(exist_ok=True); shutil.copy(TH / "questions.jsonl", OUT / "subset_think" / "questions.jsonl")
    on = {f"model.enable_thinking.{s}": "true" for s in ("parse", "solve", "repair", "fallback")}
    on.update({f"model.max_tokens.{s}": 4096 for s in ("parse", "solve", "repair", "fallback")})
    run_case("thinking-on", TH, **on, **{"serving.reasoning_parser": REASONING_PARSER})
    mark("thinking run done")
''')

add("code", '''
# 10. Restart (M4-03): kill the model server's process group once the run has written 3 questions
if RESTART_CHECK:
    proc, rout = run_case("restart", SUB, background=True, **{"concurrency.questions_per_replica": 4})
    killed, t_start = None, time.time()
    while proc.poll() is None:
        done = rout / "logs" / "questions.jsonl"
        if killed is None and done.is_file() and len(done.read_text().splitlines()) >= 3:
            pids = subprocess.run(["pgrep", "-f", "vllm.entrypoints.openai.api_server"], capture_output=True, text=True).stdout.split()
            if pids:
                os.killpg(int(pids[0]), signal.SIGKILL); killed = round(time.time() - t_start, 1); print("killed model server at", killed, "s")
        time.sleep(2)
    log = proc.stdout.read(); (rout / "stderr.txt").write_text(log)
    STATUS["restart"] = {"exit": proc.returncode, "seconds": round(time.time() - t_start, 1), "killed_at_s": killed}
    shutil.copytree(rout, OUT / "runs" / "restart", dirs_exist_ok=True); print(STATUS["restart"]); mark("restart run done")
''')

add("code", '''
# 11. Wait for the background context check, then write meta.json (everything the local report needs)
if CTX is not None:
    print("waiting for the context check ..."); CTX.wait(); STATUS["context_check"] = {"exit": CTX.returncode}
mark("all done")
(OUT / "meta.json").write_text(json.dumps({
    "commit": COMMIT, "model_repo": MODEL_REPO, "vllm": VLLM_VERSION, "gpu": gpu_name, "compute_capability": cap,
    "gpu_total_gib": round(TOTAL_GIB, 1), "gpu_memory_utilization": FRAC, "per_business": PER_BUSINESS,
    "status": STATUS, "times_s": TIMES, "minutes": round((time.time() - T0) / 60, 1)}, indent=2))
print("saved to", OUT)
print("Next, on your own computer: python tools/gpu_check_report.py --runs <downloaded folder>")
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
    out = Path(__file__).resolve().parents[1] / "notebooks" / "GPU_CHECK.ipynb"
    out.write_text(json.dumps(build(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out}", file=sys.stderr)
