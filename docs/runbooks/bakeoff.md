# Runbook — model bake-off (M3-01, M3-08)

Only the GPU part runs on Colab. The analysis runs on your own computer.

## Candidates (2026-11-11, evidence level stated per cell)

All three must be confirmed by `tools/bakeoff_report.py --verify` (Hugging Face API: licence, first commit date, revision) and by `tools/count_params.py` on the downloaded weights; the GPU check notebook saves that count.

| Candidate | Licence | Public release | Total parameters | Fits one 32 GB GPU | vLLM 0.10.1.1 |
|---|---|---|---|---|---|
| `Qwen/Qwen3-8B` | Apache-2.0 (aggregator listing of the official repo; LICENSE file in the repo) | 2025-04 (aggregator listing; confirm first commit date) | about 8.2 B (aggregator; count from safetensors) | bf16 weights about 16 GB, leaves KV cache room | Qwen3 needs vLLM >= 0.8.5 (official card): yes |
| `Qwen/Qwen3-14B-FP8` | Apache-2.0 (aggregator listings) | 2025-04/05 (confirm) | about 14.8 B (aggregator): at the 15 B limit, no room for any other model | FP8 weights about 15 GB | FP8 on sm_120: listed in vLLM 0.10.1 release notes (block FP8); not observed by us |
| `Qwen/Qwen3-14B` (bf16) | Apache-2.0 | 2025-04 | about 14.8 B | **No**: about 30 GB of weights | — |

Sources: [Qwen3-8B listing](https://featherless.ai/models/Qwen/Qwen3-8B/readme), [Qwen3-8B repo](https://huggingface.co/Qwen/Qwen3-8B/tree/main), [Qwen3-14B-FP8 card](https://huggingface.co/Qwen/Qwen3-14B-FP8), [Qwen3-14B listing](https://featherless.ai/models/Qwen/Qwen3-14B/readme), [vLLM 0.10.1 notes](https://newreleases.io/project/pypi/vllm/release/0.10.1). Both weight releases are well before the 2026-10-26 cutoff, but that is unconfirmed until `--verify` reads the first commit date.

## 1. On Colab (GPU)
1. Put `train.zip` into `MyDrive/DataMate/` on Google Drive.
2. Open `notebooks/BAKEOFF_G4.ipynb`, edit `CANDIDATES` in the first cell (Hugging Face repo ids; the defaults are examples), then **Run all**.
3. It saves everything to `MyDrive/DataMate/bakeoff/<date>/`: for each candidate two identical runs on held-out businesses, plus the determinism experiments (batch size, prefix cache, `VLLM_BATCH_INVARIANT`, structured outputs) on a small subset.

## 2. On your computer (no GPU)
Download that folder from Drive, then:
```bash
python tools/bakeoff_report.py --runs <folder> --verify --models-dir <folder with the model directories, optional>
```
It prints PA, determinism and speed per candidate and the experiment table; `--verify` adds licence, release date and parameter count (UNVERIFIED if it cannot check; confirm on the model card). It writes `report.json`. Nothing here chooses a model: the team lead decides (DEC-3).

## How to read it
- *identical output rate*: how often the same request gave the same raw text in the two runs; 1.0 and "same submission True" means deterministic on that subset.
- A setting that raises the rate without lowering PA is a candidate for `config/run_config.json`; changing it is the lead's call and needs a full-split run.
- Results on a GPU that is not Blackwell (compute capability 12.0) are only indicative.
