"""Synchronous loopback-only vLLM client (M3-02). No third-party HTTP dependency.

One identical retry on transport errors; timeouts and HTTP/protocol failures
are not retried. Every call returns ModelCall. Connections are per attempt,
so concurrent callers do not share mutable sessions. No proxies or redirects.
"""

from __future__ import annotations

import copy
import hashlib
import http.client
import json
import time
from typing import Any
from urllib.parse import urlsplit

from datamate.config import ModelConfig
from datamate.contracts import ModelCall, Stage, codes
from datamate.llm.schema import SCHEMA_ADAPTER_VERSION, schema_for_vllm


def _body_bytes(body: Any) -> bytes:
    return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def http_request_sha256(body: dict[str, Any]) -> str:
    """Hash the actual canonical HTTP body; the scripted hash convention is unchanged."""
    return hashlib.sha256(_body_bytes(body)).hexdigest()


class HttpModelClient:
    backend = "http"
    dev_only = False

    def __init__(self, cfg: ModelConfig):
        if not cfg.base_url:
            raise ValueError("model.base_url is required for HTTP backend (M3-02)")
        self.cfg = cfg
        self._url = urlsplit(cfg.base_url)

    def build_request(self, *, stage: Stage, template_id: str, messages: list[dict[str, str]],
                      json_schema: dict[str, Any] | None, max_tokens: int) -> dict[str, Any]:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        body: dict[str, Any] = {
            "model": self.cfg.served_model_name, "messages": copy.deepcopy(messages),
            "temperature": self.cfg.temperature, "top_p": self.cfg.top_p,
            "top_k": self.cfg.top_k, "min_p": self.cfg.min_p,
            "presence_penalty": self.cfg.presence_penalty,
            "frequency_penalty": self.cfg.frequency_penalty,
            "repetition_penalty": self.cfg.repetition_penalty,
            "max_tokens": max_tokens, "seed": self.cfg.seed, "n": 1, "stream": False,
            "chat_template_kwargs": {"enable_thinking": self.cfg.enable_thinking.get(stage, False)},
        }
        if json_schema is not None:
            schema = (schema_for_vllm(json_schema) if self.cfg.schema_adapter == "timeref.v1"
                      else copy.deepcopy(json_schema))
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": template_id.replace(".", "_"), "schema": schema, "strict": True}}
        return body

    def _post(self, data: bytes, timeout: float) -> tuple[int, bytes]:
        # Direct HTTPConnection ignores proxy environment variables and never follows redirects.
        host = "127.0.0.1" if self._url.hostname == "localhost" else self._url.hostname
        connection = http.client.HTTPConnection(host, self._url.port or 80, timeout=timeout)
        deadline = time.monotonic() + timeout
        try:
            path = self._url.path.rstrip("/")
            path = (path or "/v1") + "/chat/completions"
            connection.request("POST", path, body=data, headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            chunks: list[bytes] = []
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("model call deadline expired")
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            return response.status, b"".join(chunks)
        finally:
            connection.close()

    def complete(self, *, stage: Stage, template_id: str, messages: list[dict[str, str]],
                 json_schema: dict[str, Any] | None, max_tokens: int,
                 call_id: str) -> ModelCall:
        started = time.monotonic()
        body: dict[str, Any] = {}
        data = b"{}"  # no request body exists yet if request construction fails
        content, reasoning, finish = "", None, "error"
        error = None
        evidence: dict[str, Any] = {"attempts": [], "request_prepared": False, "schema_adapter": (
            SCHEMA_ADAPTER_VERSION if self.cfg.schema_adapter == "timeref.v1" else "none")}
        try:
            body = self.build_request(stage=stage, template_id=template_id, messages=messages,
                                      json_schema=json_schema, max_tokens=max_tokens)
            data = _body_bytes(body)
            evidence["request_prepared"] = True
            evidence["request_body"] = body
            evidence["original_schema_sha256"] = (
                hashlib.sha256(_body_bytes(json_schema)).hexdigest() if json_schema is not None else None)
            for attempt in range(1, 3):
                remaining = self.cfg.model_call_timeout_s - (time.monotonic() - started)
                if remaining <= 0:
                    raise TimeoutError("model call deadline expired")
                try:
                    status, raw = self._post(data, remaining)
                except TimeoutError:
                    evidence["attempts"].append({"attempt": attempt, "error": codes.E_MODEL_TIMEOUT})
                    raise
                except (OSError, http.client.HTTPException) as exc:
                    evidence["attempts"].append({"attempt": attempt,
                        "error": codes.E_MODEL_TRANSPORT, "detail": str(exc)})
                    if attempt == 2:
                        error = codes.E_MODEL_TRANSPORT
                        evidence["error_detail"] = str(exc)
                    continue
                evidence["attempts"].append({"attempt": attempt, "http_status": status})
                evidence["http_status"] = status
                evidence["response_body"] = raw.decode("utf-8", errors="replace")
                if status != 200:
                    error = codes.E_MODEL_ERROR
                    evidence["error_detail"] = f"HTTP {status}"
                    break
                payload = json.loads(raw.decode("utf-8"))
                choices = payload["choices"]
                if not isinstance(choices, list) or len(choices) != 1:
                    raise ValueError("expected exactly one response choice")
                choice = choices[0]
                message = choice["message"]
                # Never strip, normalize, repair or summarize generated text.
                content = message["content"]
                reasoning = message.get("reasoning_content", message.get("reasoning"))
                finish = choice["finish_reason"]
                if not isinstance(content, str) or not isinstance(finish, str):
                    raise ValueError("content and finish_reason must be strings")
                if reasoning is not None and not isinstance(reasoning, str):
                    raise ValueError("reasoning must be text or null")
                break
        except TimeoutError as exc:
            error = codes.E_MODEL_TIMEOUT
            evidence["error_detail"] = str(exc)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            error = codes.E_MODEL_ERROR
            evidence["error_detail"] = f"{type(exc).__name__}: {exc}"
        # Invalid protocol field types cannot be put into the frozen ModelCall contract.
        content = content if isinstance(content, str) else ""
        reasoning = reasoning if isinstance(reasoning, str) else None
        finish = finish if isinstance(finish, str) else "error"
        params = {k: v for k, v in body.items() if k not in {"messages", "response_format"}}
        return ModelCall(call_id=call_id, stage=stage, template_id=template_id, backend=self.backend,
            request_sha256=hashlib.sha256(data).hexdigest(), params=params, content=content,
            reasoning=reasoning, finish_reason=finish,
            latency_ms=int((time.monotonic() - started) * 1000), error=error, transport=evidence)
