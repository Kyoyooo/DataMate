"""M4-09: static checks of predict.sh, Dockerfile, .dockerignore and the frozen config."""

from __future__ import annotations

import re
import subprocess

from datamate.config import load_config

from conftest import REPO

PREDICT = (REPO / "predict.sh").read_text()
DOCKERFILE = (REPO / "Dockerfile").read_text()


def env_of_dockerfile() -> dict[str, str]:
    block = re.search(r"^ENV (.*?)(?=^\S)", DOCKERFILE, re.S | re.M).group(1)
    return dict(re.findall(r"(\w+)=(\S+)", block.replace("\\\n", " ")))


def test_predict_sh_takes_no_arguments_and_runs_the_fixed_command():
    assert PREDICT.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in PREDICT
    result = subprocess.run(["bash", str(REPO / "predict.sh"), "x"], capture_output=True, text=True)
    assert result.returncode == 2 and "no arguments" in result.stderr
    assert ("exec python3 -m datamate.run --config /code/config/run_config.json "
            "--data-dir /data --result-dir /result") in PREDICT
    assert "--dev" not in PREDICT and "--set" not in PREDICT
    assert "mkdir -p /result/logs" in PREDICT
    # no behavior-changing environment reads: only `export NAME=value` lines use variables
    assert not re.search(r"\$\{?[A-Za-z_]", PREDICT.replace("$#", "").replace("${BASH_SOURCE", ""))


def test_predict_sh_exports_the_spec_2_4_environment():
    exported = dict(re.findall(r"^export (\w+)=(\S+)$", PREDICT, re.M))
    for name, value in {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "PYTHONHASHSEED": "0",
                        "PYTHONUNBUFFERED": "1", "TOKENIZERS_PARALLELISM": "false",
                        "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                        "NCCL_P2P_DISABLE": "1", "VLLM_BATCH_INVARIANT": "0",
                        "VLLM_NO_USAGE_STATS": "1", "DO_NOT_TRACK": "1"}.items():
        assert exported[name] == value
    # the image default and the script never disagree
    for name, value in env_of_dockerfile().items():
        if name in exported:
            assert exported[name] == value, name


def test_dockerfile_follows_the_guide():
    lines = [x.strip() for x in DOCKERFILE.splitlines()]
    assert "ARG BASE_IMAGE=vllm/vllm-openai:v0.10.1.1" in lines and "ENTRYPOINT []" in lines
    assert 'CMD ["bash", "/code/predict.sh"]' in lines
    copies = [x for x in lines if x.startswith("COPY ")]
    index = {c.split()[1]: i for i, c in enumerate(copies)}
    assert index["models/"] < index["training_code/"] < index["src/"]  # weights before code (DG §9)
    assert index["requirements.lock"] < index["models/"]
    assert "COPY docs/SUBMISSION_README.md /code/README.md" in lines
    env = env_of_dockerfile()
    assert env["HF_HUB_OFFLINE"] == "1" and env["NCCL_P2P_DISABLE"] == "1"
    assert "--platform" not in DOCKERFILE  # the platform is a build flag (tools/build_image.sh)


def test_dockerignore_keeps_training_code_weights_and_runtime_inputs():
    patterns = [x.strip() for x in (REPO / ".dockerignore").read_text().splitlines()
                if x.strip() and not x.startswith("#")]
    for needed in ("training_code", "models", "src", "config", "tools", "docs", "predict.sh",
                   "requirements.lock", "requirements.in"):
        assert not any(p.strip("/") == needed or p.strip("/").startswith(needed + "/")
                       for p in patterns), needed


def test_every_copied_source_exists_in_the_repository():
    for line in DOCKERFILE.splitlines():
        if line.startswith("COPY ") and "--from" not in line:
            for src in line.split()[1:-1]:
                if src in ("models/", "requirements.lock"):
                    continue  # supplied by tools/build_image.sh / tools/gen_requirements_lock.sh
                assert (REPO / src).exists(), src


def test_frozen_config_is_managed_two_replica_serving_without_scripted_parts():
    cfg = load_config(REPO / "config" / "run_config.json")
    assert cfg.serving.mode == "managed" and cfg.serving.replicas == 2
    assert cfg.model.backend == "http" and cfg.model.path.startswith("/code/models/")
    assert cfg.model.script_path is None and cfg.model.replay_path is None
    assert cfg.model.record_path is None and cfg.model.base_url is None


def test_requirements_in_uses_the_pyproject_ranges_never_exact_pins():
    import pytest

    tomllib = pytest.importorskip("tomllib")  # Python 3.11+
    deps = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["dependencies"]
    want = {d.split(">")[0].split("<")[0].split("=")[0].strip(): d.replace(" ", "") for d in deps}
    want.pop("pydantic")  # shipped by the base image (SPEC §4.4)
    lines = [x.split("#")[0].strip() for x in (REPO / "requirements.in").read_text().splitlines()]
    got = {}
    for line in filter(None, lines):
        assert "==" not in line, f"exact pin in requirements.in: {line}"
        got[line.split(">")[0].split("<")[0].strip()] = line.replace(" ", "")
    assert got == want
