#!/usr/bin/env bash
# Set up the GPU environment (vast.ai, GCP...) as used on GCP on 2026-11-07:
# Python 3.12 + vLLM 0.33.0 + torch 2.14 cu130 (needs NVIDIA driver >= 580), Gemma 4 12B.
# Usage: bash setup_gpu.sh (log in to HF first with `hf auth login`, or set HF_TOKEN)
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
[ -d .venv ] || uv venv -p 3.12 .venv
. .venv/bin/activate
DRV=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 | cut -d. -f1)
if [ "$DRV" -ge 580 ]; then
  uv pip install -r env/requirements-gpu.lock
  # nccl-cu12 and nccl-cu13 both write nvidia/nccl/lib/libnccl.so.2; torch cu130 needs the cu13 one, so install it last
  uv pip install --reinstall --no-deps nvidia-nccl-cu13==2.30.7
else  # driver 570 (CUDA 12.8), same as the organizer's grading machine
  # shortcut: versions not pinned for the cu128 branch; once it works, run `uv pip freeze > env/requirements-gpu-cu128.lock`
  uv pip install vllm==0.33.0 pandas openpyxl huggingface_hub --torch-backend=cu128
fi
python -c "import torch; assert torch.cuda.is_available(), 'no GPU found'; print('torch', torch.__version__, '|', torch.cuda.device_count(), 'x', torch.cuda.get_device_name(0))"
if [ ! -f models/gemma-4-12B-it/config.json ]; then
  if [ -z "${HF_TOKEN:-}" ] && [ ! -f ~/.cache/huggingface/token ]; then
    echo "Environment ready. Not logged in to HF: run '$PWD/.venv/bin/hf auth login', then run this script again."; exit 0
  fi
  hf download google/gemma-4-12B-it --revision 43c9d014b231474fa7212dbb48a762566c2b255d --local-dir models/gemma-4-12B-it
fi
echo "Done. Run: bash run_public.sh"
