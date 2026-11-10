# Runbook — model bake-off (M3-01, M3-08)

Only the GPU part runs on Colab. The analysis runs on your own computer.

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
