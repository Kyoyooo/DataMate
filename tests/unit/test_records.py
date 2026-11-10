"""M4-07: complete log/run records and bounded log size (CPU)."""

from __future__ import annotations

import hashlib
import json
import sys

from test_replicas import FAKE, free_port

from datamate.contracts import CONTRACTS_VERSION, LogRecord, ModelCall
from datamate.run import main
from datamate.runtime.environment import fingerprint, model_record
from datamate.runtime.promptstore import PromptBlobStore

from conftest import SPLIT

BIG = "RULEBOOK " * 5000


def call_with(body):
    return ModelCall(call_id="c", stage="parse", template_id="t", backend="http",
                     request_sha256="0" * 64, params={}, content="x", reasoning=None,
                     finish_reason="stop", latency_ms=1, transport={"request_body": body,
                                                                    "http_status": 200})


def test_compact_replaces_large_messages_and_schema_with_hash_references(tmp_path):
    store = PromptBlobStore(tmp_path / "blobs.jsonl")
    body = {"messages": [{"role": "system", "content": BIG}, {"role": "user", "content": "câu hỏi?"}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "n", "strict": True, "schema": {"type": "object", "x": "y" * 900}}}}
    a, b = store.compact(call_with(body)), store.compact(call_with(body))
    store.finalize()
    req = a.transport["request_body"]
    assert req["messages"][0] == {"role": "system", "content_sha256":
                                  hashlib.sha256(BIG.encode()).hexdigest(), "content_chars": len(BIG)}
    assert req["messages"][1] == {"role": "user", "content": "câu hỏi?"}  # small stays inline
    assert "schema" not in req["response_format"]["json_schema"]
    assert len(json.dumps(a.model_dump(mode="json"))) < 1500 and a == b
    rows = [json.loads(x) for x in (tmp_path / "blobs.jsonl").read_text().splitlines()]
    assert len(rows) == 2  # system prompt and schema, once each despite two calls
    by_sha = {r["sha256"]: r["text"] for r in rows}
    assert by_sha[req["messages"][0]["content_sha256"]] == BIG
    assert [r["sha256"] for r in rows] == sorted(by_sha)  # canonical order
    assert body["messages"][0]["content"] == BIG  # the original call object is not mutated


def test_environment_fingerprint_reports_only_what_exists(tmp_path):
    fp = fingerprint((tmp_path,))
    assert fp["python"].startswith("3.") and fp["packages"]["duckdb"] and fp["lock_sha256"] is None
    (tmp_path / "requirements.lock").write_text("duckdb==1\n")
    (tmp_path / "BUILD_INFO.json").write_text('{"git_commit": "abc"}')
    fp = fingerprint((tmp_path,))
    assert fp["lock_sha256"] == hashlib.sha256(b"duckdb==1\n").hexdigest()
    assert fp["build_info"] == {"git_commit": "abc"}
    m = tmp_path / "model"
    m.mkdir()
    (m / "w.safetensors").write_bytes(b"123")
    (m / "SHA256SUMS").write_text("x  w.safetensors\n")
    rec = model_record(str(m), "dm", "http", "deadbeef")
    assert rec["files"] == [{"path": "SHA256SUMS", "size": 17}, {"path": "w.safetensors", "size": 3}]
    assert rec["sha256sums_sha256"] and rec["revision"] == "deadbeef"
    assert model_record(None, "dm", "scripted", None)["files"] is None


def test_real_http_run_records_are_complete_and_log_size_is_bounded(tmp_path):
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (tmp_path / "cfg.json").write_text(json.dumps({
        "work_dir": str(tmp_path / "w"), "model": {"path": str(model_dir), "revision": "rev1"},
        "serving": {"mode": "managed", "replicas": 2, "base_port": free_port(),
                    "vllm_command": [sys.executable, FAKE], "startup_timeout_s": 20,
                    "health_poll_interval_s": 0.05, "shutdown_timeout_s": 5},
        "concurrency": {"questions_per_replica": 2}}))
    out = tmp_path / "out"
    assert main(["--config", str(tmp_path / "cfg.json"), "--data-dir", str(SPLIT),
                 "--result-dir", str(out)]) == 0
    logs = out / "logs"
    lines = (logs / "questions.jsonl").read_text(encoding="utf-8").splitlines()
    records = [LogRecord.model_validate_json(x) for x in lines]  # every line validates
    assert len(records) == 13 and {r.contracts_version for r in records} == {CONTRACTS_VERSION}
    blobs = {json.loads(x)["sha256"]: json.loads(x)["text"]
             for x in (logs / "prompt_blobs.jsonl").read_text(encoding="utf-8").splitlines()}
    assert len(blobs) == 2  # one system prompt for the business + one response schema, not 13 copies
    for r in records:
        for c in r.calls:
            req = c.transport["request_body"]
            ref = req["messages"][0]
            assert ref["content_sha256"] in blobs and "content" not in ref
            assert c.request_sha256 and c.transport["request_compacted"] is True
    schema_refs = {c.transport["request_body"]["response_format"]["json_schema"]["schema_sha256"]
                   for r in records for c in r.calls}
    assert schema_refs <= set(blobs)
    # the rebuilt request hashes to request_sha256: nothing was lost by compaction
    from datamate.llm.http import http_request_sha256
    c = records[0].calls[0]
    body = json.loads(json.dumps(c.transport["request_body"]))
    body["messages"] = [{"role": m["role"], "content": blobs[m["content_sha256"]]}
                        if "content_sha256" in m else m for m in body["messages"]]
    body["response_format"]["json_schema"]["schema"] = json.loads(
        blobs[body["response_format"]["json_schema"].pop("schema_sha256")])
    assert http_request_sha256(body) == c.request_sha256

    run = json.loads((logs / "run.json").read_text())
    assert run["model"]["revision"] == "rev1" and run["model"]["files"] == []
    assert run["environment"]["python"] and "packages" in run["environment"]
    assert set(run["template_sha256"]) >= {"parse.frame.v3", "solve.sql.v1"}
    assert len(run["timings"]["replica_load_ms"]) == 2 and run["timings"]["total_ms"] >= 0
    assert run["timings"]["first_answer_ms"] is not None and "degrade_activated_ms" in run
    assert run["replicas"]["commands"][0][0] == sys.executable
    biz = [json.loads(x) for x in (logs / "businesses.jsonl").read_text().splitlines()]
    assert biz[0]["setup_ms"] is not None and biz[0]["status"] == "ready"
