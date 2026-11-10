"""M4 launch-argument adapter for the same limits consumed by M3 prompt budgeting."""

from __future__ import annotations

from urllib.parse import urlsplit

from datamate.config import RunConfig


def server_arguments(cfg: RunConfig, *, total_vram_mib: float | None = None) -> list[str]:
    """Return arguments only. No server launch or claim about GPU compatibility."""
    if not cfg.model.path or not cfg.model.base_url:
        raise ValueError("set model.path and model.base_url before creating server arguments")
    url = urlsplit(cfg.model.base_url)
    utilization = cfg.serving.gpu_memory_utilization
    if total_vram_mib is not None:
        if total_vram_mib <= 0:
            raise ValueError("total_vram_mib must be positive")
        utilization = min(utilization, cfg.serving.target_executor_gib * 1024 / total_vram_mib)
    args = ["--model", cfg.model.path, "--tokenizer", cfg.model.path,
            "--served-model-name", cfg.model.served_model_name,
            "--host", "127.0.0.1" if url.hostname == "localhost" else str(url.hostname),
            "--port", str(url.port or 80), "--dtype", cfg.serving.dtype,
            "--max-model-len", str(cfg.serving.max_model_len),
            "--max-num-seqs", str(cfg.serving.max_num_seqs),
            "--max-num-batched-tokens", str(cfg.serving.max_num_batched_tokens),
            "--gpu-memory-utilization", str(utilization), "--tensor-parallel-size", "1",
            "--seed", str(cfg.model.seed), "--generation-config", "vllm", "--cpu-offload-gb", "0",
            "--enable-prefix-caching" if cfg.serving.prefix_caching else "--no-enable-prefix-caching",
            "--enable-chunked-prefill" if cfg.serving.chunked_prefill else "--no-enable-chunked-prefill"]
    if cfg.serving.reasoning_parser:
        args += ["--reasoning-parser", cfg.serving.reasoning_parser]
    return args
