"""M4-03 acceptance: ReplicaManager against a fake vLLM server process (CPU, loopback only)."""

from __future__ import annotations

import os
import signal
import socket
import sys
from pathlib import Path

import pytest

from datamate.config import RunConfig
from datamate.llm import HttpModelClient
from datamate.llm.replicas import ReplicaError, ReplicaManager, build_command, build_env

FAKE = str(Path(__file__).parent.parent / "fixtures" / "fake_vllm_server.py")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_cfg(tmp_path, **serving) -> RunConfig:
    base = {"mode": "managed", "replicas": 2, "base_port": free_port(),
            "vllm_command": [sys.executable, FAKE], "startup_timeout_s": 20,
            "health_poll_interval_s": 0.05, "shutdown_timeout_s": 5}
    base.update(serving)
    return RunConfig.model_validate({"model": {"path": str(tmp_path), "served_model_name": "dm"},
                                     "serving": base})


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:  # a zombie still answers signal 0
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


def test_build_command_matches_spec_7_13_1():
    cfg = RunConfig.model_validate({
        "model": {"path": "/code/models/m", "served_model_name": "datamate", "seed": 7},
        "serving": {"mode": "managed", "replicas": 2, "base_port": 8100, "dtype": "bfloat16",
                    "max_model_len": 4096, "gpu_memory_utilization": 0.9, "max_num_seqs": 32,
                    "reasoning_parser": "qwen3", "quantization": "fp8",
                    "extra_server_args": ["--max-num-batched-tokens", "8192"]}})
    assert build_command(cfg, 1) == [
        "python3", "-m", "vllm.entrypoints.openai.api_server",
        "--model", "/code/models/m", "--served-model-name", "datamate", "--dtype", "bfloat16",
        "--max-model-len", "4096", "--gpu-memory-utilization", "0.9", "--max-num-seqs", "32",
        "--seed", "7", "--host", "127.0.0.1", "--port", "8101", "--enable-prefix-caching",
        "--generation-config", "vllm", "--reasoning-parser", "qwen3", "--quantization", "fp8",
        "--max-num-batched-tokens", "8192"]


def test_prefix_caching_off_and_tensor_parallel_flags():
    cfg = RunConfig.model_validate({
        "model": {"path": "/m"},
        "serving": {"mode": "managed", "replicas": 1, "tensor_parallel_size": 2,
                    "enable_prefix_caching": False}})
    cmd = build_command(cfg, 0)
    assert "--no-enable-prefix-caching" in cmd and "--enable-prefix-caching" not in cmd
    assert cmd[cmd.index("--tensor-parallel-size") + 1] == "2"
    assert build_env(cfg, 0, {})["CUDA_VISIBLE_DEVICES"] == "0,1"


def test_environment_is_fixed_and_one_gpu_per_replica():
    cfg = RunConfig.model_validate({"model": {"path": "/m"},
                                    "serving": {"mode": "managed", "replicas": 2}})
    e0, e1 = build_env(cfg, 0, {"HF_HUB_OFFLINE": "0"}), build_env(cfg, 1, {})
    assert (e0["CUDA_VISIBLE_DEVICES"], e1["CUDA_VISIBLE_DEVICES"]) == ("0", "1")
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "VLLM_NO_USAGE_STATS", "DO_NOT_TRACK"):
        assert e0[key] == "1"
    assert e0["NCCL_P2P_DISABLE"] == "1"


def test_gpu_ids_validation():
    with pytest.raises(ValueError, match="gpu_ids"):
        RunConfig.model_validate({"serving": {"replicas": 2, "gpu_ids": [0]}})
    cfg = RunConfig.model_validate({"model": {"path": "/m"},
                                    "serving": {"mode": "managed", "replicas": 2, "gpu_ids": [3, 5]}})
    assert build_env(cfg, 1, {})["CUDA_VISIBLE_DEVICES"] == "5"


def test_managed_requires_model_path():
    cfg = RunConfig.model_validate({"serving": {"mode": "managed"}})
    with pytest.raises(ReplicaError, match="model.path"):
        build_command(cfg, 0)


def test_start_two_replicas_log_capture_and_clean_shutdown(tmp_path):
    cfg = make_cfg(tmp_path)
    mgr = ReplicaManager(cfg, tmp_path / "logs")
    mgr.start()
    pids = [r.process.pid for r in mgr.replicas]
    try:
        assert [r.state for r in mgr.replicas] == ["ready", "ready"]
        assert mgr.base_urls == [f"http://127.0.0.1:{cfg.serving.base_port + i}/v1" for i in (0, 1)]
        assert all(isinstance(r.load_ms, int) and r.load_ms >= 0 for r in mgr.replicas)
        for i in (0, 1):
            log = (tmp_path / "logs" / f"replica-{i}.log").read_text()
            assert f"CUDA_VISIBLE_DEVICES={i}" in log and '"--port"' in log
        # configs wired per replica; the same client class talks to each
        call = HttpModelClient(mgr.client_configs()[1]).complete(
            stage="parse", template_id="t", messages=[{"role": "user", "content": "x"}],
            json_schema=None, max_tokens=5, call_id="c")
        assert call.error is None and call.content == "pong:5"
        warm = [e for e in mgr.events if e["event"] == "ready"]
        assert len(warm) == 2 and warm[0]["warmup_request_sha256"] == warm[1]["warmup_request_sha256"]
        assert mgr.record()["replica_load_ms"] == [r.load_ms for r in mgr.replicas]
    finally:
        mgr.stop()
    assert not any(alive(p) for p in pids)
    assert "clean shutdown" in (tmp_path / "logs" / "replica-0.log").read_text()
    assert [r.state for r in mgr.replicas] == ["stopped", "stopped"]
    with socket.socket() as s:  # ports released (SO_REUSEADDR: TIME_WAIT is not a leak)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", cfg.serving.base_port))


def test_failed_launch_raises_and_leaves_no_process(tmp_path):
    cfg = make_cfg(tmp_path, replicas=2, env={"FAKE_VLLM_EXIT_CODE": "7"})
    mgr = ReplicaManager(cfg, tmp_path / "logs")
    with pytest.raises(ReplicaError, match="exited with code 7"):
        mgr.start()
    assert not any(r.process and alive(r.process.pid) for r in mgr.replicas)
    assert "simulated launch failure" in (tmp_path / "logs" / "replica-0.log").read_text()


def test_startup_timeout_terminates_the_process(tmp_path):
    cfg = make_cfg(tmp_path, replicas=1, startup_timeout_s=0.5, env={"FAKE_VLLM_STARTUP_S": "30"})
    mgr = ReplicaManager(cfg, tmp_path / "logs")
    with pytest.raises(ReplicaError, match="not healthy"):
        mgr.start()
    assert not alive(mgr.replicas[0].process.pid)


def test_missing_executable_and_busy_port(tmp_path):
    cfg = make_cfg(tmp_path, replicas=1, vllm_command=["/nonexistent/vllm"])
    with pytest.raises(ReplicaError, match="cannot execute"):
        ReplicaManager(cfg, tmp_path / "l1").start()
    cfg = make_cfg(tmp_path, replicas=1)
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", cfg.serving.base_port))
        with pytest.raises(ReplicaError, match="already in use"):
            ReplicaManager(cfg, tmp_path / "l2").start()


def test_dead_replica_is_detected_restarted_once_then_refused(tmp_path):
    cfg = make_cfg(tmp_path, replicas=2, max_restarts=1)
    with ReplicaManager(cfg, tmp_path / "logs") as mgr:
        assert mgr.poll() == []
        old_pid = mgr.replicas[0].process.pid
        os.killpg(old_pid, signal.SIGKILL)
        mgr.replicas[0].process.wait()
        assert mgr.poll() == [0]
        assert mgr.restart(0) is True
        assert mgr.replicas[0].state == "ready" and mgr.replicas[0].process.pid != old_pid
        assert mgr.replicas[0].restarts == 1 and mgr.poll() == []
        os.killpg(mgr.replicas[0].process.pid, signal.SIGKILL)
        mgr.replicas[0].process.wait()
        assert mgr.poll() == [0]
        assert mgr.restart(0) is False  # budget spent
        kinds = [e["event"] for e in mgr.events if e["replica"] == 0]
        assert kinds.count("died") == 2 and "restart_refused" in kinds
        assert mgr.replicas[1].state == "ready"  # the other replica is untouched


def test_restart_that_fails_reports_false(tmp_path):
    cfg = make_cfg(tmp_path, replicas=1, max_restarts=1,
                   env={"FAKE_VLLM_EXIT_CODE": "9", "FAKE_VLLM_MARKER": str(tmp_path / "other")})
    # first launch succeeds only if the marker exists, which models "fails once, then works"
    (tmp_path / "other").touch()
    with ReplicaManager(cfg, tmp_path / "logs") as mgr:
        os.killpg(mgr.replicas[0].process.pid, signal.SIGKILL)
        mgr.replicas[0].process.wait()
        (tmp_path / "other").unlink()  # the restart now fails (exit 9), and creates the marker
        assert mgr.restart(0) is False
        assert mgr.replicas[0].state == "dead"
        assert any(e["event"] == "restart_failed" for e in mgr.events)


def test_one_broken_gpu_keeps_the_healthy_replica(tmp_path):
    # GPU 1 always fails: it gets its restart, then the run continues on replica 0 alone.
    cfg = make_cfg(tmp_path, replicas=2, max_restarts=1, env={"FAKE_VLLM_FAIL_GPUS": "1"})
    with ReplicaManager(cfg, tmp_path / "logs") as mgr:
        assert mgr.active == [0]
        assert [r.state for r in mgr.replicas] == ["ready", "dead"]
        assert mgr.replicas[1].restarts == 1
        assert [c.base_url for c in mgr.client_configs()] == [mgr.replicas[0].base_url]
        assert mgr.poll() == []  # a replica that never started is not reported as died
        kinds = [e["event"] for e in mgr.events if e["replica"] == 1]
        assert kinds[:1] == ["launch"] and "start_failed" in kinds and "restart_failed" in kinds
        assert mgr.record()["active"] == [0]
    assert "simulated broken GPU" in (tmp_path / "logs" / "replica-1.log").read_text()


def test_replica_that_fails_once_at_startup_is_restarted(tmp_path):
    cfg = make_cfg(tmp_path, replicas=1, max_restarts=1,
                   env={"FAKE_VLLM_EXIT_CODE": "5", "FAKE_VLLM_MARKER": str(tmp_path / "m")})
    with ReplicaManager(cfg, tmp_path / "logs") as mgr:
        assert mgr.active == [0] and mgr.replicas[0].state == "ready"
        assert mgr.replicas[0].restarts == 1


def test_startup_budget_must_fit_the_global_stop():
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="leaves no time"):
        RunConfig.model_validate({"model": {"path": "/m"},
                                  "serving": {"mode": "managed", "startup_timeout_s": 900,
                                              "max_restarts": 1},
                                  "deadlines": {"global_hard_stop_s": 1800}})
