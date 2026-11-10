#!/usr/bin/env bash
# DG §10 pre-submission checklist (TASKS M4-14). Examples:
#   tools/precheck.sh --data-dir /path/to/public_test --result-dir /path/to/output
#   tools/precheck.sh --data-dir D --result-dir out1 --compare out2 --answers train/answers.jsonl
#   tools/precheck.sh --image zaic2026_datamate_<team>:final [--measure-tar]
# Exit 0 = all checks passed. Set PYTHON=/path/to/python if python3 lacks the datamate dependencies.
# Details: tools/precheck.py --help
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${PYTHONPATH:-$HERE/../src}"
exec "${PYTHON:-python3}" "$HERE/precheck.py" "$@"
