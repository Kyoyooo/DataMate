#!/usr/bin/env bash
# Re-run the experiment on the public set (on a GPU machine that has run setup_gpu.sh).
# A100 40GB: ~17 minutes per 1,000 questions. 2 GPUs: TP=2.
set -euo pipefail
cd "$(dirname "$0")"
. ${VENV:-.venv}/bin/activate
export DATAMATE_GPU_UTIL=${DATAMATE_GPU_UTIL:-0.92} DATAMATE_MAXLEN=${DATAMATE_MAXLEN:-16384} PYTHONHASHSEED=0 DATAMATE_CACHE=/tmp/dm_cache_exp1
python run.py --data ${DATA:-../../data/public_test} --out ${OUT:-result/submission.jsonl} --llm ${MODEL:-models/gemma-4-12B-it} --tp ${TP:-1}
