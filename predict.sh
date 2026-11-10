#!/usr/bin/env bash
# DataMate 2026 entry point (DG §5, SPEC §2.1). Run as: bash /code/predict.sh  (no arguments).
# Reads /data (read-only), writes /result/submission.jsonl and /result/logs/.
# Every setting comes from /code/config/run_config.json; this script reads no environment
# variable that changes behavior and passes no development flag.
set -euo pipefail

if [ "$#" -ne 0 ]; then
  echo "predict.sh takes no arguments" >&2
  exit 2
fi

# Fixed environment (SPEC §2.4). Exported again here so a plain `bash predict.sh` is identical
# to the image default.
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTHONHASHSEED=0
export PYTHONUNBUFFERED=1
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NCCL_P2P_DISABLE=1
export VLLM_BATCH_INVARIANT=0
export VLLM_NO_USAGE_STATS=1
export DO_NOT_TRACK=1
export PYTHONPATH=/code/src

mkdir -p /result/logs
cd /code
exec python3 -m datamate.run --config /code/config/run_config.json --data-dir /data --result-dir /result
