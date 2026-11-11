"""vLLM replica manager (SPEC §7.13.1, TASKS M4-03). Owner: M4.

Starts ``serving.replicas`` OpenAI-compatible servers on 127.0.0.1, one per GPU
(``CUDA_VISIBLE_DEVICES``), waits for ``GET /health`` and one deterministic
warm-up request, restarts a dead replica at most ``serving.max_restarts`` times,
captures server output in ``<log_dir>/replica-<i>.log`` and shuts down cleanly
(SIGTERM to the process group, SIGKILL after ``serving.shutdown_timeout_s``).

Only loopback is used. The launch command is configuration
(``serving.vllm_command``) so CPU tests run a fake server with the same flags.
Nothing here decides model quality; it moves processes and timings only.
"""

from __future__ import annotations

import http.client
import os
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from datamate.config import ModelConfig, RunConfig, ServingConfig
from datamate.contracts import ModelCall
from datamate.llm.http import HttpModelClient

HOST = "127.0.0.1"
WARMUP_MESSAGES = [{"role": "user", "content": "Trả lời đúng một từ: xin chào."}]  # fixed, never edited

# Fixed environment of every server process (SPEC §2.4). Applied on top of the
# parent environment; ``serving.env`` may add to it but not reach the network.
SERVER_ENV = {
    "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "VLLM_NO_USAGE_STATS": "1",
    "DO_NOT_TRACK": "1", "PYTHONHASHSEED": "0", "PYTHONUNBUFFERED": "1",
    "TOKENIZERS_PARALLELISM": "false", "NCCL_P2P_DISABLE": "1",
}


class ReplicaError(RuntimeError):
    """A replica could not be started, became unhealthy or could not be restarted."""


def build_command(cfg: RunConfig, index: int) -> list[str]:
    """Server argv for replica ``index`` (SPEC §7.13.1). Pure and deterministic."""
    s, m = cfg.serving, cfg.model
    if not m.path:
        raise ReplicaError("model.path is required to start replicas")
    cmd = [*s.vllm_command, "--model", m.path, "--served-model-name", m.served_model_name,
           "--dtype", s.dtype, "--max-model-len", str(s.max_model_len),
           "--gpu-memory-utilization", f"{s.gpu_memory_utilization:g}",
           "--max-num-seqs", str(s.max_num_seqs), "--seed", str(m.seed),
           "--host", HOST, "--port", str(s.base_port + index),
           # --no-enable-prefix-caching spelling is [VERIFY] against the pinned vLLM (SPEC §7.13.1)
           "--enable-prefix-caching" if s.enable_prefix_caching else "--no-enable-prefix-caching",
           "--generation-config", "vllm"]
    if s.tensor_parallel_size > 1:
        cmd += ["--tensor-parallel-size", str(s.tensor_parallel_size)]
    if s.reasoning_parser:
        cmd += ["--reasoning-parser", s.reasoning_parser]
    if s.quantization:
        cmd += ["--quantization", s.quantization]
    return cmd + list(s.extra_server_args)


def gpu_ids_for(s: ServingConfig, index: int) -> list[int]:
    ids = s.gpu_ids if s.gpu_ids is not None else list(range(s.replicas * s.tensor_parallel_size))
    tp = s.tensor_parallel_size
    return ids[index * tp:(index + 1) * tp]


def build_env(cfg: RunConfig, index: int, base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env.update(SERVER_ENV)
    env.update(cfg.serving.env)
    env["CUDA_VISIBLE_DEVICES"] = ",".join(str(g) for g in gpu_ids_for(cfg.serving, index))
    return env


@dataclass
class Replica:
    index: int
    port: int
    gpus: list[int]
    log_path: Path
    process: subprocess.Popen[Any] | None = None
    restarts: int = 0
    load_ms: int | None = None
    state: str = "new"  # new | starting | ready | dead | stopped
    _log_fh: Any = field(default=None, repr=False)

    @property
    def base_url(self) -> str:
        return f"http://{HOST}:{self.port}/v1"


class ReplicaManager:
    def __init__(self, cfg: RunConfig, log_dir: Path, *,
                 popen: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        if cfg.serving.mode != "managed":
            raise ReplicaError("serving.mode must be 'managed' to use ReplicaManager")
        self.cfg = cfg
        self.log_dir = Path(log_dir)
        self._popen, self._clock, self._sleep = popen, clock, sleep
        self._lock = threading.RLock()
        self.events: list[dict[str, Any]] = []
        self.replicas = [Replica(i, cfg.serving.base_port + i, gpu_ids_for(cfg.serving, i),
                                 self.log_dir / f"replica-{i}.log")
                         for i in range(cfg.serving.replicas)]
        self.active: list[int] = []  # indices of replicas that started; set by start()

    # -- observability ---------------------------------------------------------------------

    def _event(self, kind: str, index: int | None, **detail: Any) -> None:
        with self._lock:
            self.events.append({"t_ms": int(self._clock() * 1000), "event": kind,
                                "replica": index, **detail})

    @property
    def base_urls(self) -> list[str]:
        return [r.base_url for r in self.replicas]

    def client_configs(self) -> list[ModelConfig]:
        """One ModelConfig per active replica with ``base_url`` wired to its server.

        Position ``k`` in this list is the orchestrator's replica ``k``; ``poll`` and ``restart``
        use the same positions (``active[k]`` is the replica index).
        """
        return [self.cfg.model.model_copy(update={"base_url": self.replicas[i].base_url})
                for i in self.active]

    def record(self) -> dict[str, Any]:
        """Replica section of run.json (SPEC §8.5)."""
        return {"replica_load_ms": [r.load_ms for r in self.replicas],
                "restarts": [r.restarts for r in self.replicas],
                "states": [r.state for r in self.replicas],
                "ports": [r.port for r in self.replicas], "gpus": [r.gpus for r in self.replicas],
                "commands": [build_command(self.cfg, r.index) for r in self.replicas],
                "active": list(self.active),
                "events": list(self.events)}

    # -- lifecycle -------------------------------------------------------------------------

    def start(self) -> None:
        """Launch every replica, then wait for each to be healthy and warm.

        A replica that fails to start gets its restart budget (``serving.max_restarts``); one that
        still fails is marked dead and the run continues on the others (``active``). Raises
        ReplicaError only when no replica is ready, after stopping everything.
        """
        self.log_dir.mkdir(parents=True, exist_ok=True)
        launched: dict[int, float] = {}
        errors: dict[int, str] = {}
        try:
            for r in self.replicas:
                try:
                    launched[r.index] = self._launch(r)
                except ReplicaError as exc:
                    errors[r.index] = str(exc)
            for r in self.replicas:  # first pass: every launched replica loads in parallel
                if r.index not in launched:
                    continue
                try:
                    self._wait_ready(r, launched[r.index])
                except ReplicaError as exc:
                    errors[r.index] = str(exc)
            for index in sorted(errors):  # second pass: bounded restarts of the failed ones
                r = self.replicas[index]
                self._terminate(r)
                r.state = "dead"
                self._event("start_failed", index, error=errors[index])
                if self._restart_index(index):
                    del errors[index]
        except BaseException:
            self.stop()
            raise
        self.active = [r.index for r in self.replicas if r.state == "ready"]
        if not self.active:
            self.stop()
            raise ReplicaError("no replica started: " + "; ".join(errors[i] for i in sorted(errors)))

    def _port_free(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # as uvicorn does
            try:
                sock.bind((HOST, port))
            except OSError:
                return False
        return True

    def _launch(self, r: Replica) -> float:
        if not self._port_free(r.port):
            raise ReplicaError(f"replica {r.index}: port {r.port} on {HOST} is already in use")
        r.log_path.parent.mkdir(parents=True, exist_ok=True)
        r._log_fh = open(r.log_path, "ab")  # noqa: SIM115 - closed in _reap
        cmd, env = build_command(self.cfg, r.index), build_env(self.cfg, r.index)
        started = self._clock()
        try:
            r.process = self._popen(cmd, stdout=r._log_fh, stderr=subprocess.STDOUT, env=env,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            r.state = "dead"
            raise ReplicaError(f"replica {r.index}: cannot execute {cmd[0]!r}: {exc}") from exc
        r.state = "starting"
        self._event("launch", r.index, pid=r.process.pid, port=r.port, gpus=r.gpus)
        return started

    def _health(self, r: Replica) -> bool:
        try:
            conn = http.client.HTTPConnection(HOST, r.port, timeout=2.0)
            try:
                conn.request("GET", "/health")
                return conn.getresponse().status == 200
            finally:
                conn.close()
        except (OSError, http.client.HTTPException):
            return False

    def _warm_up(self, r: Replica) -> ModelCall:
        cfg = self.cfg.model.model_copy(update={"base_url": r.base_url})
        client = HttpModelClient(cfg)
        return client.complete(stage="parse", template_id="warmup.v1", messages=WARMUP_MESSAGES,
                               json_schema=None, max_tokens=self.cfg.serving.warmup_max_tokens,
                               call_id=f"warmup:{r.index}")

    def _wait_ready(self, r: Replica, launched_at: float) -> None:
        s = self.cfg.serving
        while True:
            assert r.process is not None
            code = r.process.poll()
            if code is not None:
                r.state = "dead"
                raise ReplicaError(f"replica {r.index} exited with code {code} during startup; "
                                   f"see {r.log_path}")
            if self._health(r):
                break
            if self._clock() - launched_at > s.startup_timeout_s:
                r.state = "dead"
                raise ReplicaError(f"replica {r.index} not healthy after {s.startup_timeout_s:g} s; "
                                   f"see {r.log_path}")
            self._sleep(s.health_poll_interval_s)
        call = self._warm_up(r)
        r.load_ms = int((self._clock() - launched_at) * 1000)
        if call.error:
            r.state = "dead"
            raise ReplicaError(f"replica {r.index} warm-up failed: {call.error}")
        r.state = "ready"
        self._event("ready", r.index, load_ms=r.load_ms, warmup_latency_ms=call.latency_ms,
                    warmup_request_sha256=call.request_sha256)

    def poll(self) -> list[int]:
        """Positions (in ``active``) of replicas whose process has exited since they were ready."""
        dead = []
        with self._lock:
            for pos, i in enumerate(self.active):
                r = self.replicas[i]
                if r.state == "ready" and r.process is not None and r.process.poll() is not None:
                    r.state = "dead"
                    self._event("died", r.index, returncode=r.process.returncode)
                if r.state == "dead":
                    dead.append(pos)
        return dead

    def restart(self, position: int) -> bool:
        """Restart the active replica at ``position`` (see ``poll``)."""
        return self._restart_index(self.active[position])

    def _restart_index(self, index: int) -> bool:
        """One bounded restart attempt (SPEC §7.12-10). False when the budget is spent or it fails."""
        with self._lock:
            r = self.replicas[index]
            if r.restarts >= self.cfg.serving.max_restarts:
                self._event("restart_refused", index, restarts=r.restarts)
                return False
            r.restarts += 1
            self._terminate(r)
            self._event("restart", index, attempt=r.restarts)
            try:
                self._wait_ready(r, self._launch(r))
            except ReplicaError as exc:
                self._terminate(r)
                r.state = "dead"
                self._event("restart_failed", index, error=str(exc))
                return False
            return True

    def _terminate(self, r: Replica) -> None:
        proc = r.process
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
            try:
                proc.wait(timeout=self.cfg.serving.shutdown_timeout_s)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
                proc.wait()
                self._event("killed", r.index)
        if r._log_fh is not None:
            r._log_fh.close()
            r._log_fh = None

    def stop(self) -> None:
        with self._lock:
            for r in self.replicas:
                self._terminate(r)
                if r.state != "new":
                    r.state = "stopped"
            self._event("stopped", None)

    def __enter__(self) -> ReplicaManager:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
