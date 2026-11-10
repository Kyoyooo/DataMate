# Experiment 1: Gemma 12B picks a tool, code computes the answer

This is the first experiment for DataMate: use an LLM to answer every question.

## Question this experiment tries to answer
Can an LLM with ≤ 15B parameters understand everyday Vietnamese questions (abbreviations, missing accents, typos, regional dialect) well enough?

- **The LLM does one thing only:** choose the computation and fill in its parameters.
- **Python functions written from the rulebook:** compute the answer.

## Method
Every question goes through the same pipeline:

```
question + shop data
  │
1. Load the shop (datamate/load.py): README + CSV/Excel/SQLite → canonical tables
  │   (orders, order lines, customers, stock, lots, receivables…); normalize money, dates, units
  │
2. Gemma 4 12B, thinking mode (datamate/llm.py) → ONE JSON tool call
  │   e.g. {"tool": "top_products", "period": {"type": "last_week"}, "k": 1, "by": "qty"}
  │
3. Execute (datamate/tools.py → rules.py / industry.py): convert the period per the rulebook,
  │   match product / customer / mechanic names, compute a typed answer
  │
4. Unanswerable check (datamate/checks.py): keep it only for subjective / out-of-data questions,
  │   or when the shop really does not record that information; otherwise abstain
  │
5. Write submission.jsonl + log (including the model's thinking) after each batch of 256 questions
```

| File | Role |
|---|---|
| `datamate/load.py`, `readme.py`, `synonyms.py`, `parse.py` | Read raw files, map columns using the README descriptions, normalize values |
| `datamate/llm.py` | Prompt, vLLM calls, parsing the tool call from the model output |
| `datamate/tools.py` | 89 tools: name, description, parameters, and executor function |
| `datamate/rules.py`, `industry.py`, `period.py`, `entity.py` | Rulebook computations, periods, product name matching |
| `datamate/fewshot.py` | 55 example question → tool call pairs |
| `datamate/checks.py` | Final check for unanswerable answers |
| `run.py` | Main loop: load shops, run the LLM in batches, write results and logs |

The **prompt** (kept in Vietnamese, as the model sees it) contains:
- period conventions ("tuần rồi" = last week, "cùng kỳ năm ngoái" = same period last year, "T3/2026", "5/25"…) and commonly confused words ("đh" = order, "ca th8" = all of August, "bán thiếu" = sold on credit, subjective questions…);
- **89 tools:** general computations, plus industry-specific groups for motorbike repair (`sx_*`), phone shops (`dt_*`), mother & baby (`mb_*`), and building materials (deliveries, credit sales);
- **55 examples:** 46 questions taken from train, 9 hand-written for period notations that were often misread;
- **shop information:** data date range, available tables, industry, product groups, up to 300 product names.

**Model settings:** temperature 0, seed 0, up to 6,144 thinking tokens. A question whose thinking runs out before a tool call is written becomes abstain.

**Model:** Gemma 4 12B instruct (`google/gemma-4-12B-it`, revision `43c9d014b231474fa7212dbb48a762566c2b255d`), bf16, 12B parameters. No other model is used.

## Re-running
Needs one GPU with ≥ 40GB (run on 1× A100 40GB, driver 580).

The competition data is **not included**. Place it as in the original repo: the public set at `../../data/public_test` (or pass `DATA=…`) and the train set at `../../train` (for scoring and the calendar). The Gemma weights and the Python environment are created by `setup_gpu.sh`.
```bash
bash setup_gpu.sh     # install vLLM 0.33 (cu130) from env/requirements-gpu.lock, download Gemma into models/ (needs HF login)
bash run_public.sh    # → result/submission.jsonl + result/logs/log.jsonl
```
Environment variables:
- `TP=2`: run on 2 GPUs;
- `DATA=…`: use another dataset;
- `MODEL=…`: use another model folder.

The environment that produced the results below is recorded in `env/pip_freeze.txt` and `env/gpu_info.txt`.

For a dataset with answers (train): `python eval.py <submission> --gold ../../train/answers.jsonl --questions ../../train/questions.jsonl`.

## Results on the public set (1,000 questions)
| | |
|---|---|
| Leaderboard score | **0.873** (PA, public, submitted 2026-11-08) |
| Run time | 17 minutes on 1× A100 40GB (including ~2 minutes of model loading) |
| Answered | 949 questions (number 580, percent 188, list 62, string 57, date 40, boolean 11, table 11) |
| Unanswerable | 30 questions |
| Abstain | 21 questions |
| Tools used | 85/89; 106 industry-tool calls |
| Thinking length | median ~900 characters, 90% under 1,900 characters, longest 23,000 characters |

Running `run_public.sh` regenerates `result/submission.jsonl` and `result/logs/log.jsonl`. For each question the log records the question, the tool call, the model's thinking and the answer.
