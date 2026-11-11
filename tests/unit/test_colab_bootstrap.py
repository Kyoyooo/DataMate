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



def _test_split(root, questions):
    root.mkdir()
    (root / "data").mkdir()
    (root / "rulebook.md").write_text("rules")
    (root / "calendar.csv").write_text("date\n")
    (root / "questions.jsonl").write_text("".join(json.dumps(q) + "\n" for q in questions))
    return root


def test_public_chunks_are_whole_businesses_in_question_order_and_merge_back(tmp_path):
    qs = [{"id": f"q{i}", "business_id": b, "question": "?", "as_of_date": "2026-08-27"}
          for i, b in enumerate(["biz_b", "biz_a", "biz_c", "biz_b", "biz_a"])]
    split = _test_split(tmp_path / "pub", qs)
    chunks = helpers.make_business_chunks(split, tmp_path / "chunks", 2)
    assert [c.name for c in chunks] == ["chunk-00", "chunk-01"]
    ids = [[json.loads(x)["id"] for x in (c / "questions.jsonl").read_text().splitlines()] for c in chunks]
    assert ids == [["q0", "q1", "q3", "q4"], ["q2"]]  # biz_a + biz_b, then biz_c; original order kept
    assert (chunks[0] / "data").resolve() == (split / "data").resolve() and (chunks[1] / "rulebook.md").is_symlink()
    assert helpers.make_business_chunks(split, tmp_path / "chunks", 2) == chunks  # re-run is idempotent

    results = []
    for c, part in zip(chunks, reversed(ids), strict=True):  # write the chunk answers in a scrambled order
        r = tmp_path / f"res-{c.name}"
        r.mkdir()
        (r / "submission.jsonl").write_text("".join(json.dumps({"id": i, "type": "abstain"}) + "\n"
                                                    for i in reversed(sum(ids, [])) if i in set(part)))
        results.append(r)
    out = tmp_path / "submission.jsonl"
    assert helpers.merge_chunk_submissions(split, results, out) == 5
    assert [json.loads(x)["id"] for x in out.read_text().splitlines()] == ["q0", "q1", "q2", "q3", "q4"]
    with pytest.raises(ValueError, match="4 missing ids"):
        helpers.merge_chunk_submissions(split, results[:1], out)
    with pytest.raises(ValueError, match="duplicate id"):
        helpers.merge_chunk_submissions(split, results + results[:1], out)
    (split / "answers.jsonl").write_text("")
    with pytest.raises(ValueError, match="answers.jsonl present"):
        helpers.make_business_chunks(split, tmp_path / "c2", 2)
    with pytest.raises(ValueError, match="missing"):
        helpers.make_business_chunks(tmp_path / "chunks", tmp_path / "c3", 2)


def test_a_chunk_runs_and_passes_precheck_like_a_whole_split(tmp_path):
    """The chunk layout (symlinked data, rulebook, calendar) is a valid input for datamate.run."""
    import shutil

    from datamate.run import main as run_main
    split = tmp_path / "pub"
    split.mkdir()
    for name in ("data", "rulebook.md", "calendar.csv", "questions.jsonl"):
        (shutil.copytree if (SPLIT / name).is_dir() else shutil.copy)(SPLIT / name, split / name)
    (chunk,) = helpers.make_business_chunks(split, tmp_path / "chunks", 5)
    out = tmp_path / "out"
    assert run_main(["--dev", "--config", str(REPO / "config" / "dev.json"), "--data-dir", str(chunk),
                     "--result-dir", str(out), "--set", f"work_dir={tmp_path / 'w'}"]) == 0
    precheck = load("precheck")
    assert precheck.main(["--data-dir", str(chunk), "--result-dir", str(out)]) == 0
    assert helpers.merge_chunk_submissions(split, [out], tmp_path / "merged.jsonl") == 13


def test_run_meta_resumes_only_the_same_code_and_model(tmp_path):
    meta = helpers.run_meta(tmp_path, commit="abc", model="m", folds=5)
    meta["folds_done"] = {"0": {"minutes": 1}}
    helpers.save_meta(tmp_path, meta)
    again = helpers.run_meta(tmp_path, commit="abc", model="m", folds=5)
    assert again["folds_done"] == {"0": {"minutes": 1}}
    for clash in ({"commit": "def"}, {"model": "other"}, {"folds": 10}):
        with pytest.raises(ValueError, match="use a new run name"):
            helpers.run_meta(tmp_path, **{"commit": "abc", "model": "m", "folds": 5, **clash})

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
    for needle in ("ensure_vllm_env", "vllm_command", "train.zip", "snapshot_download", "config/colab.json", "HF_HUB_OFFLINE",
                   "--branch {BRANCH}", "make_business_chunks", "merge_chunk_submissions", "tools/precheck.py", "DONE",
                   "datamate.eval.harness", "--all-folds", "--resume", "tools/error_analysis.py", "projection.json",
                   "colab_helpers.run_meta"):
        assert needle in joined, needle
    for cpu_only in ("tests/fixtures", "count_params", "eval.score\"]"):
        assert cpu_only not in joined, cpu_only
    assert "MODEL_REPO" in joined.split("\n")[0] + "\n".join(code[:1])  # the model is one editable parameter
    assert "RUN_PUBLIC_TEST = False" in code[0]  # the public test is opt-in
    assert "RUN_FULL_TRAINING = False" in code[0]  # so is the full training run


# ---------------------------------------------------------------- pinned vLLM environment

GOOD = {"python": "3.12.11", "vllm": "0.10.1.1", "torch": "2.7.1+cu128", "cuda": "12.8", "transformers": "4.55.2",
        "arch_list": ["sm_90", "sm_100", "sm_120"], "cuda_available": True, "capability": "12.0"}


def test_env_commands_pin_python_vllm_cuda_128_and_contemporary_libraries(tmp_path):
    proj, venv = tmp_path / "proj", tmp_path / "venv"
    proj.mkdir()
    cmds = helpers.vllm_env_commands("0.10.1.1", proj, venv, create=True, host_python="/usr/bin/python3")
    assert list(cmds) == ["uv", "venv", "base", "freeze", "project_requirements", "project"]
    flat = {k: " ".join(v) for k, v in cmds.items()}
    assert flat["venv"] == f"/usr/bin/python3 -m uv venv --python 3.12 {venv}"
    # transformers 5 broke vLLM 0.10.1.1 on Colab: the base uses the libraries of its release date
    assert "--torch-backend=cu128 vllm==0.10.1.1 transformers==4.55.2 tokenizers==0.21.4 huggingface-hub==0.34.4" in flat["base"]
    assert "--exclude-editable" in flat["freeze"]
    assert f"-c {venv / 'base-constraints.txt'} -r {proj / 'requirements.in'}" in flat["project_requirements"]
    assert flat["project"].endswith(f"--no-deps -e {proj}")
    assert "venv" not in helpers.vllm_env_commands("0.10.1.1", proj, venv, create=False)
    # once the image lock exists, it replaces the date-based pins
    (proj / "requirements.lock").write_text("transformers==4.55.4\n")
    base = " ".join(helpers.vllm_env_commands("0.10.1.1", proj, venv, create=False)["base"])
    assert base.endswith(f"vllm==0.10.1.1 -c {proj / 'requirements.lock'}") and "4.55.2" not in base


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
        if "freeze" in cmd:
            return types.SimpleNamespace(returncode=0, stdout="vllm==0.10.1.1\ntransformers==4.55.2\n", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def test_ensure_builds_once_then_only_refreshes_the_project(tmp_path):
    venv = tmp_path / "venv"
    run = FakeRun(venv, GOOD)
    py, info = helpers.ensure_vllm_env("0.10.1.1", tmp_path / "proj", venv, run=run)
    assert py == str(venv / "bin" / "python") and info == GOOD
    assert any("vllm==0.10.1.1" in c for cmd in run.calls for c in cmd)
    assert (venv / "base-constraints.txt").read_text() == "vllm==0.10.1.1\ntransformers==4.55.2\n"
    run.calls.clear()
    helpers.ensure_vllm_env("0.10.1.1", tmp_path / "proj", venv, run=run)
    installs = [cmd for cmd in run.calls if "install" in cmd]
    assert not any("vllm==0.10.1.1" in c for cmd in installs for c in cmd)  # vLLM kept
    assert any("-e" in cmd for cmd in installs)                                # project refreshed


def test_ensure_refuses_an_unusable_environment(tmp_path):
    run = FakeRun(tmp_path / "venv", {**GOOD, "arch_list": ["sm_90"]})
    with pytest.raises(RuntimeError, match="sm_120"):
        helpers.ensure_vllm_env("0.10.1.1", tmp_path / "proj", tmp_path / "venv", run=run)
