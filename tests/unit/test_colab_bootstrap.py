"""Colab quick start: config, subset helper and the generated notebook (CPU)."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys

import pytest

from datamate.config import load_config

from conftest import REPO, SPLIT


def load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


helpers = load("colab_helpers")


def test_colab_config_is_a_valid_single_replica_setup():
    cfg = load_config(REPO / "config" / "colab.json")
    assert cfg.serving.mode == "managed" and cfg.serving.replicas == 1 and cfg.model.backend == "http"


def test_subset_split_is_training_only_and_keeps_answers(tmp_path):
    out = tmp_path / "sub"
    assert helpers.make_subset_split(SPLIT, out, 5, 4) == 4
    ids = [json.loads(x)["id"] for x in (out / "questions.jsonl").read_text().splitlines()]
    assert [json.loads(x)["id"] for x in (out / "answers.jsonl").read_text().splitlines()] == ids
    no_answers = tmp_path / "test_split"
    no_answers.mkdir()
    (no_answers / "questions.jsonl").write_text("")
    with pytest.raises(ValueError, match="training splits only"):
        helpers.make_subset_split(no_answers, tmp_path / "x", 1, 1)


def test_notebook_is_generated_clean_and_valid_python():
    gen = load("make_colab_notebook")
    path = REPO / "notebooks" / "colab_bootstrap.ipynb"
    assert json.loads(path.read_text()) == gen.build(), "regenerate: python tools/make_colab_notebook.py"
    nb = json.loads(path.read_text())
    code = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    assert all(c.get("outputs", []) == [] for c in nb["cells"] if c["cell_type"] == "code")
    for src in code:
        ast.parse(src)
    joined = "\n".join(code)
    # GPU work only: vLLM, data, model, the real run. CPU work (fixture, scoring, parameter count) is done locally.
    for needle in ("ensure_vllm_env", "vllm_command", "train.zip", "snapshot_download", "config/colab.json", "HF_HUB_OFFLINE"):
        assert needle in joined, needle
    for cpu_only in ("tests/fixtures", "count_params", "eval.score\"]"):
        assert cpu_only not in joined, cpu_only
    assert "MODEL_REPO" in joined.split("\n")[0] + "\n".join(code[:1])  # the model is one editable parameter


# ---------------------------------------------------------------- pinned vLLM environment

GOOD = {"python": "3.12.11", "vllm": "0.10.1.1", "torch": "2.7.1+cu128", "cuda": "12.8",
        "arch_list": ["sm_90", "sm_100", "sm_120"], "cuda_available": True, "capability": "12.0"}


def test_env_commands_pin_python_vllm_and_cuda_128(tmp_path):
    cmds = helpers.vllm_env_commands("0.10.1.1", tmp_path / "proj", tmp_path / "venv", create=True,
                                     host_python="/usr/bin/python3")
    flat = [" ".join(c) for c in cmds]
    assert flat[0] == "/usr/bin/python3 -m pip install -q uv"
    assert flat[1] == f"/usr/bin/python3 -m uv venv --python 3.12 {tmp_path / 'venv'}"
    assert "--torch-backend=cu128 vllm==0.10.1.1 -r" in flat[2] and flat[2].endswith("requirements.in")
    assert flat[3].endswith(f"--no-deps -e {tmp_path / 'proj'}")
    assert len(helpers.vllm_env_commands("0.10.1.1", tmp_path, tmp_path / "v", create=False)) == 3


def test_env_check_catches_wrong_version_python_and_missing_blackwell_kernels():
    assert helpers.check_env(GOOD, "0.10.1.1") == []
    assert helpers.check_env(None, "0.10.1.1")
    assert any("vllm" in p for p in helpers.check_env({**GOOD, "vllm": "0.10.2"}, "0.10.1.1"))
    assert any("python" in p for p in helpers.check_env({**GOOD, "python": "3.13.1"}, "0.10.1.1"))
    assert any("sm_120" in p for p in helpers.check_env({**GOOD, "arch_list": ["sm_90"]}, "0.10.1.1"))
    assert any("no CUDA" in p for p in helpers.check_env({**GOOD, "cuda_available": False}, "0.10.1.1"))
    # another GPU type does not need sm_120 kernels
    assert helpers.check_env({**GOOD, "capability": "8.9", "arch_list": ["sm_89"]}, "0.10.1.1") == []


class FakeRun:
    """Records commands; the probe answers with ``info`` once the environment 'exists'."""

    def __init__(self, venv, info):
        self.venv, self.info, self.calls = venv, info, []

    def __call__(self, cmd, **_):
        import types
        self.calls.append(cmd)
        if cmd[-2:] and cmd[1:2] == ["-c"]:
            return types.SimpleNamespace(returncode=0, stdout=json.dumps(self.info) + "\n", stderr="")
        if "venv" in cmd:
            (self.venv / "bin").mkdir(parents=True)
            (self.venv / "bin" / "python").write_text("")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def test_ensure_builds_once_then_only_refreshes_the_project(tmp_path):
    venv = tmp_path / "venv"
    run = FakeRun(venv, GOOD)
    py, info = helpers.ensure_vllm_env("0.10.1.1", tmp_path / "proj", venv, run=run)
    assert py == str(venv / "bin" / "python") and info == GOOD
    assert any("vllm==0.10.1.1" in c for cmd in run.calls for c in cmd)
    run.calls.clear()
    helpers.ensure_vllm_env("0.10.1.1", tmp_path / "proj", venv, run=run)
    installs = [cmd for cmd in run.calls if "install" in cmd]
    assert not any("vllm==0.10.1.1" in c for cmd in installs for c in cmd)  # vLLM kept
    assert any("-e" in cmd for cmd in installs)                                # project refreshed


def test_ensure_refuses_an_unusable_environment(tmp_path):
    run = FakeRun(tmp_path / "venv", {**GOOD, "arch_list": ["sm_90"]})
    with pytest.raises(RuntimeError, match="sm_120"):
        helpers.ensure_vllm_env("0.10.1.1", tmp_path / "proj", tmp_path / "venv", run=run)
