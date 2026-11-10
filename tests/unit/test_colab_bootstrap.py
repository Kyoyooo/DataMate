"""M4-02: colab.json, helper module and the generated bootstrap notebook (CPU)."""

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


def test_colab_config_is_valid_managed_single_replica_without_dev_components():
    cfg = load_config(REPO / "config" / "colab.json")
    assert cfg.serving.mode == "managed" and cfg.serving.replicas == 1
    assert cfg.model.backend == "http" and cfg.solver.tokenizer == "model"
    assert cfg.model.script_path is None and cfg.model.replay_path is None and cfg.model.record_path is None
    assert 0 < cfg.serving.gpu_memory_utilization < 0.5  # 32 GB cap on a larger Colab GPU
    assert cfg.concurrency.questions_per_replica == 24 and cfg.serving.max_num_seqs == 64  # SPEC §6.2


def test_sha256sums_create_check_and_detect_every_kind_of_drift(tmp_path):
    root = tmp_path / "snap"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("a")
    (root / "sub" / "b.txt").write_text("b")
    assert helpers.create_sums(root) == 2
    first = (root / "SHA256SUMS").read_text()
    assert first.splitlines()[0].endswith("  a.txt") and "  sub/b.txt" in first
    assert helpers.create_sums(root) == 2 and (root / "SHA256SUMS").read_text() == first  # deterministic
    assert helpers.check_sums(root) == []
    (root / "a.txt").write_text("changed")
    assert helpers.check_sums(root) == ["hash mismatch: a.txt"]
    (root / "a.txt").write_text("a")
    (root / "sub" / "b.txt").unlink()
    assert helpers.check_sums(root) == ["missing: sub/b.txt"]
    (root / "sub" / "b.txt").write_text("b")
    (root / "extra.bin").write_text("x")
    assert helpers.check_sums(root) == ["not in SHA256SUMS: extra.bin"]
    assert helpers.check_sums(tmp_path / "empty") == [f"SHA256SUMS missing in {tmp_path / 'empty'}"]
    assert helpers.main(["check", str(root)]) == 1 and helpers.main(["bad"]) == 2


def test_subset_split_is_deterministic_training_only_and_keeps_answers(tmp_path):
    out = tmp_path / "sub"
    assert helpers.make_subset_split(SPLIT, out, 5, 4) == 4
    ids = [json.loads(x)["id"] for x in (out / "questions.jsonl").read_text().splitlines()]
    assert ids == [json.loads(x)["id"] for x in (SPLIT / "questions.jsonl").read_text().splitlines()][:4]
    assert [json.loads(x)["id"] for x in (out / "answers.jsonl").read_text().splitlines()] == ids
    assert (out / "data").is_symlink()
    nothing = tmp_path / "test_split"
    nothing.mkdir()
    (nothing / "questions.jsonl").write_text("")
    with pytest.raises(ValueError, match="training splits only"):
        helpers.make_subset_split(nothing, tmp_path / "x", 1, 1)


def test_subset_run_through_the_pipeline_scores_like_the_fixture(tmp_path):
    from datamate.eval.score import score_files
    from datamate.run import main

    from conftest import SCRIPT
    sub = tmp_path / "sub"
    helpers.make_subset_split(SPLIT, sub, 20, 20)
    out = tmp_path / "out"
    assert main(["--dev", "--config", str(REPO / "config" / "dev.json"), "--data-dir", str(sub),
                 "--result-dir", str(out), "--set", f"work_dir={tmp_path / 'w'}",
                 "--set", f"model.script_path={SCRIPT}"]) == 0
    assert set(score_files(out / "submission.jsonl", sub / "answers.jsonl")["per_id"].values()) == {1}


def test_notebook_is_generated_pinned_and_free_of_outputs():
    gen = load("make_colab_notebook")
    path = REPO / "notebooks" / "colab_bootstrap.ipynb"
    assert json.loads(path.read_text()) == gen.build(), "regenerate: python tools/make_colab_notebook.py"
    nb = json.loads(path.read_text())
    assert all(c.get("outputs", []) == [] for c in nb["cells"] if c["cell_type"] == "code")
    intro = "".join(nb["cells"][0]["source"])
    assert "≤ 20 minutes" in intro and "SHA256SUMS" in intro and "pinned commit" in intro
    code = ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]
    joined = "\n".join(code)
    for needle in ('re.fullmatch(r"[0-9a-f]{40}", REPO_COMMIT)', "is-ancestor", "check_sums", "answers.jsonl",
                   "PA = 1.0000", "config/colab.json", "precheck.sh", "gpu_memory_fraction", "WITHIN BUDGET",
                   "requirements.in", "load_tokenizer", "CREATE_MISSING_SUMS = False", "has no SHA256SUMS"):
        assert needle in joined, needle
    assert "snapshot_download" not in joined and "from_pretrained" not in joined  # no weight downloads
    for src in code:
        ast.parse(src)
