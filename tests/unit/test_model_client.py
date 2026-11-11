"""M3-02 acceptance: real local HTTP server, no GPU, weights or external network."""

from __future__ import annotations

import copy
import hashlib
import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic import ValidationError

from datamate.config import ModelConfig, RunConfig
from datamate.contracts import ModelCall, QuestionFrame, SolverOutput, codes
from datamate.llm import (
    HttpModelClient,
    ProductionGuardError,
    http_request_sha256,
    make_client,
    request_sha256,
    schema_for_vllm,
)
from datamate.parse import parse_question
from datamate.runtime import answer_question

from conftest import question

MESSAGES = [{"role": "user", "content": "  Doanh thu tháng này?\n"}]


def response(content="  tiếng Việt\n", reasoning=None, finish="stop"):
    return {"choices": [{"message": {"content": content, "reasoning_content": reasoning},
                         "finish_reason": finish}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3}}


@pytest.fixture
def http_server():
    state = {"actions": [], "requests": [], "lock": threading.Lock()}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = self.rfile.read(int(self.headers["Content-Length"]))
            body = json.loads(data)
            with state["lock"]:
                state["requests"].append((self.path, data, body))
                action = state["actions"].pop(0) if state["actions"] else {}
            if action.get("disconnect"):
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            if action.get("sleep"):
                time.sleep(action["sleep"])
            payload = action.get("payload", response())
            if action.get("echo"):
                payload = response(body["messages"][-1]["content"])
            raw = action.get("raw", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            self.send_response(action.get("status", 200))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            if "location" in action:
                self.send_header("Location", action["location"])
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # the timeout test deliberately closes the client connection

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def client_for(server, **overrides):
    return HttpModelClient(ModelConfig(base_url=server["url"], **overrides))


def call(client, **overrides):
    args = dict(stage="parse", template_id="parse.frame.v3", messages=MESSAGES,
                json_schema=QuestionFrame.model_json_schema(), max_tokens=32, call_id="call:1")
    return client.complete(**{**args, **overrides})


def test_http_request_fields_and_exact_response(http_server, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://invalid.proxy:9999")
    content, reasoning = " \n{\"sql\":\"SELECT 1\"}  ", "  lập luận\n\n"
    http_server["actions"] = [{"payload": response(content, reasoning)}]
    client = client_for(http_server, served_model_name="candidate", temperature=0.2, top_p=0.8,
                        top_k=20, min_p=0.1, presence_penalty=0.2, frequency_penalty=0.3,
                        repetition_penalty=1.1, seed=42, enable_thinking={"solve": True})
    original = SolverOutput.model_json_schema()
    result = call(client, stage="solve", template_id="solve.sql.v1", json_schema=original)
    path, raw, body = http_server["requests"][0]
    assert path == "/v1/chat/completions"
    assert body == {
        "model": "candidate", "messages": MESSAGES, "temperature": 0.2, "top_p": 0.8,
        "top_k": 20, "min_p": 0.1, "presence_penalty": 0.2, "frequency_penalty": 0.3,
        "repetition_penalty": 1.1, "seed": 42, "n": 1, "max_tokens": 32, "stream": False,
        "chat_template_kwargs": {"enable_thinking": True},
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "solve_sql_v1", "schema": original, "strict": True}},
    }
    assert result.content == content and result.reasoning == reasoning
    assert result.error is None and result.backend == "http" and result.finish_reason == "stop"
    assert result.request_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.latency_ms >= 0
    assert result.params == {k: v for k, v in body.items() if k not in {"messages", "response_format"}}
    assert result.transport["request_body"] == body
    assert ModelCall.model_validate_json(result.model_dump_json()) == result


def test_http_hash_covers_actual_body_and_is_order_independent(http_server):
    client = client_for(http_server)
    a = call(client)
    b = call(client, call_id="different-log-id")
    assert a.request_sha256 == b.request_sha256
    body = a.transport["request_body"]
    assert http_request_sha256(dict(reversed(list(body.items())))) == a.request_sha256
    for key, value in [("seed", 5), ("model", "other"), ("max_tokens", 50),
                       ("chat_template_kwargs", {"enable_thinking": True}),
                       ("response_format", {"type": "json_object"}),
                       ("messages", [{"role": "user", "content": "other"}])]:
        assert http_request_sha256({**body, key: value}) != a.request_sha256
    legacy = {"messages": MESSAGES, "params": {"temperature": 0.0}, "json_schema": None}
    expected = hashlib.sha256(json.dumps(legacy, sort_keys=True, ensure_ascii=False,
                                        separators=(",", ":")).encode()).hexdigest()
    assert request_sha256(MESSAGES, {"temperature": 0.0}, None) == expected


def test_schema_adapter_is_targeted_and_does_not_mutate_contract():
    original = QuestionFrame.model_json_schema()
    before = copy.deepcopy(original)
    wire = schema_for_vllm(original)
    expr = wire["$defs"]["TimeRef"]["properties"]["expr"]
    assert "oneOf" not in expr and "discriminator" not in expr and len(expr["anyOf"]) == 11
    tags = []
    for branch in expr["anyOf"]:
        definition = wire["$defs"][branch["$ref"].split("/")[-1]]
        assert "kind" in definition["required"]
        tags.append(definition["properties"]["kind"]["const"])
    assert len(set(tags)) == len(tags)
    assert original == before and schema_for_vllm(wire) == wire
    assert schema_for_vllm(SolverOutput.model_json_schema()) == SolverOutput.model_json_schema()
    with pytest.raises(ValidationError):
        QuestionFrame.model_validate({"expected_type": "number"})
    with pytest.raises(ValidationError):
        QuestionFrame.model_validate({"expected_type": "string", "time": [
            {"span": "test", "expr": {}}]})


@pytest.mark.parametrize("change", ["duplicate", "unknown_union", "bad_discriminator"])
def test_schema_adapter_rejects_unreviewed_unions(change):
    schema = QuestionFrame.model_json_schema()
    if change == "duplicate":
        schema["$defs"]["RollingExpr"]["properties"]["kind"]["const"] = "date"
    elif change == "bad_discriminator":
        schema["$defs"]["TimeRef"]["properties"]["expr"]["discriminator"]["propertyName"] = "x"
    else:
        schema["properties"]["extra"] = {"oneOf": [{"type": "string"}, {"type": "number"}]}
    with pytest.raises(ValueError):
        schema_for_vllm(schema)


def test_schema_preparation_error_is_modelcall_not_exception(http_server):
    result = call(client_for(http_server), json_schema={"oneOf": [{"type": "string"}]})
    assert result.error == codes.E_MODEL_ERROR
    assert result.transport["attempts"] == [] and not http_server["requests"]
    assert result.transport["request_prepared"] is False


def test_schema_adapter_opt_out_and_schema_free_calls(http_server):
    original = QuestionFrame.model_json_schema()
    result = call(client_for(http_server, schema_adapter="none"), json_schema=original)
    assert result.error is None
    sent = http_server["requests"][-1][2]["response_format"]["json_schema"]["schema"]
    assert sent == original and result.transport["schema_adapter"] == "none"
    result = call(client_for(http_server), json_schema=None)
    assert result.error is None and "response_format" not in http_server["requests"][-1][2]


def test_retry_uses_remaining_call_budget(monkeypatch):
    client = HttpModelClient(ModelConfig(base_url="http://127.0.0.1:8000", model_call_timeout_s=1))
    timeouts = []
    def post(data, timeout):
        timeouts.append(timeout)
        if len(timeouts) == 1:
            time.sleep(0.02)
            raise ConnectionResetError("test connection reset")
        return 200, json.dumps(response("ok")).encode()
    monkeypatch.setattr(client, "_post", post)
    result = call(client)
    assert result.error is None and len(timeouts) == 2
    assert 0 < timeouts[1] < timeouts[0] <= 1


def test_transport_retry_once_with_identical_bytes(http_server):
    http_server["actions"] = [{"disconnect": True}, {"payload": response("ok")}]
    result = call(client_for(http_server))
    assert result.error is None and result.content == "ok"
    assert len(http_server["requests"]) == 2
    assert http_server["requests"][0][1] == http_server["requests"][1][1]
    assert result.transport["attempts"][0]["error"] == codes.E_MODEL_TRANSPORT


def test_transport_failure_returns_error_after_two_attempts(http_server):
    http_server["actions"] = [{"disconnect": True}, {"disconnect": True}]
    result = call(client_for(http_server))
    assert result.error == codes.E_MODEL_TRANSPORT and len(http_server["requests"]) == 2


def test_timeout_is_not_retried(http_server):
    http_server["actions"] = [{"sleep": 0.3}]
    result = call(client_for(http_server, model_call_timeout_s=0.05))
    assert result.error == codes.E_MODEL_TIMEOUT
    assert len(http_server["requests"]) == 1 and len(result.transport["attempts"]) == 1


@pytest.mark.parametrize("status", [400, 429, 500, 503])
def test_http_error_is_not_retried_and_body_is_retained(http_server, status):
    raw = b'{"error":{"message":"schema rejected"}}'
    http_server["actions"] = [{"status": status, "raw": raw}]
    result = call(client_for(http_server))
    assert result.error == codes.E_MODEL_ERROR and len(http_server["requests"]) == 1
    assert result.transport["http_status"] == status
    assert result.transport["response_body"] == raw.decode()


def test_redirect_is_not_followed(http_server):
    http_server["actions"] = [{"status": 302, "location": "https://example.com"}]
    result = call(client_for(http_server))
    assert result.error == codes.E_MODEL_ERROR and len(http_server["requests"]) == 1


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": [1]},
    {"choices": [{"message": {"content": None}, "finish_reason": "stop"}]},
    response("text", ["not text"]), response("text", None, None)])
def test_invalid_response_protocol_returns_error(http_server, payload):
    http_server["actions"] = [{"payload": payload}]
    result = call(client_for(http_server))
    assert result.error == codes.E_MODEL_ERROR and len(http_server["requests"]) == 1


def test_malformed_json_response_returns_error(http_server):
    http_server["actions"] = [{"raw": b"not JSON"}]
    result = call(client_for(http_server))
    assert result.error == codes.E_MODEL_ERROR and result.transport["response_body"] == "not JSON"


@pytest.mark.parametrize("content,finish", [("", "stop"), ("not JSON", "stop"),
                                           ('{"sql":"SELEC 1"}', "stop"), ("partial", "length")])
def test_model_text_and_finish_reason_are_not_rewritten(http_server, content, finish):
    http_server["actions"] = [{"payload": response(content, None, finish)}]
    result = call(client_for(http_server))
    assert result.error is None and result.content == content and result.finish_reason == finish
    assert result.reasoning is None


@pytest.mark.parametrize("url", ["https://127.0.0.1:8000", "http://example.com", "http://0.0.0.0:8000",
                                "http://user:password@127.0.0.1", "http://127.0.0.1/v1?x=1"])
def test_config_restricts_http_to_loopback(url):
    with pytest.raises(ValidationError):
        ModelConfig(base_url=url)


def test_http_factory_and_scripted_guard(http_server):
    client = make_client(ModelConfig(base_url=http_server["url"]), dev=False)
    assert isinstance(client, HttpModelClient) and not client.dev_only
    with pytest.raises(ValueError, match="model.base_url is required"):
        make_client(ModelConfig(), dev=False)
    with pytest.raises(ProductionGuardError):
        make_client(ModelConfig(backend="scripted"), dev=False)


def test_shared_client_can_serve_concurrent_callers(http_server):
    http_server["actions"] = [{"echo": True} for _ in range(8)]
    client = client_for(http_server)
    def task(i):
        return call(client, messages=[{"role": "user", "content": str(i)}], call_id=str(i))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(task, range(8)))
    assert [r.content for r in results] == [str(i) for i in range(8)]
    assert all(r.error is None for r in results)


def test_http_pipeline_executes_real_sql_and_logs_reasoning(http_server, split, catalog, cfg):
    text = "Tháng này có bao nhiêu dòng hàng?"
    frame = {"expected_type": "number", "numeric_kind": "count", "time": [
        {"span": "Tháng này", "expr": {"kind": "relative_period", "unit": "month", "offset": 0}}]}
    sql = "SELECT COUNT(*) AS value FROM ban_hang WHERE ngay_dat BETWEEN DATE '2026-03-01' AND DATE '2026-03-04'"
    http_server["actions"] = [{"payload": response(json.dumps(frame), " parser reasoning\n")},
                              {"payload": response(json.dumps({"sql": sql}), None)}]
    http_cfg = RunConfig(work_dir=cfg.work_dir, model=ModelConfig(base_url=http_server["url"]))
    client = make_client(http_cfg.model, dev=False)
    record, log = answer_question(question(text), split, catalog, client, http_cfg)
    assert record.type == "number" and record.answer == 6  # fixture DH009/010/011 have 2 lines each
    assert log.code == sql and log.thinking == [" parser reasoning\n", ""]
    assert all(c.backend == "http" and c.transport["http_status"] == 200 for c in log.calls)
    assert "oneOf" not in http_server["requests"][0][2]["response_format"]["json_schema"]["schema"][
        "$defs"]["TimeRef"]["properties"]["expr"]


def test_http_parser_still_uses_original_pydantic_validation(http_server, split, catalog, cfg):
    http_server["actions"] = [{"payload": response('{"expected_type":"number"}')}]
    frame, result, error = parse_question(question("Bao nhiêu?"), split, catalog,
                                          client_for(http_server), cfg)
    assert result.error is None and frame is None and error == codes.E_PARSE_INVALID


def test_thinking_is_logged_exactly_from_inline_think_blocks_and_null_when_off():
    from datamate.runtime.pipeline import _thinking

    def call(content, reasoning=None):
        return ModelCall(call_id="c", stage="solve", template_id="t", backend="http",
                         request_sha256="0" * 64, params={}, content=content, reasoning=reasoning,
                         finish_reason="stop", latency_ms=1)
    # thinking off: no reasoning anywhere -> null
    assert _thinking([call('{"sql":"SELECT 1"}'), call("{}")]) is None
    # reasoning parser on: reasoning_content wins, kept byte-for-byte, one entry per call
    assert _thinking([call("{}", "  a\n"), call("{}")]) == ["  a\n", ""]
    # no parser: the inline block text is the reasoning; the content is untouched
    inline = call("<think>\nxét bảng ban_hang\n</think>\n\n{}")
    assert _thinking([inline]) == ["\nxét bảng ban_hang\n"]
    assert inline.content.startswith("<think>")


def test_managed_thinking_requires_a_reasoning_parser():
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="reasoning_parser"):
        RunConfig.model_validate({"model": {"path": "/m", "enable_thinking": {"solve": True}},
                                  "serving": {"mode": "managed"}})
    RunConfig.model_validate({"model": {"path": "/m", "enable_thinking": {"solve": True}},
                              "serving": {"mode": "managed", "reasoning_parser": "qwen3"}})
