#!/usr/bin/env bash
# Build the submission image (DG §9, TASKS M4-09). Run on the build host from the repository root.
#   tools/build_image.sh <team_name> <model_dir>
# <model_dir> is a local directory with the selected model (weights, tokenizer, configs); it is
# staged under ./models/<name> and must match model.path in config/run_config.json.
# Prerequisites: requirements.lock (tools/gen_requirements_lock.sh), docker with BuildKit.
set -euo pipefail
TEAM="${1:?usage: tools/build_image.sh <team_name> <model_dir>}"
MODEL_SRC="${2:?usage: tools/build_image.sh <team_name> <model_dir>}"
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

[ -f requirements.lock ] || { echo "error: requirements.lock missing (run tools/gen_requirements_lock.sh)" >&2; exit 2; }
[ -d "$MODEL_SRC" ] || { echo "error: model dir $MODEL_SRC not found" >&2; exit 2; }
NAME="$(basename "$MODEL_SRC")"
CONFIGURED="$(python3 -c 'import json;print(json.load(open("config/run_config.json"))["model"]["path"])')"
[ "$CONFIGURED" = "/code/models/$NAME" ] || {
  echo "error: config/run_config.json model.path is $CONFIGURED but the staged model would be /code/models/$NAME" >&2; exit 2; }

python3 tools/count_params.py "$MODEL_SRC"           # must print OK (<= 15 B) or the build stops
mkdir -p models && rsync -a --delete "$MODEL_SRC"/ "models/$NAME"/
if [ -d train ]; then rsync -a --delete train/ training_code/data/train/; fi
python3 training_code/data_generation/build_manifest.py

docker build --platform linux/amd64 --build-arg GIT_COMMIT="$(git rev-parse HEAD)" \
  -t "zaic2026_datamate_${TEAM}:final" .
docker image inspect -f '{{.Os}}/{{.Architecture}} {{.Size}}' "zaic2026_datamate_${TEAM}:final"
docker run --rm --network none --entrypoint "" "zaic2026_datamate_${TEAM}:final" find /code -maxdepth 2
