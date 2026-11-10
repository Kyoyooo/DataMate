# training_code — DataMate 2026 verification package (DG §8)

**Status of this package (2026-11-11): no model was trained, fine-tuned or distilled.** The submitted solution uses a publicly released LLM as is (see `/code/README.md` for name, revision, release date, license and parameter count). Nothing in this directory is a model checkpoint.

What is here and why:

| Path | Content |
|---|---|
| `data/train/` | A copy of the organizer-provided **training split** (questions, reference answers, rulebook, calendar, business files), staged by `tools/build_image.sh` at build time. Used only for development evaluation and for the few-shot example bank (TASKS M3-10, **not yet built**). Public and private test data are never included or used. |
| `data_generation/build_manifest.py` | Writes `data_manifest.json` (path, SHA-256, size, source, split, record count of every packaged data file). |
| `data_manifest.json` | The manifest. `omitted_base_checkpoints` is empty: all inference weights are inside the image. |
| `configs/`, `logs/` | Run configurations and logs of preparation steps. Currently empty: no training or generation was run. |
| `requirements.txt` | Pinned dependencies of the scripts above (standard library only, so none). |

Exact commands:

```bash
python training_code/data_generation/build_manifest.py
```

Hardware/runtime: not applicable (no training). Nondeterministic steps: none.

If a few-shot bank or other derived artifact is added (M3-10), its builder script, configuration, seed and log are added here in the same change and listed in `data_manifest.json`.
