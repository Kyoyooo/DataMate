"""M4-05 acceptance: concurrency, deadlines, stops and replica failure on CPU."""

from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

from datamate.config import RunConfig, load_config
from datamate.contracts import ModelCall
from datamate.llm import ScriptedModelClient
from datamate.run import run
from datamate.runtime.orchestrator import Orchestrator, assign_businesses

from conftest import SCRIPT, SPLIT


def test_assignment_follows_spec_7_12(tmp_path):
    # order (count desc, id asc): a5, b3, c3, d1; each goes to the replica with the smaller total
    assert assign_businesses({"d": 1, "c": 3, "b": 3, "a": 5}, 2) == {"a": 0, "b": 1, "c": 1, "d": 0}
    assert assign_businesses({"x": 2}, 1) == {"x": 0}


def two_business_split(tmp_path: Path) -> Path:
    dst = tmp_path / "split2"
    shutil.copytree(SPLIT, dst)
    shutil.copytree(dst / "data" / "biz_fx01", dst / "data" / "biz_fx02")
    lines = [json.loads(x) for x in (SPLIT / "questions.jsonl").read_text().splitlines()]
    extra = [{**q, "id": q["id"].replace("fx_", "fy_"), "business_id": "biz_fx02"} for q in lines]
    (dst / "questions.jsonl").write_text(
        "\n".join(json.dumps(q, ensure_ascii=False) for q in lines + extra) + "\n")
    return dst


def fresh_clients(n):
    return [ScriptedModelClient.from_file(SCRIPT) for _ in range(n)]


def cfg_for(tmp_path, **kw):
    sets = [f"work_dir={tmp_path / 'work'}", "model.backend=scripted"]
    sets += [f"{k.replace('__', '.')}={v}" for k, v in kw.items()]
    return load_config(None, sets)


def test_identical_submission_bytes_with_1_and_n_workers(tmp_path):
    split = two_business_split(tmp_path)
    outs = {}
    for name, workers in (("w1", 1), ("w8", 8)):
        cfg = cfg_for(tmp_path / name, concurrency__questions_per_replica=workers)
        out = tmp_path / name / "out"
        assert run(cfg, fresh_clients(2), split, out, dev=True, overrides=[]) == 0
        outs[name] = out
    for f in ("submission.jsonl",):
        assert (outs["w1"] / f).read_bytes() == (outs["w8"] / f).read_bytes()
    lines = (outs["w8"] / "submission.jsonl").read_text().splitlines()
    assert len(lines) == 26 and len({json.loads(x)["id"] for x in lines}) == 26
    # the log file is canonical too, apart from timing
    def strip(p):
        rows = [json.loads(x) for x in (p / "logs" / "questions.jsonl").read_text().splitlines()]
        for r in rows:
            r.pop("elapsed_ms")
            for c in r["calls"]:
                c.pop("latency_ms")
            for a in r["attempts"]:
                a.pop("duration_ms")
        return rows
    assert strip(outs["w1"]) == strip(outs["w8"])
    run_json = json.loads((outs["w8"] / "logs" / "run.json").read_text())
    assert run_json["replica_assignment"] == {"biz_fx01": 0, "biz_fx02": 1}
    assert run_json["orchestrator"]["questions_per_replica"] == [13, 13]


def test_single_client_still_works_like_before(tmp_path):
    cfg = cfg_for(tmp_path)
    assert run(cfg, ScriptedModelClient.from_file(SCRIPT), SPLIT, tmp_path / "o", dev=True,
               overrides=[]) == 0


class BlockingClient:
    """Every call blocks for its allowed time (timeout_s) and then reports a timeout."""

    backend, dev_only = "fake", True

    def __init__(self):
        self.timeouts: list[float | None] = []

    def complete(self, *, stage, template_id, messages, json_schema, max_tokens, call_id,
                 timeout_s=None):
        self.timeouts.append(timeout_s)
        time.sleep(min(timeout_s if timeout_s is not None else 5, 5))
        return ModelCall(call_id=call_id, stage=stage, template_id=template_id, backend="fake",
                         request_sha256="0" * 64, params={}, content="", reasoning=None,
                         finish_reason="error", latency_ms=0, error="E_MODEL_TIMEOUT")


def reasons(out: Path) -> dict[str, str]:
    return {r["id"]: r["decision"]["reason_code"] for r in
            (json.loads(x) for x in (out / "logs" / "questions.jsonl").read_text().splitlines())}


def test_hard_deadline_caps_the_model_call_and_abstains(tmp_path):
    cfg = cfg_for(tmp_path, deadlines__question_soft_s=0.2, deadlines__question_hard_s=0.4,
                  concurrency__questions_per_replica=13)
    client, out = BlockingClient(), tmp_path / "out"
    started = time.monotonic()
    assert run(cfg, client, SPLIT, out, dev=True, overrides=[]) == 0
    assert time.monotonic() - started < 4
    assert set(reasons(out).values()) == {"E_DEADLINE"}
    assert all(t is not None and t <= 0.4 for t in client.timeouts)
    assert all(json.loads(x)["type"] == "abstain" for x in (out / "submission.jsonl").read_text().splitlines())


def test_global_stop_writes_every_id(tmp_path):
    cfg = cfg_for(tmp_path, deadlines__global_hard_stop_s=0.5, concurrency__questions_per_replica=2)
    out = tmp_path / "out"
    started = time.monotonic()
    assert run(cfg, BlockingClient(), SPLIT, out, dev=True, overrides=[]) == 0
    assert time.monotonic() - started < 4
    assert len((out / "submission.jsonl").read_text().splitlines()) == 13
    assert set(reasons(out).values()) <= {"E_GLOBAL_STOP"}
    assert json.loads((out / "logs" / "run.json").read_text())["orchestrator"]["stop_reason"] == "global_stop"


def test_sigterm_path_abstains_unwritten_ids_immediately(tmp_path):
    from datamate.catalog import setup_business
    from datamate.rules import load_split
    from datamate.run import load_questions
    from datamate.runtime import ResultWriter

    cfg = cfg_for(tmp_path, concurrency__questions_per_replica=2)
    questions, _, _ = load_questions(SPLIT / "questions.jsonl")
    with ResultWriter(tmp_path / "out") as writer:
        orch = Orchestrator(
            cfg=cfg, split=load_split(SPLIT), questions=questions, clients=[BlockingClient()],
            writer=writer,
            setup=lambda b: (setup_business(SPLIT / "data" / b, b, tmp_path / "work"), None))
        threading.Timer(0.5, orch.request_stop).start()
        started = time.monotonic()
        stats = orch.run()
        assert time.monotonic() - started < 3  # the blocked calls last 5 s each
        assert stats.stop_reason == "sigterm"
        assert len(writer.written_ids()) == 13
        assert set(stats.reasons) == {"E_GLOBAL_STOP"}
        # a late result for an id that is already written is dropped, never duplicated
        late = next(iter(questions))
        from datamate.runtime.orchestrator import _abstain
        assert writer.try_write(*_abstain(late, "E_INTERNAL", None)) is False


class FlakySupervisor:
    def __init__(self):
        self.polls = 0
        self.restarts = []

    def poll(self):
        self.polls += 1
        return [0] if self.polls == 1 else []

    def restart(self, i):
        self.restarts.append(i)
        return False


def test_dead_replica_queue_is_drained_to_the_other_replica(tmp_path):
    split = two_business_split(tmp_path)
    cfg = cfg_for(tmp_path, concurrency__questions_per_replica=2)
    sup, out = FlakySupervisor(), tmp_path / "out"
    clients = fresh_clients(2)
    assert run(cfg, clients, split, out, dev=True, overrides=[], supervisor=sup) == 0
    assert sup.restarts == [0]
    lines = [json.loads(x) for x in (out / "submission.jsonl").read_text().splitlines()]
    assert len(lines) == 26
    per = json.loads((out / "logs" / "run.json").read_text())["orchestrator"]["questions_per_replica"]
    assert sum(per) == 26 and per[1] >= 13  # replica 1 took over what replica 0 had not started


def test_no_client_means_complete_all_abstain_submission(tmp_path):
    out = tmp_path / "out"
    assert run(cfg_for(tmp_path), [], SPLIT, out, dev=True, overrides=[]) == 0
    assert set(reasons(out).values()) == {"E_REPLICA_DOWN"}
    assert len((out / "submission.jsonl").read_text().splitlines()) == 13


def test_projected_finish_uses_recent_throughput():
    now = [0.0]
    cfg = RunConfig()
    from datamate.runtime.writer import ResultWriter  # noqa: F401
    orch = Orchestrator(cfg=cfg, split=None, questions=[], clients=[], writer=None,
                        setup=lambda b: (None, None), clock=lambda: now[0], t0=0.0)
    orch.questions = [object()] * 110  # 110 questions, 20 finished at 2 s each
    orch._finished = 20
    orch._completions.extend(2.0 * i for i in range(20))  # span 38 s over 19 gaps = 2 s each
    now[0] = 40.0
    assert orch.projected_finish_s() == 40.0 + 90 * 2.0


class SoftExpired:
    soft_expired, hard_expired, degrade = True, False, False

    def remaining_s(self):
        return float("inf")


def test_soft_deadline_stops_repairs(cfg, split, catalog):
    from datamate.solver import solve

    from conftest import question, scripted
    text = "Doanh thu tuần rồi là bao nhiêu?"
    parse = {"expected_type": "number", "numeric_kind": "money", "time": []}
    client = scripted(text, parse, {"sql": "SELECT nope FROM missing"},
                      {"sql": "SELECT 1 AS value"})
    from datamate.contracts import QuestionFrame
    frame = QuestionFrame.model_validate(parse)
    attempts = solve(question(text), frame, [], catalog, split, client, cfg, SoftExpired())
    assert len(attempts) == 1 and not attempts[0].ok  # would be 2 without the soft deadline
    client = scripted(text, parse, {"sql": "SELECT nope FROM missing"}, {"sql": "SELECT 1 AS value"})
    assert len(solve(question(text), frame, [], catalog, split, client, cfg)) == 2


def test_managed_serving_end_to_end_with_fake_servers(tmp_path):
    import sys

    from test_replicas import FAKE, free_port

    from datamate.run import main
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    conf = {"work_dir": str(tmp_path / "work"),
            "model": {"path": str(model_dir)},
            "serving": {"mode": "managed", "replicas": 2, "base_port": free_port(),
                        "vllm_command": [sys.executable, FAKE], "startup_timeout_s": 20,
                        "health_poll_interval_s": 0.05, "shutdown_timeout_s": 5},
            "concurrency": {"questions_per_replica": 2}, "solver": {"tokenizer": "estimate"}, "exec_limits": {"workers": 2}}
    (tmp_path / "cfg.json").write_text(json.dumps(conf))
    out = tmp_path / "out"
    assert main(["--config", str(tmp_path / "cfg.json"), "--data-dir", str(SPLIT),
                 "--result-dir", str(out)]) == 0
    # the fake server answers "pong", which is not a QuestionFrame: every question abstains
    assert set(reasons(out).values()) == {"E_PARSE_INVALID"}
    run_json = json.loads((out / "logs" / "run.json").read_text())
    assert run_json["replicas"]["states"] == ["ready", "ready"]  # snapshot before shutdown
    assert all(isinstance(t, int) for t in run_json["replicas"]["replica_load_ms"])
    assert (out / "logs" / "replica-0.log").is_file() and (out / "logs" / "replica-1.log").is_file()


def test_managed_serving_missing_model_exits_2_without_outputs(tmp_path, capsys):
    from datamate.run import main
    (tmp_path / "cfg.json").write_text(json.dumps(
        {"model": {"path": str(tmp_path / "absent")}, "serving": {"mode": "managed"}}))
    out = tmp_path / "out"
    assert main(["--config", str(tmp_path / "cfg.json"), "--data-dir", str(SPLIT),
                 "--result-dir", str(out)]) == 2
    assert "not a directory" in capsys.readouterr().err and not out.exists()


def test_managed_serving_unstartable_replicas_still_deliver_all_abstain(tmp_path):
    from datamate.run import main
    model_dir = tmp_path / "m"
    model_dir.mkdir()
    (tmp_path / "cfg.json").write_text(json.dumps({
        "work_dir": str(tmp_path / "w"), "model": {"path": str(model_dir)},
        "serving": {"mode": "managed", "vllm_command": ["/nonexistent/vllm"]},
        "solver": {"tokenizer": "estimate"}, "exec_limits": {"workers": 2}}))
    out = tmp_path / "out"
    assert main(["--config", str(tmp_path / "cfg.json"), "--data-dir", str(SPLIT),
                 "--result-dir", str(out)]) == 0
    assert set(reasons(out).values()) == {"E_REPLICA_DOWN"}


def test_managed_serving_continues_on_the_surviving_replica(tmp_path):
    import sys

    from test_replicas import FAKE, free_port

    from datamate.run import main
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    conf = {"work_dir": str(tmp_path / "work"), "model": {"path": str(model_dir)},
            "serving": {"mode": "managed", "replicas": 2, "base_port": free_port(),
                        "vllm_command": [sys.executable, FAKE], "startup_timeout_s": 20,
                        "health_poll_interval_s": 0.05, "shutdown_timeout_s": 5,
                        "env": {"FAKE_VLLM_FAIL_GPUS": "1"}},
            "concurrency": {"questions_per_replica": 2}, "solver": {"tokenizer": "estimate"},
            "exec_limits": {"workers": 2}}
    (tmp_path / "cfg.json").write_text(json.dumps(conf))
    out = tmp_path / "out"
    assert main(["--config", str(tmp_path / "cfg.json"), "--data-dir", str(SPLIT),
                 "--result-dir", str(out)]) == 0
    # every question reached replica 0 (the fake answers "pong": parse is invalid, never DOWN)
    assert set(reasons(out).values()) == {"E_PARSE_INVALID"}
    run_json = json.loads((out / "logs" / "run.json").read_text())
    assert run_json["replicas"]["active"] == [0]


def test_global_stop_counts_from_process_start(tmp_path):
    # main() passes its own start time: here the process "started" 10 s ago (model loading),
    # so a 5 s global budget is already spent before any question runs.
    cfg = cfg_for(tmp_path, deadlines__global_hard_stop_s=5)
    out = tmp_path / "out"
    assert run(cfg, fresh_clients(1), SPLIT, out, dev=True, overrides=[],
               started_at=time.monotonic() - 10) == 0
    assert len((out / "submission.jsonl").read_text().splitlines()) == 13
    assert set(reasons(out).values()) == {"E_GLOBAL_STOP"}
