#!/usr/bin/env bash
# Organizer entry point: /data (read-only) → /result/submission.jsonl + /result/logs/log.jsonl. No network needed.
set -euo pipefail
mkdir -p /result/logs
cd /code
export DATAMATE_CACHE=/tmp/datamate_cache PYTHONUNBUFFERED=1 PYTHONHASHSEED=0
exec python run.py --data /data --out /result/submission.jsonl --logs /result/logs --llm /code/models/gemma-4-12B-it --tp "${TP:-2}"
