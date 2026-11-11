"""GPU check: the generated notebook and the CPU report on a simulated result folder."""

from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import subprocess
import sys

from conftest import REPO, SPLIT


def load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_notebook_is_generated_clean_pinned_and_valid_python():
    gen = load("make_gpu_check_notebook")
    path = REPO / "notebooks" / "GPU_CHECK.ipynb"
    assert json.loads(path.read_text()) == gen.build(), "regenerate: python tools/make_gpu_check_notebook.py"
    code = ["".join(c["source"]) for c in gen.build()["cells"] if c["cell_type"] == "code"]
    for src in code:
        ast.parse(src)
    joined = "\n".join(code)
    for needle in ('VLLM_VERSION     = "0.10.1.1"', "vllm=={VLLM_VERSION}", "model.record_path",
                   "model.enable_thinking", "serving.reasoning_parser", "os.killpg", "check_m1_context.py",
                   "--tokenizer-dir", "count_params.py", "HF_HUB_OFFLINE", "meta.json", "train-A1", "train-A2"):
        assert needle in joined, needle


def dev_run(out, *sets):
    args = [sys.executable, "-m", "datamate.run", "--dev", "--config", str(REPO / "config" / "dev.json"),
            "--data-dir", str(SPLIT), "--result-dir", str(out), "--set", f"work_dir={out}-work"]
    for s in sets:
        args += ["--set", s]
    proc = subprocess.run(args, capture_output=True, text=True, cwd=REPO)
    assert proc.returncode == 0, proc.stderr


def test_report_on_a_simulated_folder(tmp_path):
    runs = tmp_path / "gpu_check"
    (runs / "runs").mkdir(parents=True)
    dev_run(runs / "runs" / "fixture", f"model.record_path={runs / 'split_mini.recorded.jsonl'}")
    for tag in ("train-A1", "train-A2"):
        dev_run(runs / "runs" / tag)
    shutil.copy(SPLIT / "answers.jsonl", runs / "answers.jsonl")
    (runs / "subset").mkdir()
    shutil.copy(SPLIT / "questions.jsonl", runs / "subset" / "questions.jsonl")
    (runs / "env").mkdir()
    (runs / "env" / "count_params.json").write_text(json.dumps({"parameters": 8_190_735_360}))
    (runs / "meta.json").write_text(json.dumps({
        "commit": "0" * 40, "vllm": "0.10.1.1", "gpu": "sim", "compute_capability": "12.0",
        "status": {"restart": {"exit": 0, "killed_at_s": None}},
        "times_s": {"first scored training run": 600}}))

    ck = load("gpu_check_report").report(runs)
    got = {(r["task"], r["check"]): r for r in ck.rows}

    def status(task, prefix):
        return next(r["status"] for (t, c), r in got.items() if t == task and c.startswith(prefix))

    assert status("DEC-3", "total parameters") == "PASS"
    assert status("M3-02", "real HTTP calls") == "FAIL"  # scripted calls carry no HTTP transport
    assert status("M3-13", "CPU replay") == "PASS"      # recording replays to the same bytes
    assert status("M3-04", "schema-valid") == "PASS"
    assert status("M3-03", "no context overflow") == "PASS"
    assert status("M4-02", "fresh session") == "PASS"
    assert status("L-15", "two identical runs") == "PASS"
    assert status("M4-07", "precheck of fixture") == "PASS"
    assert status("M4-07", "precheck of train-A1") == "PASS"
    assert status("M4-19", "thinking off") == "PASS"
    assert status("M4-19", "thinking on") == "NOT RUN"
    assert status("M4-03", "replica restart") == "NOT RUN"
    assert status("M3-03", "schema budget with the real tokenizer") == "NOT RUN"
    assert ck.failed
