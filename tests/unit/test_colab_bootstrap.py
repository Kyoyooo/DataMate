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
    assert "config/colab.json" in joined and "PA" in joined or "datamate.eval.score" in joined
    # everything needed in one run: vLLM, data from train.zip, an example model download, scoring
    for needle in ("import vllm", "train.zip", "snapshot_download", "count_params", "PA", "HF_HUB_OFFLINE"):
        assert needle in joined, needle
    assert "MODEL_REPO" in joined.split("\n")[0] + "\n".join(code[:1])  # the model is one editable parameter
