#!/usr/bin/env bash
# M4-01: generate requirements.lock by `pip freeze` INSIDE the chosen base image.
#
# Never edit the output by hand and never generate it outside the image: the
# lock must describe the exact vLLM / torch / transformers build the image ships.
#
# Usage (build host with Docker and network access, i.e. NOT the offline test run):
#   tools/gen_requirements_lock.sh [BASE_IMAGE]
# Default BASE_IMAGE: vllm/vllm-openai:v0.10.1.1 (DEC-3 reference image).
# Outputs (repository root):
#   requirements.lock              pip freeze after installing requirements.in
#   requirements.lock.base         pip freeze of the untouched base image
#   requirements.lock.meta.json    image id, repo digest, python/torch/vllm versions
set -euo pipefail
trap 'rm -f "$ROOT/requirements.lock.tmp"' EXIT

BASE_IMAGE="${1:-vllm/vllm-openai:v0.10.1.1}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

command -v docker >/dev/null || { echo "error: docker not found" >&2; exit 2; }
[ -f requirements.in ] || { echo "error: requirements.in missing" >&2; exit 2; }

docker pull "$BASE_IMAGE"
IMAGE_ID="$(docker image inspect -f '{{.Id}}' "$BASE_IMAGE")"
REPO_DIGEST="$(docker image inspect -f '{{index .RepoDigests 0}}' "$BASE_IMAGE" 2>/dev/null || true)"

# 1. Baseline: what the image already contains.
docker run --rm --entrypoint "" "$BASE_IMAGE" python3 -m pip freeze --all \
  | LC_ALL=C sort > requirements.lock.base

# 2. Install project requirements with the base image's pins as constraints,
#    so pip cannot replace torch/vllm/transformers; then freeze.
docker run --rm --entrypoint "" -v "$ROOT/requirements.in:/tmp/requirements.in:ro" \
  -v "$ROOT/requirements.lock.base:/tmp/constraints.txt:ro" "$BASE_IMAGE" bash -c '
    set -euo pipefail
    if ! python3 -m pip install --no-cache-dir -c /tmp/constraints.txt -r /tmp/requirements.in >&2; then
      echo "error: requirements.in conflicts with a package version shipped in the base image" >&2
      echo "       (see the pip resolver message above); widen the range in requirements.in" >&2
      echo "       and pyproject.toml, never re-pin a base-image package" >&2
      exit 3
    fi
    python3 -m pip freeze --all' | LC_ALL=C sort > requirements.lock.tmp
mv requirements.lock.tmp requirements.lock

docker run --rm -i --entrypoint "" "$BASE_IMAGE" python3 - > requirements.lock.meta.json <<PY
import json, platform, sys
import torch, vllm
print(json.dumps({"base_image": "$BASE_IMAGE", "image_id": "$IMAGE_ID",
                  "repo_digest": "$REPO_DIGEST", "python": platform.python_version(),
                  "torch": torch.__version__, "cuda": torch.version.cuda,
                  "vllm": vllm.__version__}, indent=2, sort_keys=True))
PY

echo "wrote requirements.lock ($(wc -l < requirements.lock) pins), requirements.lock.base, requirements.lock.meta.json"
echo "Next: commit all three; run the CPU tests from the lock (see docs/decisions/M4-01-base-image.md)."
