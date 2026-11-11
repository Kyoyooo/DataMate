"""tools/bakeoff.py and the generated bake-off notebook (CPU)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys

import pytest

from datamate.run import main

from conftest import REPO, SCRIPT, SPLIT

TOOLS = REPO / "tools"


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bakeoff = load("bakeoff")
SHA = "a" * 40


def hub(**kw):
    return {"license": "apache-2.0", "sha": SHA, "first_commit_date": "2026-04-29", **kw}


def test_candidate_verification_pass_fail_and_unverified():
    spec = {"name": "m", "repo": "o/m", "revision": SHA}
    ok = bakeoff.verify_candidate(spec, hub(), 8_190_000_000)
    assert ok["all_pass"] and ok["license"] == ok["release_date"] == ok["param_limit"] == "PASS"
    late = bakeoff.verify_candidate(spec, hub(first_commit_date="2026-10-26"), 1)  # not BEFORE the cutoff
    assert late["release_date"] == "FAIL" and not late["all_pass"]
    big = bakeoff.verify_candidate(spec, hub(), 14_000_000_000, other_params=1_000_000_001)
    assert big["param_limit"] == "FAIL"
    assert bakeoff.verify_candidate(spec, hub(), 15_000_000_000)["param_limit"] == "PASS"  # <= 15 B
    odd = bakeoff.verify_candidate(spec, hub(license="other"), 1)
    assert odd["license"] == "UNVERIFIED" and not odd["all_pass"]  # never assumed permitted
    none = bakeoff.verify_candidate({"name": "m", "repo": "o/m", "revision": "main"}, None, None)
    assert none["revision_fixed"] == "FAIL" and none["release_date"] == "UNVERIFIED"
    assert none["param_limit"] == "UNVERIFIED" and not none["all_pass"]
    moved = bakeoff.verify_candidate(spec, hub(sha="b" * 40), 1)
    assert moved["revision_fixed"] == "FAIL"


def test_gpu_memory_fraction_emulates_a_32gib_card():
    assert bakeoff.gpu_memory_fraction(96.0, 32.0) == 0.333
    assert bakeoff.gpu_memory_fraction(24.0, 32.0) == 0.95  # never above the safe ceiling
    with pytest.raises(ValueError):
        bakeoff.gpu_memory_fraction(0)


def test_business_folds_follow_sha256_rank_mod_5():
    ids = [f"biz_{i:03d}" for i in range(12)]
    folds = bakeoff.business_folds(ids)
    ranked = sorted(ids, key=lambda b: hashlib.sha256(b.encode()).hexdigest())
    assert [folds[b] for b in ranked] == [i % 5 for i in range(12)]
    assert folds == bakeoff.business_folds(list(reversed(ids)))  # independent of input order


@pytest.fixture
def two_biz_train(tmp_path):
    dst = tmp_path / "train"
    shutil.copytree(SPLIT, dst)
    shutil.copytree(dst / "data" / "biz_fx01", dst / "data" / "biz_fx02")
    qs = [json.loads(x) for x in (SPLIT / "questions.jsonl").read_text().splitlines()]
    ans = [json.loads(x) for x in (SPLIT / "answers.jsonl").read_text().splitlines()]
    extra_q = [{**q, "id": "b_" + q["id"], "business_id": "biz_fx02"} for q in qs]
    extra_a = [{**a, "id": "b_" + a["id"]} for a in ans]
    (dst / "questions.jsonl").write_text("\n".join(json.dumps(x) for x in qs + extra_q) + "\n")
    (dst / "answers.jsonl").write_text("\n".join(json.dumps(x) for x in ans + extra_a) + "\n")
    return dst


def test_fold_split_holds_out_whole_businesses_with_their_answers(two_biz_train, tmp_path):
    out0, out1 = tmp_path / "f0", tmp_path / "f1"
    b0 = bakeoff.make_fold_split(two_biz_train, out0, 0, 2)
    b1 = bakeoff.make_fold_split(two_biz_train, out1, 1, 2)
    assert sorted(b0 + b1) == ["biz_fx01", "biz_fx02"] and not set(b0) & set(b1)
    for out, biz in ((out0, b0), (out1, b1)):
        qs = [json.loads(x) for x in (out / "questions.jsonl").read_text().splitlines()]
        ans = [json.loads(x) for x in (out / "answers.jsonl").read_text().splitlines()]
        assert {q["business_id"] for q in qs} == set(biz) and len(qs) == 13  # all questions of the business
        assert {a["id"] for a in ans} == {q["id"] for q in qs}
        assert (out / "data").is_symlink() and (out / "rulebook.md").exists()
    capped = bakeoff.make_fold_split(two_biz_train, tmp_path / "cap", 0, 2, max_per_business=3)
    assert len((tmp_path / "cap" / "questions.jsonl").read_text().splitlines()) == 3 and capped == b0


@pytest.fixture
def fixture_runs(tmp_path):
    runs = []
    for name in ("a", "b"):
        out = tmp_path / name
        assert main(["--dev", "--config", str(REPO / "config" / "dev.json"), "--data-dir", str(SPLIT),
                     "--result-dir", str(out), "--set", f"work_dir={tmp_path / ('w' + name)}",
                     "--set", f"model.script_path={SCRIPT}", "--set", "exec_limits.workers=1"]) == 0
        runs.append(out)
    return runs


def test_determinism_report_on_identical_and_perturbed_runs(fixture_runs, tmp_path):
    a, b = fixture_runs
    d = bakeoff.compare_determinism(a, b, SPLIT / "answers.jsonl")
    assert d["questions"] == 13 and d["answers_changed"] == 0 and d["submissions_byte_identical"]
    assert d["calls_same_request_different_output"] == 0 and d["identical_output_rate"] == 1.0
    assert d["calls_same_request"] == d["calls_total"] > 0
    assert d["pa_a"] == d["pa_b"] == 1.0 and d["delta_pa"] == 0.0
    # perturb run b: one raw output differs and one final answer changes
    p = b / "logs" / "questions.jsonl"
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
    rows[0]["calls"][0]["content"] += " "
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    sub = b / "submission.jsonl"
    lines = sub.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    lines[0] = json.dumps({"id": first["id"], "type": "abstain"})
    sub.write_text("\n".join(lines) + "\n", encoding="utf-8")
    d = bakeoff.compare_determinism(a, b, SPLIT / "answers.jsonl")
    assert d["calls_same_request_different_output"] == 1 and d["answers_changed"] == 1
    assert d["changed_ids"] == [first["id"]] and not d["submissions_byte_identical"]
    assert d["by_stage"]["parse"]["different_output"] == 1
    assert d["delta_pa"] == pytest.approx(1 / 13)  # one answer went from +1 to 0


def test_throughput_and_summary_from_a_real_run_directory(fixture_runs):
    t = bakeoff.throughput(fixture_runs[0])
    assert t["questions"] == 13 and t["wall_s"] > 0 and t["elapsed_ms_p50"] is not None
    s = bakeoff.run_summary(fixture_runs[0], SPLIT / "answers.jsonl")
    assert s["pa"]["pa"] == 1.0 and "environment" in s and "by_reason" in s


def test_notebook_is_generated_gpu_only_and_valid_python():
    import ast
    gen = load("make_bakeoff_notebook")
    path = REPO / "notebooks" / "BAKEOFF_G4.ipynb"
    assert json.loads(path.read_text()) == gen.build(), "regenerate: python tools/make_bakeoff_notebook.py"
    nb = json.loads(path.read_text())
    assert all(c.get("outputs", []) == [] for c in nb["cells"] if c["cell_type"] == "code")
    code = "\n".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code")
    ast.parse(code)
    for needle in ("ensure_vllm_env", "vllm_command", "train.zip", "snapshot_download", "VLLM_BATCH_INVARIANT", "enable_prefix_caching",
                   "max_num_seqs", "structured_outputs", "meta.json", "bakeoff_report.py"):
        assert needle in code, needle
    # CPU-only work (analysis, licence checks, parameter counts, scoring) is not done on the GPU runtime
    for cpu_only in ("compare_determinism", "verify_candidate", "count_params", "datamate.eval.score"):
        assert cpu_only not in code, cpu_only


def test_report_runs_on_cpu_from_saved_runs(fixture_runs, tmp_path, capsys):
    report = load("bakeoff_report")
    root = tmp_path / "bake"
    (root / "runs").mkdir(parents=True)
    a, b = fixture_runs
    for src, tag in ((a, "m-A1"), (b, "m-A2"), (a, "m-D-baseline-1"), (b, "m-D-baseline-2")):
        shutil.copytree(src, root / "runs" / tag)
    shutil.copy(SPLIT / "answers.jsonl", root / "answers.jsonl")
    (root / "meta.json").write_text(json.dumps({
        "commit": "a" * 40, "gpu": "test", "compute_capability": "12.0", "candidates": ["org/m"],
        "models": {"m": "m"}, "variants": ["baseline"], "fold": 0, "exit_codes": {}, "minutes": 1}))
    assert report.main(["--runs", str(root)]) == 0
    out = capsys.readouterr().out
    assert "PA 1.0000" in out and "0 answers changed" in out and "baseline identical output rate 1.0" in out
    assert (root / "report.json").is_file()
    (root / "runs" / "m-A2" / "submission.jsonl").unlink()
    assert "runs missing or failed" in json.dumps(report.report(root, False, None))


def test_structured_outputs_switch_removes_response_format_from_the_request():
    from datamate.config import ModelConfig
    from datamate.llm.http import build_request_body
    kw = dict(stage="parse", template_id="t.v1", messages=[{"role": "user", "content": "x"}],
              json_schema={"type": "object"}, max_tokens=8)
    assert "response_format" in build_request_body(ModelConfig(), **kw)
    assert "response_format" not in build_request_body(ModelConfig(structured_outputs=False), **kw)
