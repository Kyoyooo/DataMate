# DataMate — Zalo AI Challenge 2026

> **Competition requirements and reference material.** Compiled in original English from the competition information provided by the team lead, the three supplied evaluation/data images, and the separately labeled official Docker Submission Guide supplement. In case of conflict, the organizers' current published rules take precedence. Last checked: 2026-11-06 (GMT+7).
>
> **Scope:** This is a requirements reference, **not** a system architecture, implementation plan, or team work breakdown. Claude must derive and justify those artifacts separately when requested.

## 1. Description

Spreadsheets and simple databases are the most widely used data systems in the world. A shop owner keeps sales and inventory in Excel; a teacher keeps grades and attendance; a clinic keeps patient visits and medicine batches; an HR officer keeps timesheets; a cooperative keeps yields and input costs; a commune office keeps household statistics; a journalist downloads open data from the General Statistics Office; an employee of a large company wants a number from the data warehouse without waiting for the data team. All of them have the data. Almost none of them can write a query. What they want is to ask in plain Vietnamese — “Tháng này bán chạy nhất mặt hàng gì?”, “Tuần rồi bán được bao nhiêu ly trà sữa?”, “Còn ai nợ tiền chưa trả?”, “Thuốc nào sắp hết hạn trong kho?” — and get a correct answer.

**DataMate** challenges you to build an AI agent that answers natural-language Vietnamese questions directly on structured data (CSV, Excel, SQLite): given the raw files and a question, the agent returns a correct answer — or **declines to answer** when the data cannot support the question. The competition data is anchored in the world of Vietnamese small businesses — the largest group of spreadsheet users in the country and the one with the richest, messiest real-world data — but the capability you build is general: natural-language question answering over tabular data.

### 1.1 Input

- A **data package** for one business: one or more files (`.csv`, `.xlsx`, `.sqlite`) plus a short `README.md` describing the business.
- A **question** in everyday Vietnamese.
- An **as-of date**: the “today” against which relative time expressions (“tháng này”, “tuần rồi”, “cùng kỳ năm ngoái”) are resolved.
- A **rulebook** and a **solar–lunar calendar**, shared by every business of the split.

### 1.2 Output

A final answer of one of the types in the Evaluation section: a value (`number`, `percent`, `string`, `date`, `boolean`, `list`, `table`), `unanswerable` when the data cannot support the question, or `abstain` when the agent chooses not to answer.

Example input, one line of `questions.jsonl`:

```json
{"id": "q_06de33fa21cc", "business_id": "biz_118", "question": "sp bán dc nhiều nhất tuần rồi là gì", "as_of_date": "2026-03-04"}
```

Example output, one line of `submission.jsonl`:

```json
{"id": "q_06de33fa21cc", "type": "string", "answer": "Xi măng Hà Tiên PCB40 bao 50kg"}
```

## 2. Evaluation

### 2.1 Per-question scoring

Each answer is scored **correct**, **wrong**, or **abstain**. An answer of type `abstain` (or a missing answer) is an abstain. Any other answer is correct only if its **type equals the reference type** and its **value matches** the reference by the rules below; otherwise it is wrong. There is **no partial credit**.

**Transcription of attached Image 1 — answer types and matching:**

| Type | Answer content | Example | Matching rule |
|---|---|---|---|
| `number` | A numeric value (VND amounts, counts, quantities) | `48250000` | Exact match. Reference values are integers (VND amounts, counts, quantities) or rounded to 2 decimals. |
| `percent` | A percentage value, in percent | `-12.45` | Exact match after rounding to 2 decimal places; the sign must be correct. |
| `string` | A name (product, customer, branch, weekday, …) | `"Sting dâu 330ml"` | Both answer and each accepted reference form normalized and compared for exact equality. Normalize: (1) Unicode NFC; (2) lowercase; (3) replace every non-letter, non-digit and non-whitespace character with a space; (4) strip leading/trailing whitespace and collapse whitespace runs to one space. **Diacritics are not removed.** Accepted forms include spellings in the business data and its code; e.g. `sting dâu 330ml`, `sp0042`. |
| `date` | ISO date | `"2026-08-15"`, `"2025-09"` | Exact match: `yyyy-mm-dd`; for questions about a month, `yyyy-mm`. |
| `boolean` | True/false | `true` | Exact match. |
| `list` | Ordered list of names or numbers | `["Cà phê sữa", "Bạc xỉu", "Trà đào"]` | Always ordered and matched position by position. Order is question-specific or rulebook default. Elements obey string or number matching. |
| `table` | Small table with column names and rows | `{"columns": ["..."], "rows": [[...]]}` | Columns matched by normalized name; if names do not match, by position. Rows matched as a set; name cells use string rule, numeric cells use number rule. |
| `unanswerable` | Data does not contain what is needed | `—` | Correct if and only if reference is unanswerable. |
| `abstain` | Agent chooses not to answer | `—` | Scored as abstain regardless of reference. |

### 2.2 Ranking questions

Rankings use the criterion stated in the question, or the rulebook default when the question gives none, in **descending** order of that criterion over **valid orders only**; elements with equal values are ordered by **code ascending**. Questions whose reference ranking has a tie at the `k` boundary (or at rank 1 for “... nhất” questions) are excluded from test sets. If fewer than `k` candidates exist, the reference answer contains all of them.

### 2.3 Penalized Accuracy (PA)

**Transcription of attached Image 2:**

$$
\operatorname{PA}=\frac{1}{N}\sum_{i=1}^{N}s_i,\qquad
s_i=\begin{cases}
+1&\text{answer }i\text{ is correct},\\
0&\text{answer }i\text{ is abstain},\\
-1&\text{answer }i\text{ is wrong}.
\end{cases}
$$

All questions carry equal weight. Final ranking ties are broken by total inference time in the organizers' re-run, then earlier submission.

**Engineering implication (derived, not an official rule):** Relative to `abstain` (0), a speculative answer has positive expected value only if its estimated probability of correctness is above 0.5: `E[score] = p × 1 + (1 − p) × (−1) = 2p − 1`. A genuinely `unanswerable` reference can earn `+1` by correctly outputting `unanswerable`, but an incorrect `unanswerable` is `−1` like any other wrong answer.

## 3. Data

### 3.1 Business types and scale

- Vietnamese small businesses: grocery stores, coffee and bubble-tea shops, restaurants, pharmacies, building-material stores, motorbike repair shops, mother-and-baby stores, and more.
- The private test includes **business types absent from training and public test**.
- Per business: **12–30 months** of activity, seasonality (Tết, Mid-Autumn, public holidays, paydays, weekends), approximately **hundreds to 300,000 rows**.

### 3.2 Package structure

```text
<split>/
├── data/<business_id>/
│   ├── *.csv | *.xlsx | *.sqlite   # one or more files
│   └── README.md                  # business description and notes
├── rulebook.md                    # default rules and vocabulary
├── calendar.csv                   # solar–lunar calendar (Tết)
├── questions.jsonl                # one question per line
└── answers.jsonl                  # training only
```

Example question:

```json
{"id": "q_01234", "business_id": "biz_017", "question": "thang nay hang nao ban cham nhat, ton nhieu ma ban ko dc", "as_of_date": "2026-08-27"}
```

Training businesses also have reference answers in `answers.jsonl` linked by `id`. An `alias` list contains accepted alternate forms of name answers. Unanswerable questions have `"answer": null`. Do not include `alias` in submission.

```json
{"id": "q_06de33fa21cc", "type": "string", "answer": "Xi măng Hà Tiên PCB40 bao 50kg", "alias": ["SP0001"]}
```

README quality varies from comprehensive data dictionaries to a few informal notes or nothing useful.

### 3.3 Splits

**Transcription of attached Image 3:**

| Split | Businesses | Questions | Reference answers |
|---|---:|---:|---|
| Training | 30 | ~3,000 | Yes |
| Public test | 10–20 | ~1,000 | Hidden; scored on public leaderboard |
| Private test | 10–20 | ~500 | Hidden; released during private test phase; includes new business types |

### 3.4 Business rules

Each split supplies **its own `rulebook.md`**, fixing default meaning of terms where the question does not. **Rulebook contents can differ across splits; never assume the training rulebook is universal.**

Typical examples (only examples: the mounted split's rulebook is authoritative):

- Revenue = sum of line amounts **after line-level discounts**, **not** deducting order-level vouchers; excludes VAT and delivery fees, cancelled orders and orders with any returned item.
- “bán chạy” defaults to **quantity**.
- Week = **Monday–Sunday**.
- “tháng này” = from first day of month through **as_of_date inclusive**.
- Default cost = weighted-average purchase cost by lot.
- Tết window = from **23 tháng Chạp to mùng 10** (lunar calendar).

## 4. Submission format

Upload `submission.jsonl`, one JSON object per line. Valid types:

```jsonl
{"id":"q_01234","type":"string","answer":"Sting dâu 330ml"}
{"id":"q_01235","type":"number","answer":48250000}
{"id":"q_01236","type":"percent","answer":-12.45}
{"id":"q_01237","type":"date","answer":"2026-08-15"}
{"id":"q_01238","type":"boolean","answer":true}
{"id":"q_01239","type":"list","answer":["Cà phê sữa","Bạc xỉu","Trà đào"]}
{"id":"q_01240","type":"table","answer":{"columns":["khach_hang","so_tien_no"],"rows":[["Chị Lan",3200000],["Anh Tú",1500000]]}}
{"id":"q_01241","type":"unanswerable","reason":"Dữ liệu không có giá vốn nên không tính được lợi nhuận"}
{"id":"q_01242","type":"abstain"}
```

Notes: `reason` is optional for `unanswerable`. Missing rows score as `abstain`. Daily submission quota is governed by competition regulations.

### 4.1 Docker image submission

The image must contain inference source, training source/data, model weights and a `predict.sh` that reads the test set from `/data` and writes `/result/submission.jsonl` and per-question logs to `/result/logs/`, plus a README. Organizers re-run and inspect the logs if uploaded/private re-run results differ.

## 5. Competition rules

### 5.1 Rounds

1. **Round 1, public test:** develop, run on public test and upload `submission.jsonl`; public leaderboard is for development/reference.
2. **Final solution:** before deadline, submit and freeze a Docker image. Organizers mount `/data` and collect `/result/submission.jsonl`.
3. **Round 2, private test:** after freeze, organizers release private test; teams execute the **same frozen solution** and upload `submission.jsonl`. Official final ranking is determined by the organizers' re-run.

### 5.2 Technical requirements

1. **Teams/eligibility:** governed by general Zalo AI Challenge 2026 regulations.
2. **Models:** all inference model weights must have been publicly released **before 2026-10-26**, under a permitting license. Fine-tuning permitted. The **sum of parameters across all inference models must be ≤15 billion**, including all MoE parameters (even when not simultaneously loaded), embedding/reranking/classifier/LLMs. Quantization is allowed. Declare models in solution README.
3. **No external services:** inference strictly offline, inside Docker. No commercial LLM API calls, no downloads, no networking.
4. **No human in the loop:** fully automatic answers; no hard-coded answers or question/business-ID keyed logic.
5. **Code execution:** model-generated code may run inside container; mounted `/data` is read-only, temporary writes elsewhere.
6. **Data:** training split, self-generated data, public datasets/models are allowed. **No training on public or private test data and no collection of test answers by any means.**
7. **Reference compute:** 2 × NVIDIA RTX 5090 (32 GB VRAM each), 512 GB RAM. Docker must finish full private test in **6 wall-clock hours**, including load. Blackwell CUDA ≥12.8 and matching PyTorch/vLLM required; see official Docker guide.
8. **Reproducibility:** organizers' re-run determines score; require `|PA(uploaded) − PA(re-run)| ≤ 0.03`. Above threshold triggers investigation and potential extra run; unexplained discrepancies disqualify. If cutoff at 6 hours or early termination, only answers already written score; remaining questions abstain.

### 5.3 Submission guide / dates (GMT+7)

- **Public round:** **October 26 – November 16, 2026**, maximum **5 submission files/day**; quota resets daily.
- **Final Docker submission:** **November 16, 2026 at 23:59**; provide checksum and public Google Drive link via Solution Submission form. At most **2 solution submissions**; only the last is evaluated.
- **Private test release:** **November 20, 2026 at 09:00**.
- **Private results submission deadline:** **November 23, 2026 at 23:59**.
- **Top-2 announcement:** **December 2, 2026**.

Source Docker PDF: https://dl-challenge.zalo.ai/2026/datamate_dkewxftdzo/zac2026_DataMate_docker_guideline_final.pdf

---

## 6. Supplement: Official Docker Submission Guide

> The items in this section were checked against the 10-page official Docker PDF (2026-11-06). For container mechanics, consult the PDF itself as the authoritative source.

### 6.1 Required contents and reference environment

- Image contains complete offline inference code, full inference weights/tokenizers/configs, training/fine-tuning code/configs/dependencies/logs, training & validation data/generation evidence, data manifest/checksums, `/code/README.md` and `/code/predict.sh`.
- `/code/predict.sh` must run with **no arguments**. Fixed seeds/temperature/batch settings; no edits or downloads at runtime.
- Reference base image: `vllm/vllm-openai:v0.10.1.1` (tested with PyTorch 2.7.1+cu128, CUDA ≥ 12.8). Alternative base images must support RTX 5090 compute capability 12.0.
- Test runner: 2 GPUs, `--network none`, `--shm-size=16g`, `/data` read-only, `/result` writable, no privileged mode or Docker socket.
- **Max uncompressed `docker save` image tar = 100 GB**, including layers. Export linux/amd64.
- Any public URL exception is for an eligible **training-only** base checkpoint; inference weights **must** be packaged locally.

### 6.2 Per-question logging — important

Each question needs a corresponding log record under `/result/logs/`, containing:

- `id`: the question identifier;
- `answer`: final answer including its type;
- `elapsed_ms`: a non-negative integer wall-clock time from question start to final answer, including reads/reasoning/execution;
- `thinking`: **the actual model-generated reasoning as generated**, if any, without summarizing/truncating; a list in call order for multiple model calls; **`null` if no reasoning generated**;
- When executing code: `code` (actual generated code or predefined function and actual arguments) and `output` (actual computed result).

**Do not fabricate reasoning or code execution.** Never log private development-time prompts as though they were runtime model output. If the local inference model emits no thinking/reasoning, write `null`.

### 6.3 Reproducibility and runtime checklist

- Run the same container twice against the same input (offline) and compare outputs; greedy decoding/fixed seed help but GPU batching may still cause differences.
- Ensure every question has a persisted output line and log as soon as it finishes; partial results count if time is exhausted.
- Estimate total time as `load_time + average_question_time × 500`; six hours is 21,600 seconds, giving an average maximum of **43.2 s/question** *before* subtracting loading/overhead. A safety margin is essential; this is not a speed target.
- Set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` when appropriate.
- NVIDIA/NCCL changes in the PDF (NCCL 2.27.7, `NCCL_P2P_DISABLE=1`) are tested **examples**, not universal fixes; validate against the exact runtime.

Sample official test command (replace placeholders; shell on a host with supported NVIDIA GPUs):

```bash
docker run --rm --gpus '"device=0,1"' --network none --shm-size=16g \
  --entrypoint bash \
  -v /path/to/test_split:/data:ro \
  -v /path/to/output:/result \
  zaic2026_datamate_<team_name>:final /code/predict.sh
```

### 6.4 Training-verification evidence

- `/code/README.md`: approach, model names/sources/fixed revisions/original release dates/licenses/parameter counts, data sources/counts, commands and environment.
- `/code/training_code/`: reproducible preprocessing/training code, pinned dependencies, config and seeds, training and validation data, logs, checkpoints/evidence and `data_manifest.json` (local paths, hashes, counts, source versions).
- If commercial APIs were used **during permitted data generation** (not inference), preserve the actual prompts and responses used; follow the competition data rules. Never use public/private test to train or collect answers.
- State clearly if no fine-tuning/data generation was performed. If using an adapter, include both base weights + adapter or a merged model for inference.

### 6.5 Final export and checksums

```bash
set -o pipefail
docker save zaic2026_datamate_<team_name>:final | gzip > zaic2026_datamate_<team_name>.tar.gz
# Uncompressed .tar size in bytes:
gzip -dc zaic2026_datamate_<team_name>.tar.gz | wc -c
# Integrity checksum (do not rename after creating it):
md5sum zaic2026_datamate_<team_name>.tar.gz > zaic2026_datamate_<team_name>.tar.gz.md5
```

Before sending: download the archive from the shared link on another machine and verify with `md5sum -c`. The model/image/training/config/artifacts and declared public checkpoint revisions are **frozen** after the solution deadline.

### 6.6 Official sources

- Zalo DataMate Docker guideline: https://dl-challenge.zalo.ai/2026/datamate_dkewxftdzo/zac2026_DataMate_docker_guideline_final.pdf
- Claude Code quickstart: https://code.claude.com/docs/en/quickstart
- Claude Code best practices: https://code.claude.com/docs/en/best-practices
- Claude Code costs: https://code.claude.com/docs/en/costs
- Claude Code project memory: https://code.claude.com/docs/en/memory
