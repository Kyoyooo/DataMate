"""M3-13: recording and replay of model calls (CPU)."""

from __future__ import annotations

import json
import threading

import pytest

from datamate.config import ModelConfig, load_config
from datamate.contracts import codes
from datamate.llm import (
    ProductionGuardError,
    RecordingModelClient,
    ReplayModelClient,
    ScriptedModelClient,
    call_key,
    http_request_sha256,
    make_client,
)
from datamate.llm.http import build_request_body

MSG = [{"role": "user", "content": "Doanh thu?"}]
ENTRY = {"stage": "parse", "question": "Doanh thu?", "content": "  {\"a\": 1}\n", "reasoning": "nghĩ"}


def kwargs(**over):
    base = dict(stage="parse", template_id="t.v1", messages=MSG, json_schema=None, max_tokens=64)
    base.update(over)
    return base


def test_key_is_the_sha256_of_the_http_request_body():
    cfg = ModelConfig()
    body = build_request_body(cfg, **kwargs())
    assert call_key(cfg, **kwargs()) == http_request_sha256(body)


def test_key_changes_with_prompt_params_schema_and_thinking():
    cfg = ModelConfig()
    base = call_key(cfg, **kwargs())
    assert call_key(cfg, **kwargs(messages=[{"role": "user", "content": "Doanh thu ?"}])) != base
    assert call_key(cfg, **kwargs(max_tokens=65)) != base
    assert call_key(cfg, **kwargs(json_schema={"type": "object"})) != base
    assert call_key(ModelConfig(seed=1), **kwargs()) != base
    assert call_key(ModelConfig(enable_thinking={"parse": True}), **kwargs()) != base


def test_record_then_replay_is_exact_and_misses_are_values(tmp_path):
    cfg, path = ModelConfig(backend="scripted"), tmp_path / "calls.jsonl"
    rec = RecordingModelClient(ScriptedModelClient([ENTRY]), path, cfg)
    original = rec.complete(**kwargs(call_id="q1:parse:1"))
    rec.close()
    replay = ReplayModelClient.from_file(path, cfg)
    got = replay.complete(**kwargs(call_id="OTHER:parse:1"))
    assert got.content == original.content == "  {\"a\": 1}\n"  # byte for byte, whitespace kept
    assert got.reasoning == "nghĩ" and got.call_id == "OTHER:parse:1"
    assert got.backend == "replay" and got.transport["recorded_backend"] == "scripted"
    assert got.request_sha256 == call_key(cfg, **kwargs())
    miss = replay.complete(**kwargs(call_id="m", messages=[{"role": "user", "content": "Doanh thu 2?"}]))
    assert miss.error == codes.E_REPLAY_MISS and miss.content == "" and len(replay.misses) == 1


def test_first_recording_wins_and_conflicts_are_counted(tmp_path):
    cfg, path = ModelConfig(), tmp_path / "c.jsonl"
    rec = RecordingModelClient(
        ScriptedModelClient([{**ENTRY, "content": "A"}, {**ENTRY, "content": "B"}]), path, cfg)
    rec.complete(**kwargs(call_id="1"))
    rec.complete(**kwargs(call_id="2"))
    rec.close()
    assert rec.conflicts == 1
    assert ReplayModelClient.from_file(path, cfg).complete(**kwargs(call_id="x")).content == "A"
    assert len(path.read_text().splitlines()) == 2  # header + one record


def test_recording_is_thread_safe(tmp_path):
    cfg, path = ModelConfig(), tmp_path / "c.jsonl"
    entries = [{"stage": "parse", "question": f"q{i}", "content": f"c{i}"} for i in range(40)]
    rec = RecordingModelClient(ScriptedModelClient(entries), path, cfg)
    threads = [threading.Thread(target=rec.complete, kwargs=kwargs(
        messages=[{"role": "user", "content": f"q{i}"}], call_id=str(i))) for i in range(40)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    rec.close()
    rows = [json.loads(x) for x in path.read_text().splitlines()[1:]]
    assert len(rows) == 40 and len({r["request_sha256"] for r in rows}) == 40


def test_bad_header_is_rejected(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"format": "other"}\n')
    with pytest.raises(ValueError, match="datamate.model_calls.v1"):
        ReplayModelClient.from_file(p, ModelConfig())


def test_replay_and_recording_are_development_only(tmp_path):
    (tmp_path / "r.jsonl").write_text('{"format": "datamate.model_calls.v1"}\n')
    with pytest.raises(ProductionGuardError):
        make_client(ModelConfig(backend="replay", replay_path=str(tmp_path / "r.jsonl")), dev=False)
    with pytest.raises(ProductionGuardError):
        make_client(ModelConfig(base_url="http://127.0.0.1:1/v1", record_path=str(tmp_path / "o")),
                    dev=False)
    with pytest.raises(ValueError, match="replay_path"):
        make_client(ModelConfig(backend="replay"), dev=True)
    cfg = load_config(None, ["model.backend=replay"])
    assert cfg.model.backend == "replay"


def _load_tool():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "tools" / "record_model_calls.py"
    spec = importlib.util.spec_from_file_location("record_model_calls", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_recording_tool_subset_and_training_only_guard(tmp_path, capsys):
    from conftest import REPO, SCRIPT, SPLIT
    tool = _load_tool()
    lines = ['{"business_id": "b2", "id": "x1"}', '{"business_id": "b1", "id": "y1"}',
             '{"business_id": "b1", "id": "y2"}', '{"business_id": "b1", "id": "y3"}']
    chosen = tool.subset(lines, 2, 3)
    assert [json.loads(c)["id"] for c in chosen] == ["y1", "y2", "x1"]  # sorted by business id
    out = tmp_path / "rec.jsonl"
    code = tool.main(["--config", str(REPO / "config" / "dev.json"), "--data-dir", str(SPLIT),
                      "--out", str(out), "--per-business", "5", "--max-questions", "4",
                      "--set", f"model.script_path={SCRIPT}", "--set", f"work_dir={tmp_path / 'w'}"])
    assert code == 0 and len(out.read_text().splitlines()) > 1
    no_answers = tmp_path / "split"
    no_answers.mkdir()
    (no_answers / "questions.jsonl").write_text("")
    assert tool.main(["--config", "x", "--data-dir", str(no_answers), "--out", str(out)]) == 2
    assert "training splits only" in capsys.readouterr().err
