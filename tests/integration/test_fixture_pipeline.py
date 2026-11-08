"""End-to-end CPU pipeline on the synthetic fixture (development path, scripted model).

Expected answers in tests/fixtures/split_mini/answers.jsonl were computed by
hand from ban_hang.csv (derivations in tests/fixtures/README.md), not by
running the pipeline. Passing this test says the plumbing is correct; it says
nothing about competition accuracy.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from datamate.eval.score import score_files
from datamate.run import main

from conftest import REPO, SCRIPT, SPLIT, run_one

DEV_ARGS = ["--dev", "--config", str(REPO / "config" / "dev.json")]


def _run(tmp_path: Path, *extra: str) -> tuple[int, Path]:
    out = tmp_path / "result"
    code = main([*extra, "--data-dir", str(SPLIT), "--result-dir", str(out)])
    return code, out


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_fixture_pipeline_end_to_end(tmp_path: Path) -> None:
    code, out = _run(tmp_path, *DEV_ARGS, "--set", f"work_dir={tmp_path / 'work'}",
                     "--set", f"model.script_path={SCRIPT}")
    assert code == 0
    subs = _jsonl(out / "submission.jsonl")
    questions = _jsonl(SPLIT / "questions.jsonl")
    assert [s["id"] for s in subs] == [q["id"] for q in questions]  # one line per id

    result = score_files(out / "submission.jsonl", SPLIT / "answers.jsonl")
    assert result["per_id"] == {q["id"]: 1 for q in questions}

    logs = {r["id"]: r for r in _jsonl(out / "logs" / "questions.jsonl")}
    assert set(logs) == {q["id"] for q in questions}
    for sub in subs:
        log = logs[sub["id"]]
        # Docker guide §3.3 required fields, recorded from the actual run
        assert {"id", "answer", "elapsed_ms", "thinking", "code", "output"} <= set(log)
        assert log["answer"] == {k: v for k, v in sub.items() if k != "id"}
        assert isinstance(log["elapsed_ms"], int) and log["elapsed_ms"] >= 0
        assert log["thinking"] is None  # the scripted client produces no reasoning
        assert all(c["backend"] == "scripted" for c in log["calls"])

    # Resolved windows (generic temporal parameters; as_of 2026-03-04 is a Wednesday)
    def window(qid: str) -> tuple[str, str]:
        w = logs[qid]["windows"][0]
        return w["start"], w["end"]

    assert window("fx_q01") == ("2026-02-23", "2026-03-01")  # tuần rồi: full Mon–Sun
    assert window("fx_q04") == ("2026-03-01", "2026-03-04")  # tháng này: to today
    assert window("fx_q08") == ("2026-03-02", "2026-03-04")  # tuần này: Monday to today
    assert window("fx_q12") == ("2026-02-26", "2026-03-04")  # 7 ngày gần nhất incl. today

    # Repair path: first SQL fails, the repaired SQL answers; both are logged in order.
    assert [a["error_code"] for a in logs["fx_q06"]["attempts"]] == ["E_SQL_EXEC", None]
    assert isinstance(logs["fx_q06"]["code"], list) and len(logs["fx_q06"]["code"]) == 2
    # No SQL runs for questions decided before solving.
    assert logs["fx_q07"]["code"] is None and logs["fx_q09"]["code"] is None

    run = json.loads((out / "logs" / "run.json").read_text(encoding="utf-8"))
    assert run["dev_mode"] is True and run["model_backend"] == "scripted"
    assert "parse.frame.v2" in run["template_sha256"]


def test_yearless_comparison_runs_through_parser_and_solver(cfg, split, catalog):
    text = "Từ 1/3 đến 4/3 có nhiều đơn hơn cùng kỳ tháng trước không?"
    frame = {"expected_type": "boolean", "time": [
        {"span": "Từ 1/3 đến 4/3", "expr": {"kind": "date_range",
         "start": {"month": 3, "day": 1, "year": None}, "end": {"month": 3, "day": 4, "year": None}}},
        {"span": "cùng kỳ tháng trước", "role": "comparison",
         "expr": {"kind": "same_days_previous_month", "ref": 0}},
    ]}
    # DH009–011 vs. DH003. The fixture's later order DH012 is outside both windows.
    sql = {"sql": "SELECT COUNT(DISTINCT ma_don) FILTER (WHERE ngay_dat BETWEEN DATE '2026-03-01'"
                  " AND DATE '2026-03-04') > COUNT(DISTINCT ma_don) FILTER (WHERE ngay_dat BETWEEN"
                  " DATE '2026-02-01' AND DATE '2026-02-04') AS value FROM ban_hang"}
    record, log = run_one(text, frame, sql, cfg=cfg, split=split, catalog=catalog)
    assert record == {"id": "t_q1", "type": "boolean", "answer": True}
    assert log.calls[0].template_id == "parse.frame.v2"
    assert [(w.role, w.start.isoformat(), w.end.isoformat()) for w in log.windows] == [
        ("primary", "2026-03-01", "2026-03-04"), ("comparison", "2026-02-01", "2026-02-04"),
    ]
    assert [call.stage for call in log.calls] == ["parse", "solve"]


@pytest.mark.parametrize("source_ref, expected_type, reason", [
    (0, "unanswerable", "D_UNANSWERABLE_OUT_OF_RANGE"), (3, "abstain", "E_TIME_UNSUPPORTED"),
])
def test_comparison_without_data_or_source_skips_sql(cfg, split, catalog, source_ref, expected_type, reason):
    text = "Tháng này có nhiều đơn hơn cùng kỳ năm ngoái không?"
    frame = {"expected_type": "boolean", "time": [
        {"span": "Tháng này", "expr": {"kind": "relative_period", "unit": "month", "offset": 0}},
        {"span": "cùng kỳ năm ngoái", "role": "comparison",
         "expr": {"kind": "same_period_prior_year", "ref": source_ref}},
    ]}
    record, log = run_one(text, frame, cfg=cfg, split=split, catalog=catalog)
    assert record["type"] == expected_type
    assert log.decision["reason_code"] == reason
    assert [call.stage for call in log.calls] == ["parse"] and log.code is None


def test_fixture_pipeline_is_deterministic(tmp_path: Path) -> None:
    args = [*DEV_ARGS, "--set", f"work_dir={tmp_path / 'work'}", "--set",
            f"model.script_path={SCRIPT}"]
    a = tmp_path / "a"
    b = tmp_path / "b"
    assert main([*args, "--data-dir", str(SPLIT), "--result-dir", str(a)]) == 0
    assert main([*args, "--data-dir", str(SPLIT), "--result-dir", str(b)]) == 0
    assert (a / "submission.jsonl").read_bytes() == (b / "submission.jsonl").read_bytes()


def test_production_mode_rejects_scripted_backend(tmp_path: Path, capsys) -> None:
    code, out = _run(tmp_path, "--config", str(REPO / "config" / "dev.json"))
    assert code == 2
    assert "development-only" in capsys.readouterr().err
    assert not (out / "submission.jsonl").exists()


def test_production_config_fails_clearly_until_client_exists(tmp_path: Path, capsys) -> None:
    code, out = _run(tmp_path, "--config", str(REPO / "config" / "run_config.json"))
    assert code == 2
    assert "M3-02" in capsys.readouterr().err
    assert not (out / "submission.jsonl").exists()


def test_overrides_rejected_without_dev(tmp_path: Path) -> None:
    code, out = _run(tmp_path, "--set", "model.backend=scripted")
    assert code == 2
    assert not out.exists()
