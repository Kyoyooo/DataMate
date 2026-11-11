"""M4-11 fault injection (CPU): every fault ends with exit 0, every id written once, and a
result directory that passes tools/precheck.py.

Input faults run the scripted development pipeline on a broken copy of the fixture split.
Model faults use stub clients. Signal faults run the real CLI with managed serving against the
fake vLLM server (tests/fixtures/fake_vllm_server.py), exactly as predict.sh starts it.
"""

from __future__ import annotations

import collections
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from datamate.contracts import ModelCall, codes
from datamate.run import main, run

from conftest import REPO, SPLIT

FAKE = str(REPO / "tests" / "fixtures" / "fake_vllm_server.py")


def _precheck():
    spec = importlib.util.spec_from_file_location("precheck", REPO / "tools" / "precheck.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["precheck"] = mod
    spec.loader.exec_module(mod)
    return mod


PRECHECK = _precheck()


def records(out: Path) -> list[dict]:
    return [json.loads(x) for x in (out / "logs" / "questions.jsonl").read_text().splitlines()]


def assert_complete(data: Path, out: Path) -> collections.Counter:
    """Exit-independent completeness: precheck passes and every distinct input id is written once."""
    assert PRECHECK.main(["--data-dir", str(data), "--result-dir", str(out)]) == 0
    ids = []
    for line in (data / "questions.jsonl").read_text(encoding="utf-8-sig").splitlines():
        try:
            qid = json.loads(line).get("id")
        except (json.JSONDecodeError, AttributeError):
            continue
        if isinstance(qid, str) and qid:
            ids.append(qid)
    sub = [json.loads(x) for x in (out / "submission.jsonl").read_text().splitlines()]
    assert sorted(s["id"] for s in sub) == sorted(set(ids))
    return collections.Counter(r["decision"]["reason_code"] for r in records(out))


def broken_copy(tmp: Path, name: str) -> Path:
    d = tmp / name
    shutil.copytree(SPLIT, d)
    return d


def dev_main(data: Path, out: Path, tmp: Path) -> int:
    return main(["--dev", "--config", str(REPO / "config" / "dev.json"), "--data-dir", str(data),
                 "--result-dir", str(out), "--set", f"work_dir={tmp / 'work'}",
                 "--set", "exec_limits.workers=2"])


def _rm(d: Path, *names: str) -> None:
    for n in names:
        (d / n).unlink()


def _write(d: Path, rel: str, data: bytes) -> None:
    (d / rel).write_bytes(data)


INPUT_FAULTS = {
    "no_rulebook": lambda d: _rm(d, "rulebook.md"),
    "no_calendar": lambda d: _rm(d, "calendar.csv"),
    "binary_calendar": lambda d: _write(d, "calendar.csv", b"\x00\xff garbage,\n"),
    "binary_rulebook": lambda d: _write(d, "rulebook.md", b"\xff\xfe\x00garbage"),
    "bad_question_lines": lambda d: (d / "questions.jsonl").write_text(
        (d / "questions.jsonl").read_text() + '{not json\n{"id": "q_no_fields"}\n[1, 2]\n'),
    "duplicate_ids": lambda d: (d / "questions.jsonl").write_text(
        (d / "questions.jsonl").read_text() + (d / "questions.jsonl").read_text().splitlines()[0] + "\n"),
    "bom_and_crlf_questions": lambda d: (d / "questions.jsonl").write_bytes(
        b"\xef\xbb\xbf" + (d / "questions.jsonl").read_bytes().replace(b"\n", b"\r\n")),
    "unknown_business": lambda d: (d / "questions.jsonl").write_text(
        (d / "questions.jsonl").read_text().replace('"biz_fx01"', '"biz_absent"', 1)),
    "corrupt_extra_workbook": lambda d: _write(d, "data/biz_fx01/extra.xlsx", b"not a zip file"),
    "corrupt_only_table": lambda d: _write(d, "data/biz_fx01/ban_hang.csv", b"\x00\x01\xff garbage"),
    "empty_business_dir": lambda d: [p.unlink() for p in (d / "data" / "biz_fx01").iterdir()],
    "empty_questions": lambda d: (d / "questions.jsonl").write_text(""),
}


@pytest.mark.parametrize("fault", sorted(INPUT_FAULTS))
def test_input_fault_still_gives_a_complete_valid_result(fault, tmp_path):
    data = broken_copy(tmp_path, fault)
    INPUT_FAULTS[fault](data)
    out = tmp_path / "out"
    assert dev_main(data, out, tmp_path) == 0
    reasons = assert_complete(data, out)
    if fault in ("no_rulebook", "no_calendar", "binary_calendar", "binary_rulebook", "duplicate_ids",
                 "bom_and_crlf_questions"):
        assert reasons["D_ANSWER"] == 11  # generic defaults; nothing lost
    if fault == "bad_question_lines":
        assert reasons["E_INPUT_INVALID"] == 1 and reasons["D_ANSWER"] == 11
    if fault == "unknown_business":
        assert reasons[codes.E_INPUT_BUSINESS_MISSING] == 1
    if fault == "corrupt_extra_workbook":
        # one unreadable file is skipped with W_UNSUPPORTED_FILE; the business stays usable
        biz = json.loads((out / "logs" / "businesses.jsonl").read_text().splitlines()[0])
        assert biz["status"] == "ready"
        assert any(w.startswith("W_UNSUPPORTED_FILE extra.xlsx") for w in biz["warnings"])
        assert reasons["D_ANSWER"] >= 10
        assert "D_UNANSWERABLE_CONFIRMED" not in reasons  # incomplete schema: never confirm missing
    if fault in ("corrupt_only_table", "empty_business_dir"):
        assert sum(reasons.values()) == 13 and "D_ANSWER" not in reasons


def test_existing_result_files_are_kept_not_overwritten(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "submission.jsonl").write_text("old\n")
    assert dev_main(SPLIT, out, tmp_path) == 0
    assert (out / "submission.jsonl.prev-1").read_text() == "old\n"
    assert_complete(SPLIT, out)


class ErrorClient:
    backend, dev_only = "stub", True

    def __init__(self, error: str | None = None, raise_exc: bool = False):
        self.error, self.raise_exc = error, raise_exc

    def complete(self, *, stage, template_id, messages, json_schema, max_tokens, call_id, **_):
        if self.raise_exc:
            raise RuntimeError("model client bug")
        return ModelCall(call_id=call_id, stage=stage, template_id=template_id, backend="stub",
                         request_sha256="0" * 64, params={}, content="", reasoning=None,
                         finish_reason="error", latency_ms=0, error=self.error)


@pytest.mark.parametrize("client,expected", [
    (ErrorClient(codes.E_MODEL_ERROR), codes.E_MODEL_ERROR),
    (ErrorClient(codes.E_MODEL_TIMEOUT), codes.E_MODEL_TIMEOUT),
    (ErrorClient(raise_exc=True), codes.E_INTERNAL),
])
def test_model_failures_abstain_and_write_every_id(client, expected, cfg, tmp_path):
    out = tmp_path / "out"
    assert run(cfg, client, SPLIT, out, dev=True, overrides=[]) == 0
    reasons = assert_complete(SPLIT, out)
    assert set(reasons) == {expected}
    assert all(json.loads(x)["type"] == "abstain" for x in (out / "submission.jsonl").read_text().splitlines())


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _managed_cli(tmp: Path, env: dict[str, str], workers: int = 2) -> tuple[subprocess.Popen, Path]:
    model = tmp / "model"
    model.mkdir()
    conf = {"work_dir": str(tmp / "work"), "model": {"path": str(model)},
            "serving": {"mode": "managed", "replicas": 1, "base_port": _free_port(),
                        "vllm_command": [sys.executable, FAKE], "startup_timeout_s": 120,
                        "health_poll_interval_s": 0.05, "shutdown_timeout_s": 5, "env": env},
            "concurrency": {"questions_per_replica": workers}, "solver": {"tokenizer": "estimate"},
            "exec_limits": {"workers": 2}}
    (tmp / "cfg.json").write_text(json.dumps(conf))
    out = tmp / "out"
    proc = subprocess.Popen([sys.executable, "-m", "datamate.run", "--config", str(tmp / "cfg.json"),
                             "--data-dir", str(SPLIT), "--result-dir", str(out)],
                            cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            env={**os.environ, "PYTHONHASHSEED": "0"})
    return proc, out


def _wait_for(pred, timeout: float) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.1)
    return False


def test_sigterm_during_the_run_writes_every_id(tmp_path):
    proc, out = _managed_cli(tmp_path, {"FAKE_VLLM_REPLY_DELAY_S": "1.5"}, workers=1)
    qlog = out / "logs" / "questions.jsonl"
    assert _wait_for(lambda: qlog.is_file() and len(qlog.read_text().splitlines()) >= 1, 60)
    proc.send_signal(signal.SIGTERM)
    output, _ = proc.communicate(timeout=60)
    assert proc.returncode == 0, output
    reasons = assert_complete(SPLIT, out)
    assert reasons[codes.E_GLOBAL_STOP] >= 1
    assert json.loads((out / "logs" / "run.json").read_text())["orchestrator"]["stop_reason"] == "sigterm"


def test_sigterm_while_the_model_is_loading_writes_every_id(tmp_path):
    proc, out = _managed_cli(tmp_path, {"FAKE_VLLM_STARTUP_S": "60"})
    log = out / "logs" / "replica-0.log"
    assert _wait_for(lambda: log.is_file(), 30)
    time.sleep(0.5)
    started = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    output, _ = proc.communicate(timeout=60)
    assert proc.returncode == 0, output
    assert time.monotonic() - started < 30  # did not wait for the server
    reasons = assert_complete(SPLIT, out)
    assert set(reasons) == {codes.E_GLOBAL_STOP}
    assert "SIGTERM during model server startup" in output
