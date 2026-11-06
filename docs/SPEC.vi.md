# DataMate 2026 — Đặc tả kỹ thuật

| Trường | Giá trị |
|---|---|
| **Tài liệu** | `SPEC.md` |
| **Phiên bản** | 1.1 — phân công một Lead và bốn thành viên; quy tắc tương thích, conformance và determinism cho phát triển song song |
| **Trạng thái** | Baseline triển khai. Contract tại §5 **đóng băng ở I0 (2026-11-07 12:00 GMT+7)**; thay đổi sau đó theo §15. |
| **Ngày** | 2026-11-06 (GMT+7) |
| **Nguồn thiết kế có thẩm quyền** | `ARCHITECTURE_PROPOSAL.md` v2.1 (dẫn là **AP §x**) |
| **Tài liệu cấu trúc đi kèm** | `ARCHITECTURE.md` v1.1 (dẫn là **ARCH §x**) — bố cục module, góc nhìn runtime, seam |
| **Nguồn quy định tuân thủ** | `COMPETITION_BRIEF.md` (**Brief §x**) và `zac2026_DataMate_docker_guideline_final.md` (**DG §x**) |
| **Đối tượng đọc** | Lead và bốn thành viên M1–M4 (vai trò trong `IMPLEMENTATION_PLAN.md` §2) |

---

## 0. Cách đọc tài liệu

### 0.1 Ngôn ngữ quy phạm
**PHẢI (MUST)**, **KHÔNG ĐƯỢC (MUST NOT)**, **NÊN (SHOULD)**, **KHÔNG NÊN (SHOULD NOT)** và **CÓ THỂ (MAY)** được dùng theo RFC 2119. Mọi nội dung không đánh dấu là ví dụ, lý do hoặc ghi chú đều có tính quy phạm.

### 0.2 Tag
| Tag | Ý nghĩa |
|---|---|
| **[REQ]** | Yêu cầu cuộc thi hoặc hướng dẫn Docker (Brief / DG) |
| **[AP]** | Được ấn định bởi kiến trúc đã duyệt |
| **[SPEC]** | Lựa chọn cấp đặc tả tại đây trong phạm vi kiến trúc |
| **[DEFAULT DEC-n]** | Default chọn tại đây cho quyết định còn mở ở AP §13; chỉ đổi qua khóa config được nêu, không đổi code |
| **[VERIFY]** | Phải xác nhận bằng Brief, dữ liệu training hoặc test trước M1; giá trị hiện tại là giả định làm việc |

### 0.3 Tình trạng nguồn
- Có khi viết: `ARCHITECTURE_PROPOSAL.md` v2.1, `ARCHITECTURE.md` v1.1, `IMPLEMENTATION_PLAN.md` v1.1, `TASKS.md` v1.1 và hướng dẫn Docker.
- **Không có:** `CLAUDE.md` và `COMPETITION_BRIEF.md`. Dẫn chiếu Brief theo AP v2.1. Mọi mục phụ thuộc câu chữ chính xác của Brief (đặc biệt JSON wire shape của `list`/`table`, chế độ làm tròn, mã hóa `boolean`) được gắn **[VERIFY]** và liệt kê tại §17. Lead chịu trách nhiệm đối chiếu Brief trước **I0** (TASKS L-11).
- `ARCHITECTURE.md` bổ sung chi tiết cấp module. Tài liệu đó KHÔNG ĐƯỢC mâu thuẫn đặc tả này; xử lý xung đột theo quy trình thay đổi §15.

### 0.4 Làm rõ kiến trúc
Đặc tả này **không đưa ra thay đổi kiến trúc lớn**. Có bảy điểm làm rõ tại §16 (SC-1 … SC-7), giải quyết phần AP chưa quy định đủ. SC-3 khắc phục **lỗ hổng tương thích offline thiết yếu**: DuckDB mặc định tải extension lúc chạy, sẽ thất bại dưới `--network none`.

### 0.5 Người phụ trách
Theo vai trò trong `IMPLEMENTATION_PLAN.md` §2: **Lead** (contract, evaluation, tích hợp), **M1** Dữ liệu và ngữ nghĩa, **M2** Quy tắc, thời gian và câu trả lời, **M3** Reasoning Engine, **M4** Nền tảng và tuân thủ. Mỗi tiêu đề component tại §7 nêu người phụ trách.

---

## 1. Phạm vi

### 1.1 Trong phạm vi
Hệ thống inference đóng gói trong Docker image: entry point, mô hình process, data contract dùng chung, config, mọi component C1–C14 ở AP §6, prompt (theo contract, không quy định câu chữ), determinism, ngân sách hiệu năng, logging, testing, quy tắc tương thích khi phát triển song song, artifact tuân thủ và quy trình tích hợp.

### 1.2 Ngoài phạm vi
Lịch trình và phân công (`IMPLEMENTATION_PLAN.md`, `TASKS.md`), câu chữ prompt (M3 phụ trách, quản lý phiên bản trong `prompts/`) và fine-tuning (AP §8.3, chỉ Phase 3).

### 1.3 Nhãn phase
Mỗi yêu cầu thuộc **P1** (baseline, cần cho M1), **P2** (độ chính xác) hoặc **P3** (tùy chọn, có gate) theo AP §10. Yêu cầu không đánh dấu là P1. Tính năng P2/P3 PHẢI có config switch (§6) với default production `false` đến khi vượt gate.

---

## 2. Runtime contract của hệ thống

### 2.1 Entry point [REQ DG §5]
- `bash /code/predict.sh`, không đối số, không input tương tác.
- `predict.sh` PHẢI:
  1. `set -euo pipefail`.
  2. Export môi trường cố định ở §2.4.
  3. `mkdir -p /result/logs`.
  4. `exec python3 -m datamate.run --config /code/config/run_config.json --data-dir /data --result-dir /result`.
- `predict.sh` KHÔNG ĐƯỢC đọc biến môi trường làm thay đổi hành vi. Entry point Python PHẢI bỏ qua mọi override `DATAMATE_*` trừ khi có `--dev`; `predict.sh` không bao giờ truyền `--dev`.
- Flag chỉ dùng cho development (chỉ chấp nhận cùng `--dev`): `--set key=value` (override config, §6.1) và `--stub <stage>` (thay stage pipeline bằng đối tượng thay thế từ `contracts/testing.py` để tích hợp; stage: `split`, `setup`, `parse`, `temporal`, `solve`, `execute`, `decide`, `format`).
- Exit code: **0** khi `submission.jsonl` có đúng một dòng cho mỗi ID câu hỏi input phân biệt (đáp án hoặc abstain) và đã ghi `run.json`; **1** nếu không. Lỗi fatal vẫn PHẢI kích hoạt bước finalization tại §2.3 trước khi thoát.

### 2.2 Filesystem
| Đường dẫn | Quyền truy cập | Nội dung |
|---|---|---|
| `/data` | Read-only [REQ] | Input (DG §3.1). Không được ghi gì, kể cả SQLite journal (§7.2.4) |
| `/code` | Read-only theo quy ước | Mã, config, model, artifact training (DG §4) |
| `/tmp/datamate/` | Read-write | Thư mục gốc tạm; tạo khi khởi động; không đọc lại giữa các lần chạy |
| `/tmp/datamate/biz/<bkey>/catalog.duckdb` | rw khi setup, sau đó ro | Database từng doanh nghiệp |
| `/tmp/datamate/sandbox/<pid>/` | rw | Vùng tạm executor |
| `/result/submission.jsonl` | Ghi | §8.2 |
| `/result/logs/questions.jsonl` | Ghi | §8.3 |
| `/result/logs/businesses.jsonl` | Ghi | §8.4 |
| `/result/logs/run.json` | Ghi | §8.5 |
| `/result/logs/progress.log` | Ghi | Tiến độ dễ đọc, nội dung không quy phạm |

`<bkey>` là tên thư mục doanh nghiệp được làm sạch thành `[A-Za-z0-9_-]`, chỉ dùng làm khóa đường dẫn.

### 2.3 Vòng đời lần chạy
```
T0  process start (monotonic clock starts; wall-clock budget counts from here)
 1  load + validate RunConfig; compute config_sha256
 2  validate /data layout; read questions.jsonl (§7.0)
 3  in parallel:
      a. start model replicas (C13) and wait for health + warm-up
      b. split bootstrap (C1): rulebook, calendar, TemporalParams (needs a replica)
      c. business setup (C2, then C3 in P2) in a process pool, ordered per §7.12
 4  as each business becomes READY and the split context is READY, enqueue its questions
 5  question workers run the per-question pipeline (§7.4–§7.11)
 6  global stop at min(all done, T0 + global_hard_stop_s)
 7  finalize: write `abstain` for every unwritten id; write run.json; stop replicas; exit
```

### 2.4 Môi trường cố định (đặt trong Dockerfile và export lại bởi `predict.sh`)
| Biến | Giá trị | Lý do |
|---|---|---|
| `HF_HUB_OFFLINE` | `1` | [REQ DG §9] |
| `TRANSFORMERS_OFFLINE` | `1` | [REQ DG §9] |
| `PYTHONHASHSEED` | `0` | Determinism |
| `PYTHONUNBUFFERED` | `1` | Logging |
| `TOKENIZERS_PARALLELISM` | `false` | Determinism, an toàn fork |
| `OMP_NUM_THREADS`, `MKL_NUM_THREADS`, `OPENBLAS_NUM_THREADS` | `1` | Determinism thư viện số trong sandbox worker |
| `NCCL_P2P_DISABLE` | `1` | [DG §9] không gây hại trong topology DP; chỉ bắt buộc cho dự phòng TP |
| `VLLM_BATCH_INVARIANT` | `0` **[DEFAULT DEC-3]**; chỉ `1` nếu xác thực thành công (AP §7.7) | Determinism |
| `VLLM_NO_USAGE_STATS`, `DO_NOT_TRACK` | `1` | Không gọi ra ngoài |

### 2.5 Hành vi bị cấm [REQ]
- Không truy cập mạng dưới mọi hình thức, trừ loopback do C13 sử dụng.
- Không chọn đáp án, nhánh prompt, ngưỡng hoặc code path theo `id` câu hỏi hay `business_id`. Chỉ CÓ THỂ dùng chúng làm khóa opaque để nhóm, sắp thứ tự, đặt tên file và log. Static check trong CI PHẢI thất bại nếu có string literal khớp mẫu ID từ training split xuất hiện trong `src/`.
- Không ghi dưới `/data`.

---

## 3. Mô hình process

```
main process (asyncio event loop)
├── Orchestrator (C12), Writer task (C11), ModelClient (C13 client)
├── replica-0: vLLM OpenAI server subprocess, CUDA_VISIBLE_DEVICES=0, 127.0.0.1:8100
├── replica-1: vLLM OpenAI server subprocess, CUDA_VISIBLE_DEVICES=1, 127.0.0.1:8101
├── setup pool: ProcessPoolExecutor (spawn), size = setup_workers   → C2, C3 DB work
└── sandbox pool: custom killable worker pool (spawn), size = sandbox_workers → C8 (§7.8)
```
- Start method PHẢI là `spawn` cho mọi pool (không kế thừa trạng thái CUDA hoặc event loop). Sandbox pool không phải `ProcessPoolExecutor`, vì phải hủy và thay riêng worker timeout.
- Chỉ C11 ghi `/result`. Chỉ C13 giao tiếp model server. Chỉ C2/C3 ghi file DuckDB. Chỉ C8 thực thi mã được sinh.
- Fallback **[AP §6.3]**: nếu không có loopback serving dưới `--network none` (kiểm tra tại G6), replica chạy dưới dạng engine `AsyncLLM` in-process sau cùng protocol `ModelClient` (§7.13.3). Không component nào khác được nhận biết khác biệt.

---

## 4. Bố cục repository và module

### 4.1 Bố cục image [REQ DG §4]
```
/code/
├── predict.sh
├── README.md                     # §13.1
├── requirements.txt              # pinned, generated from the lock (§4.4)
├── config/run_config.json        # frozen production config (§6)
├── src/datamate/                 # inference package (installed with pip -e or on PYTHONPATH)
├── models/<model_dir>/           # only the selected model (AP §7.9)
└── training_code/                # §13.2
```

### 4.2 Bố cục package, phân công và review
| Module | Component | Phụ trách | Reviewer bắt buộc | Phụ thuộc |
|---|---|---|---|---|
| `datamate/contracts/` | Mọi kiểu chung (§5), protocol, test double | **Lead** | Thành viên có component tạo hoặc dùng kiểu thay đổi | stdlib, pydantic |
| `datamate/config.py` | RunConfig loader (§6) | M4 | Lead | contracts |
| `datamate/run.py` | Entry point, vòng đời, stub mode (§2) | M4 | Lead | Tất cả |
| `datamate/rules/` | C1 Split Bootstrap | M2 | M3 | contracts, llm, prompts |
| `datamate/temporal/` | C5 Temporal Resolver, LunarCalendar | M2 | M3 | contracts |
| `datamate/semantics/` | C3 Semantic Compiler (P2) | M1 | M2 | contracts, llm, prompts, catalog |
| `datamate/lexicon/` | Lexicon viết tắt, text folding | M1 | M2 | — |
| `datamate/ingest/` | Reader, parser C2 | M1 | M3 | contracts, lexicon |
| `datamate/catalog/` | Materialization DuckDB, profiling, SchemaCard C2 | M1 | M3 | contracts, ingest, llm (tokenizer) |
| `datamate/entities/` | C6 Entity Linker (P2) | M1 | M3 | contracts, lexicon |
| `datamate/llm/client.py`, `tokenizer.py` | Client C13 | M3 | M4 | contracts |
| `datamate/llm/replicas.py`, `inprocess.py` | Replica C13 | M4 | M3 | contracts |
| `datamate/prompts/` | Prompt template + ID (§7.13.5) | M3 | Lead | — |
| `datamate/parse/` | C4 Question Parser | M3 | M2 | contracts, llm, prompts, lexicon |
| `datamate/solver/` | C7 Solver, context pack | M3 | M2 | contracts, llm, prompts, lexicon |
| `datamate/sandbox/` | C8 Executor | M3 | M4 | contracts |
| `datamate/decision/` | C9 Verifier & Decision | M2 | Lead | contracts, lexicon |
| `datamate/formatting/` | C10 Formatter | M2 | Lead | contracts |
| `datamate/runtime/` | C12 Orchestrator, C11 Writer, record | M4 | M3 (orchestration), Lead (record) | contracts, mọi module pipeline |
| `datamate/eval/` | Scorer, harness C14 (không được `run.py` import) | **Lead** | M2 (chấm điểm), M4 (harness) | contracts, tất cả |
| `tests/contract/`, `tests/integration/`, `tests/determinism/`, `tests/golden/` | Test dùng chung (§14) | **Lead** | M2 cho golden test | — |

Cột phân công và reviewer được phản ánh trong `CODEOWNERS`; CI yêu cầu phê duyệt của reviewer được liệt kê.

### 4.3 Quy tắc dependency và public API
- `contracts` không import gì từ `datamate`.
- **Public API.** Mỗi package khai báo tên public trong `__all__` của `__init__.py`. Package khác chỉ CÓ THỂ import các tên đó (hoặc kiểu contract). Không import chéo package module private và tên có prefix `_`. CI kiểm tra điều này.
- Module pipeline giao tiếp **chỉ** qua kiểu contract và protocol tại §5.10.
- Phân lớp theo ARCH §4.2: module chỉ import cùng lớp hoặc lớp thấp hơn.
- `eval` CÓ THỂ import mọi thứ; không gì trên luồng inference import `eval`.
- Cấm cyclic import; CI chạy kiểm tra import graph.

### 4.4 Dependency
- Base image theo DEC-3 (AP §7.9). Phiên bản Python = Python của base image.
- `requirements.lock` PHẢI được tạo bằng `pip freeze` **bên trong base image đã chọn** sau khi cài requirement dự án; mọi môi trường development cài từ cùng lock (AP §4.2). Thêm dependency là thay đổi lock, cần Lead và M4 duyệt.
- Dependency cấp dự án (pin chính xác tại M0 trong lock): `duckdb`, `python-calamine`, `openpyxl` (reader fallback), `pandas`, `pyarrow`, `rapidfuzz`, `charset-normalizer`, `httpx`; `pydantic` v2, `transformers` (chỉ tokenizer) và `openai` lấy từ base image.
- Không dependency nào được truy cập mạng lúc import hoặc runtime. Xác minh bằng G6 (`--network none`).

---

## 5. Contract dùng chung

### 5.1 Quy tắc chung
- Triển khai bằng model **pydantic v2** trong `datamate/contracts/`, với `model_config = ConfigDict(frozen=True, extra="forbid", strict=True)`.
- `CONTRACTS_VERSION = "1.0.0"` (semver, §15). Mọi log record mang phiên bản này.
- JSON Schema được export bằng script tới `contracts/schemas/<Name>.json` và commit. CI thất bại nếu schema export khác bản commit mà không tăng phiên bản.
- Ngày là `datetime.date` trong bộ nhớ, chuỗi ISO-8601 trên wire. Giá trị decimal là `decimal.Decimal` trong bộ nhớ và **không bao giờ** đi qua binary floating point giữa executor và formatter.
- Text được chuẩn hóa NFC tại ranh giới đi vào hệ thống (file input, output model). Contract không chứa text đã bỏ dấu, trừ trường được đặt tên tường minh `*_folded`.

### 5.2 Enum
```text
AnswerType     = number | percent | string | date | boolean | list | table
DecisionKind   = answer | unanswerable | abstain
DateGranularity= day | month
Granularity    = day | week | month | quarter | year | range
Stage          = rule_profile | compile | parse | solve | repair | fallback | fallback_repair
ExprKind       = date | date_range | calendar_period | relative_period | rolling
               | same_period_prior_year | lunar_holiday | lunar_date_range | all_time | unsupported
MentionKind    = product | category | customer | supplier | employee | store | channel | other
ResultShape    = scalar | list | table
ReasonCode     = see §10.2
```

### 5.3 Input
**`Question`**
| Trường | Type | Ràng buộc |
|---|---|---|
| `id` | str | Không rỗng |
| `business_id` | str | Không rỗng; phải khớp thư mục dưới `/data/data/`, nếu không abstain câu hỏi với `E_INPUT_BUSINESS_MISSING` |
| `question` | str | NFC |
| `as_of_date` | date | ISO `yyyy-mm-dd`; không parse được → abstain với `E_INPUT_AS_OF` |
| `line_no` | int | Dòng trong `questions.jsonl`, bắt đầu từ 1 (chỉ dùng sắp thứ tự) |

### 5.4 Cấu hình
**`RunConfig`** — xem mọi khóa tại §6. Tải một lần; bất biến; `config_sha256` = SHA-256 của JSON chuẩn (key có sắp xếp, không khoảng trắng).

### 5.5 Contract cấp split
**`TemporalParams`** (SC-1; P1)
| Trường | Type | Ý nghĩa | Fallback tổng quát khi rulebook không nêu |
|---|---|---|---|
| `week_start` | `mon`/`sun` | Ngày đầu tuần | `mon` (ISO 8601) |
| `to_date_end` | `as_of` / `day_before_as_of` | Kết thúc window “tuần/tháng/năm này” và “đến nay” | `as_of` |
| `rolling_includes_as_of` | bool | “N ngày qua” có gồm `as_of_date` không | `true` |
| `prior_period_full` | bool | “Tuần/tháng trước” nghĩa là toàn bộ kỳ lịch trước | `true` |
| `year_omitted_policy` | `most_recent_not_after_as_of` | Suy ra năm cho “tháng 3”, “Q2” | Cố định |
| `same_period_alignment` | `calendar_dates` / `elapsed_days` | Cách “cùng kỳ năm ngoái” ánh xạ window | `calendar_dates` |
| `provenance` | Map trường → `{source: "rulebook"|"generic", span: str|null}` | Dấu vết kiểm toán | — |

Fallback là **quy ước tổng quát, không phải giá trị học từ training rulebook**; mỗi lần dùng fallback được log với `provenance.source="generic"` và bật `F_TEMPORAL_GENERIC` như feature verifier (§7.9).

**`HolidayWindow`** (P2): `name_key` (str, từ từ vựng rulebook), `anchor` (`{lunar_month, lunar_day}`), `start_offset_days` (int), `end_offset_days` (int), `span` (trích dẫn rulebook).

**`RuleProfile`** (P2): `temporal: TemporalParams`, `holidays: list[HolidayWindow]`, `default_rank_criterion: {metric_text: str, span: str} | null`, `definitions: list[{term: str, text: str, span: str}]`, `unresolved: list[str]`.

**`SplitContext`**: `rulebook_text: str` (nguyên văn, NFC), `rulebook_sha256: str`, `temporal: TemporalParams`, `rule_profile: RuleProfile | null`, `calendar: LunarCalendar` (protocol §5.10), `calendar_ok: bool`.

### 5.6 Contract cấp doanh nghiệp
**`ColumnInfo`**
| Trường | Type | Ghi chú |
|---|---|---|
| `name` | str | SQL identifier (SC-2) |
| `original_name` | str | Header như khi tìm thấy, NFC |
| `sql_type` | str | `BIGINT`, `DECIMAL(38,6)`, `DOUBLE`, `VARCHAR`, `DATE`, `TIMESTAMP`, `BOOLEAN` |
| `semantic_hint` | str \| null | `money`, `quantity`, `percent`, `code`, `name`, `status`, `date`, hoặc null |
| `null_rate` | float | 0–1 |
| `distinct_count` | int | Chính xác |
| `min`, `max` | str \| null | Dạng chuỗi |
| `top_values` | list[{value: str, count: int}] | §7.2.8 |
| `raw_column` | str \| null | Tên cột VARCHAR raw được giữ lại khi parsing thay đổi giá trị |
| `parse_rate` | float | Tỷ lệ giá trị raw không null parse được |
| `format_note` | str \| null | Ví dụ `dot_thousands`, `dd/mm/yyyy`, `excel_serial` |

**`TableInfo`**: `name`, `source_file` (tương đối so với thư mục doanh nghiệp), `source_part` (sheet / SQLite table / null), `row_count`, `columns: list[ColumnInfo]`, `candidate_keys: list[list[str]]`, `dropped_rows: {total_rows: int, note_rows: int, blank_rows: int}`.

**`JoinEdge`**: `left: "table.col"`, `right: "table.col"`, `cardinality: "n:1"|"1:1"|"n:n"`, `match_rate: float`.

**`BusinessCatalog`**
| Trường | Type |
|---|---|
| `business_id` | str |
| `bkey` | str |
| `db_path` | str |
| `tables` | list[TableInfo] |
| `joins` | list[JoinEdge] |
| `date_columns` | list[{column: "table.col", min: date, max: date}] |
| `data_range` | `DateRange \| null`, trong đó `DateRange = {start: date, end: date}`; hợp của các cột ngày thuộc table không phải dimension |
| `readme_text` | str \| null (nguyên văn, chỉ cắt ngắn cho context pack, không cắt khi lưu trữ) |
| `schema_card` | str (§7.2.9) |
| `schema_card_sha256` | str |
| `warnings` | list[{code: str, detail: str}] |
| `setup_ms` | int |
| `status` | `ready` / `failed` |

**`ViewSpec`** (P2): `name` (prefix `v_`), `purpose`, `ddl`, `depends_on: list[str]`, `validation: {executed: bool, row_count: int, checks: list[{name, passed, detail}]}`, `enabled: bool`, `category: str`.

**`SemanticAnnotations`** (P2): `table_roles: map table → {role: fact|dimension|lookup|log|other, grain: str}`, `value_semantics: list[{column, value, meaning}]`, `join_paths: list[JoinEdge]`, `views: list[ViewSpec]`, `compile_calls: list[ModelCall]`.

### 5.7 Contract cấp câu hỏi
**`TimeExpr`** — discriminated union theo `kind` (SC-6):
| `kind` | Trường | Ví dụ |
|---|---|---|
| `date` | `date` | “ngày 5/3/2025” |
| `date_range` | `start`, `end` | “từ 1/3 đến 15/3” (nếu thiếu năm thì xác định theo policy; model xuất năm `null`) |
| `calendar_period` | `unit` (month/quarter/year/week), `year: int\|null`, `index: int\|null` | “tháng 3/2025”, “quý 2”, “năm 2024” |
| `relative_period` | `unit` (day/week/month/quarter/year), `offset: int`, `to_date: bool` | “tuần rồi” → week, −1, false; “tháng này” → month, 0, true |
| `rolling` | `unit` (day/week/month), `count: int ≥ 1` | “7 ngày qua” |
| `same_period_prior_year` | `ref: int` (index trong `QuestionFrame.time`) | “cùng kỳ năm ngoái” |
| `lunar_holiday` (P2) | `name_key: str`, `year_offset: int` | “Tết năm nay” |
| `lunar_date_range` (P2) | `lunar_month`, `lunar_day_start\|null`, `lunar_day_end\|null`, `year_offset` | “rằm tháng 8” |
| `all_time` | — | Không nêu ràng buộc thời gian |
| `unsupported` | `reason: str` | Mọi trường hợp khác |

**`TimeRef`**: `span: str` (substring nguyên văn của câu hỏi), `role: primary|comparison|baseline`, `expr: TimeExpr`.

**`Mention`**: `text: str` (substring nguyên văn), `kind: MentionKind`.

**`RankingSpec`**: `k: int|null`, `direction: top|bottom`, `criterion_text: str|null` (null → tiêu chí mặc định trong rulebook).

**`Answerability`**: `status: answerable|missing_field|unclear`, `missing_fields: list[str]`.

**`QuestionFrame`** (output model, ràng buộc bằng schema, §7.4)
| Trường | Type |
|---|---|
| `expected_type` | AnswerType |
| `date_granularity` | DateGranularity \| null (bắt buộc khi và chỉ khi `expected_type == date`) |
| `metric_text` | str (≤ 200 ký tự) |
| `mentions` | list[Mention] (≤ 10) |
| `time` | list[TimeRef] (≤ 4) |
| `ranking` | RankingSpec \| null (bắt buộc khi và chỉ khi `expected_type == list`) |
| `group_by_text` | list[str] |
| `comparison` | `{kind: change_pct|change_abs|ratio|difference, baseline_ref: int}` \| null |
| `needs_procedural` | bool |
| `answerability` | Answerability |

**`TimeWindow`**: `ref_index: int`, `role`, `start: date`, `end: date` (bao gồm hai biên, start ≤ end), `granularity: Granularity`, `provenance: list[str]` (tên tham số và nguồn đã dùng), `coverage_ratio: float` (số ngày giao với `data_range` / số ngày window; `null` nếu không có dải dữ liệu), `flags: list[str]`.

**`EntityCandidate`** (P2): `mention_index: int`, `table`, `column`, `value: str` (như lưu trữ), `code: str|null`, `score: float` (0–100), `strength: strong|weak`.

**`ModelCall`**
| Trường | Type | Ghi chú |
|---|---|---|
| `call_id` | str | `<question_id or bkey>:<stage>:<n>` |
| `stage` | Stage | |
| `replica` | int | |
| `template_id` | str | §7.13.5 |
| `request_sha256` | str | SHA-256 của JSON request chuẩn (message + tham số) |
| `params` | object | Mọi tham số decoding thực sự gửi đi |
| `content` | str | Chính xác `message.content` được trả về |
| `reasoning` | str \| null | Chính xác `reasoning_content` được trả về, hoặc null |
| `finish_reason` | str | |
| `prompt_tokens`, `completion_tokens` | int | |
| `latency_ms` | int | |
| `error` | str \| null | Mã lỗi transport/timeout |

**`ExecutionResult`**: `language: sql|python`, `code: str` (văn bản thực thi chính xác), `ok: bool`, `error_code: ReasonCode|null`, `error_text: str|null` (≤ 2.000 ký tự, cắt kèm dấu hiệu — error text để chẩn đoán, không phải trường tuân thủ), `columns: list[str]`, `column_types: list[str]`, `rows: list[list[JSONValue]]` (≤ `max_result_rows`), `row_count: int` (số dòng fetch, giới hạn ở `max_result_rows + 1`), `truncated: bool` (true khi và chỉ khi có hơn `max_result_rows` dòng), `duration_ms: int`, `helper_call: {function: str, inputs: object} | null`.

Giá trị dòng qua ranh giới process được mã hóa bằng JSON có tag (`{"t":"dec","v":"123.450000"}`, `{"t":"date","v":"2025-03-01"}`, chuỗi thường, int, bool, null), để không giá trị nào đi qua float.

**`SolverAttempt`**: `attempt_no: int`, `stage: Stage`, `model_call: ModelCall`, `solver_output: SolverOutput | null` (null nếu output model không hợp lệ), `execution: ExecutionResult | null`, `contract_check: {ok: bool, reason: ReasonCode|null}`.

**`SolverOutput`** (output model, ràng buộc bằng schema, §7.7.3): `sql: str` (hoặc `python: str` cho fallback), `result_shape: ResultShape`, `answer_column: str|null`, `notes: str` (≤ 300 ký tự).

**`TypedValue`** — discriminated union:
| `type` | Giá trị trong bộ nhớ |
|---|---|
| `number`, `percent` | `Decimal` |
| `string` | `str` |
| `date` | `{value: date, granularity: DateGranularity}` |
| `boolean` | `bool` |
| `list` | `list[{item: JSONScalar, sort_key: Decimal|str|null, tie_code: str|null}]` |
| `table` | `{columns: list[str], rows: list[list[JSONScalar]]}` |

**`Decision`**: `kind: DecisionKind`, `value: TypedValue|null` (có giá trị khi và chỉ khi trả lời), `reason_code: ReasonCode`, `unanswerable_reason: str|null`, `features: map[str, float|int|bool|str]`, `p_correct: float|null` (P3).

### 5.8 Output contract
**`SubmissionRecord`** [REQ DG §3.2] — đúng một trong các dạng:
```json
{"id": "q_01234", "type": "number", "answer": 48250000}
{"id": "q_01235", "type": "unanswerable", "reason": "missing_field:cost"}
{"id": "q_01236", "type": "abstain"}
```
**`LogRecord`** — §8.3. **`BusinessLogRecord`** — §8.4. **`RunRecord`** — §8.5.

### 5.9 Invariant contract (thực thi bằng validator và kiểm thử)
1. `TimeWindow.start ≤ TimeWindow.end`.
2. Có `QuestionFrame.ranking` khi và chỉ khi `expected_type == list`; có `date_granularity` khi và chỉ khi `expected_type == date`.
3. `Decision.value.type == SubmissionRecord.type` đối với đáp án.
4. Mọi `Mention.text` và `TimeRef.span` là substring của câu hỏi gốc **hoặc** đã chuẩn hóa; nếu không, bỏ mục đó và bật `F_SPAN_MISMATCH`.
5. `ModelCall.content` và `.reasoning` lưu đúng từng byte như trả về.

### 5.10 Protocol và đối tượng thay thế (`contracts/protocols.py`, `contracts/testing.py`)
```python
class ModelClient(Protocol):
    async def call(self, *, stage: Stage, template_id: str, messages: list[dict],
                   json_schema: dict | None, max_tokens: int, enable_thinking: bool,
                   replica: int, call_id: str, timeout_s: float) -> ModelCall: ...

class LunarCalendar(Protocol):
    def to_lunar(self, d: date) -> tuple[int, int, int, bool]: ...   # (year, month, day, is_leap)
    def to_solar(self, lunar_year: int, month: int, day: int, is_leap: bool = False) -> date: ...
    def covers(self, d: date) -> bool: ...

class Executor(Protocol):
    async def run_sql(self, db_path: str, sql: str, limits: ExecLimits) -> ExecutionResult: ...
    async def run_python(self, db_path: str, code: str, limits: ExecLimits) -> ExecutionResult: ...  # P2

class Deadline(Protocol):
    @property
    def soft_expired(self) -> bool: ...
    @property
    def hard_expired(self) -> bool: ...
    def remaining_s(self) -> float: ...

# ExecLimits is the RunConfig.exec_limits section (a contract type).

class SubmissionSink(Protocol):
    async def write(self, record: SubmissionRecord, log: LogRecord) -> None: ...
    def written_ids(self) -> frozenset[str]: ...
```

Đối tượng thay thế trong `contracts/testing.py` PHẢI có tại I0 (11-07 12:00) và PHẢI vượt bộ conformance test ở §14.3:

| Đối tượng thay thế | Triển khai | Hành vi |
|---|---|---|
| `ScriptedModelClient` | `ModelClient` | Trả `content`/`reasoning` cố định theo `(stage, template_id)` hoặc thứ tự call |
| `ReplayModelClient` | `ModelClient` | Trả `ModelCall` ghi sẵn theo khóa `request_sha256`; request không biết → `ModelCall.error = "E_REPLAY_MISS"` |
| `FakeExecutor` | `Executor` | Chạy SQL in-process trên kết nối DuckDB read-only, cùng mã hóa và mã lỗi như C8 |
| `FixtureLunarCalendar` | `LunarCalendar` | Tạo từ fixture calendar nhỏ bao phủ hai năm âm lịch |
| `FakeDeadline` | `Deadline` | Đồng hồ tiến lên thủ công |
| `InMemorySink` | `SubmissionSink` | Ghi các lần write theo thứ tự; từ chối ID trùng |
| `fixture_split_context()` | — | `SplitContext` với `TemporalParams` generic và fixture calendar |

M1 cung cấp fake catalog (`make_fake_catalog()` và catalog dựng sẵn dưới `tests/fixtures/catalogs/`) trước cuối ngày 11-07 (TASKS M1-11).

---

## 6. Cấu hình

### 6.1 Quy tắc
- Config production là `/code/config/run_config.json`, đóng băng trong image [REQ DG §5.3]. Đây là nguồn **duy nhất** cho giá trị có thể điều chỉnh; không module nào được hard-code giá trị liệt kê tại đây.
- Khóa không biết là lỗi. Khóa thiếu nhận default dưới đây; config hiệu lực (đã điền default) là nội dung được `config_sha256` hash và `run.json` ghi lại.
- Dev harness CÓ THỂ override qua `--dev --set key=value`; override được ghi trong run record. `predict.sh` không thể truyền override. Không thành viên nào sửa `run_config.json` local để thử nghiệm.
- Thêm khóa cần default và một dòng trong mục này, merge cùng code đọc khóa đó (§15).

### 6.2 Khóa và default
```json
{
  "contracts_version": "1.0.0",
  "model": {
    "path": "/code/models/<selected>",
    "serving": "http",
    "served_name": "datamate",
    "revision": "<hf-commit-sha>",
    "dtype": "bfloat16",
    "quantization": null,
    "max_model_len": 32768,
    "gpu_memory_utilization": 0.90,
    "max_num_seqs": 64,
    "enable_prefix_caching": true,
    "reasoning_parser": null,
    "replicas": 2,
    "tensor_parallel_size": 1,
    "base_port": 8100,
    "startup_timeout_s": 900,
    "extra_server_args": []
  },
  "decoding": {
    "temperature": 0.0,
    "top_p": 1.0,
    "seed": 20261116,
    "stages": {
      "rule_profile": {"max_tokens": 2048, "enable_thinking": false},
      "compile":      {"max_tokens": 4096, "enable_thinking": false},
      "parse":        {"max_tokens": 1024, "enable_thinking": false},
      "solve":        {"max_tokens": 2048, "enable_thinking": false},
      "repair":       {"max_tokens": 2048, "enable_thinking": false},
      "fallback":     {"max_tokens": 3072, "enable_thinking": false}
    }
  },
  "concurrency": {"questions_per_replica": 24, "setup_workers": 8, "setup_threads_per_business": 4, "sandbox_workers": 16},
  "deadlines": {
    "model_call_timeout_s": 120,
    "question_soft_s": 120,
    "question_hard_s": 300,
    "target_finish_s": 9000,
    "degrade_if_projected_finish_s": 14400,
    "global_hard_stop_s": 19800
  },
  "exec_limits": {
    "sql_timeout_s": 20, "python_timeout_s": 30,
    "memory_limit_mb": 8192, "max_result_rows": 1000, "duckdb_threads": 1
  },
  "solver": {
    "max_repairs": 2, "fewshot_k": 3,
    "context_budget_tokens": 24000, "schema_card_budget_tokens": 8000,
    "readme_budget_tokens": 2000, "python_fallback": false
  },
  "features": {
    "rule_profile": false, "lunar": false, "entity_linker": false,
    "compiled_views": false, "compiled_views_categories": null, "verifier_features": false,
    "calibrator": false, "multi_strategy": false
  },
  "decision": {"policy": "rule_gate", "calibrator_path": null, "threshold": 0.5,
               "abstain_on_zero_coverage": true},
  "formatting": {"rounding": "ROUND_HALF_UP", "integer_literal_when_integral": true,
                 "tie_code_order": "numeric_if_all_numeric_else_lexicographic"},
  "ingest": {
    "numeric_accept_rate": 0.98, "date_accept_rate": 0.98,
    "max_header_scan_rows": 20, "low_cardinality_max": 50, "top_values_max": 30,
    "max_file_mb": 2048
  },
  "entities": {"top_k": 5, "strong_threshold": 85, "weak_threshold": 70},
  "logging": {"progress_interval_s": 60, "max_output_rows_logged": 50}
}
```
Ghi chú:
- `enable_thinking: false` ở mọi nơi là **[DEFAULT DEC-10]**.
- `reasoning_parser` được đặt bởi DEC-3 (ví dụ `qwen3` cho model Qwen). PHẢI đặt khi bất kỳ stage nào bật thinking, để reasoning nằm trong `reasoning_content` thay vì `content`.
- `decision.policy = "rule_gate"` là **[DEFAULT DEC-8]**.
- `features.compiled_views = false` là **[DEFAULT DEC-4]**.
- `max_num_seqs` và `questions_per_replica` cố định; KHÔNG ĐƯỢC điều chỉnh khi chạy (AP §6.11).
- `global_hard_stop_s` = 5 giờ 30 phút, chừa 30 phút trong giới hạn 6 giờ cho finalization và dự phòng.

---

## 7. Đặc tả component

Mỗi component liệt kê: người phụ trách, interface, hành vi, xử lý lỗi, ngân sách và test bắt buộc. Tên và type trong function signature có tính quy phạm; cấu trúc nội bộ tự do.

### 7.0 Tải input (M4 phụ trách, trong `run.py`)
- Đọc `/data/questions.jsonl` dưới dạng UTF-8 (chấp nhận BOM). Parse độc lập từng dòng không trống.
- Dòng không phải JSON hợp lệ hoặc thiếu `id` được bỏ qua và đếm trong `run.json.errors` (không thể trả lời nếu thiếu ID).
- Dòng có `id` nhưng trường khác không hợp lệ trở thành `Question` được abstain với input reason code tương ứng.
- Trùng `id`: xử lý lần xuất hiện đầu; bỏ và đếm các lần sau. Đúng một dòng submission mỗi ID phân biệt.
- Phát hiện thư mục `/data/data/<business_id>/` bằng listing; không setup doanh nghiệp không có câu hỏi.

### 7.1 C1 Split Bootstrap (M2 phụ trách)
```python
async def bootstrap_split(data_dir: Path, cfg: RunConfig, client: ModelClient) -> SplitContext
```
1. **Rulebook.** Đọc byte `rulebook.md`; decode UTF-8 (bỏ BOM); chuẩn hóa NFC; lưu nguyên văn. Thiếu hoặc không đọc được → `rulebook_text = ""`, cảnh báo `W_RULEBOOK_MISSING`; tiếp tục với tham số generic.
2. **Calendar.** Đọc `calendar.csv`. Ánh xạ cột dùng bảng alias (ngày dương; năm, tháng, ngày âm; cờ nhuận) **[VERIFY với file thực tế tại M0]**. Validation: ngày dương tăng nghiêm ngặt từng ngày, không khoảng trống; trường âm lịch trong miền hợp lệ. Thất bại → `calendar_ok = false`; không dùng tính năng âm lịch; cảnh báo `W_CALENDAR_INVALID`.
3. **TemporalParams (P1, SC-1).** Một model call, stage `rule_profile`, template `rules.temporal.v1`, output ràng buộc JSON Schema: mỗi trường §5.5 là `{value, span}`, trong đó `span` là trích dẫn nguyên văn rulebook hoặc null.
   - Validation từng trường: `span` PHẢI là substring của rulebook sau gộp khoảng trắng; `value` PHẢI thuộc tập được phép. Trường hỏng một trong hai check nhận fallback generic với `provenance.source = "generic"`.
   - Rulebook rỗng thì bỏ call, mọi trường generic.
   - Call chạy trên replica 0 trước khi dispatch câu hỏi; `ModelCall` được lưu trong `run.json.split.calls`.
4. **RuleProfile (P2, `features.rule_profile`).** Cùng cách với template `rules.profile.v1`; thêm `holidays`, `default_rank_criterion`, `definitions`. Xác thực mỗi holiday bằng cách giải quyết cho mọi năm âm lịch calendar bao phủ; holiday không giải quyết được bị bỏ và ghi tên trong `unresolved`.

Test: round-trip rulebook nguyên văn (bằng byte sau NFC); span validation từ chối diễn đạt lại; fallback generic khi rulebook rỗng; calendar validator trên fixture có khoảng trống, ngày trùng, tháng nhuận.

### 7.2 C2 Ingestion & Catalog (M1 phụ trách)
```python
def setup_business(business_dir: Path, bkey: str, cfg: RunConfig) -> BusinessCatalog   # runs in setup pool
```

#### 7.2.1 Phát hiện dữ liệu
- File trực tiếp dưới thư mục doanh nghiệp (đệ quy thêm một cấp thư mục con), có extension `.csv`, `.tsv`, `.txt` (chỉ khi nhận diện delimiter thành công), `.xlsx`, `.xlsm`, `.xls` (qua calamine), `.sqlite`, `.sqlite3`, `.db`. Sắp theo đường dẫn tương đối (thứ tự byte) để thứ tự table tất định.
- Đọc nguyên văn `README.md` (không phân biệt hoa/thường) vào `readme_text`.
- Bỏ file lớn hơn `ingest.max_file_mb`, kèm `W_FILE_TOO_LARGE`.

#### 7.2.2 CSV
- Thứ tự phát hiện encoding: UTF-8-SIG → UTF-8 → phỏng đoán tốt nhất của `charset-normalizer` giới hạn trong {cp1258, utf-16, windows-1252} → latin-1 (kèm `W_ENCODING_FALLBACK`).
- Dialect: nhận diện delimiter trong `, ; \t |` trên 64 KB đầu; quote char `"`.
- Ban đầu đọc mọi ô thành chuỗi; xác định kiểu ở §7.2.5.

#### 7.2.3 Excel
- Đọc mọi sheet bằng `python-calamine`; chỉ dùng `openpyxl` nếu calamine thất bại trên file (`W_READER_FALLBACK`).
- Ô giữ kiểu gốc từ reader (number, datetime, string, bool). Ô có kiểu ngày được xem là ngày; ô số trong cột có gợi ý ngày được thử như Excel serial (§7.2.6).
- **Phát hiện table block:** block là dãy dòng liên tục tối đa, tách khỏi block khác bởi ≥ 2 dòng hoàn toàn trống **hoặc** một dòng header mới. Mỗi block thành một table.
- **Phát hiện header:** trong `max_header_scan_rows` dòng đầu của block, chọn dòng tối đa hóa `score = 0.5·text_ratio + 0.3·uniqueness + 0.2·type_consistency_below`, với `text_ratio` là tỷ lệ ô chuỗi không rỗng, `uniqueness` là tỷ lệ giá trị không rỗng phân biệt, `type_consistency_below` là tỷ lệ cột có 20 dòng tiếp theo nhất quán kiểu. Dòng phía trên header là dòng tiêu đề (ghi trong `TableInfo.dropped_rows` dưới dạng note). Nếu dòng ngay trên header chỉ có một phần ô được điền và header có ô trống, gộp hai dòng (`"<upper> <lower>"`). Hòa điểm chọn dòng sớm nhất.
- **Dòng tổng:** một dòng là dòng tổng nếu ô text không rỗng đầu tiên, sau fold, khớp `^(tong( cong)?|cong|total|grand total|sum|tong so)\b` **và** ít nhất một ô số bằng tổng cột đó trên các dòng trước trong block với sai số tối đa 0.5% (hoặc đó là dòng dữ liệu cuối block). Bỏ dòng tổng (`W_TOTAL_ROW_DROPPED`, kèm index dòng).
- **Dòng ghi chú:** bỏ các dòng cuối chỉ có đúng một ô text không rỗng như note.

#### 7.2.4 SQLite (SC-3)
- Mở bằng thư viện chuẩn Python: `sqlite3.connect("file:<path>?mode=ro&immutable=1", uri=True)` để không ghi gì vào `/data` (không journal hoặc WAL).
- Đọc mỗi user table và view (trừ `sqlite_%`) bằng `SELECT *`, nạp vào DuckDB qua Arrow. Giữ kiểu SQLite khai báo trong `format_note`; giá trị lưu dạng text đi qua cùng bước xác định kiểu như cột CSV.
- KHÔNG ĐƯỢC dùng extension `sqlite` của DuckDB (sẽ bị tải lúc runtime).

#### 7.2.5 Parse số
Áp dụng theo cột cho giá trị chuỗi. Null token (sau trim, case-fold): `""`, `na`, `n/a`, `null`, `none`, `nan`, `-`, `--`, `—`.
- Bỏ khoảng trắng và NBSP; bỏ token tiền tệ (`đ`, `₫`, `vnd`, `vnđ`, `dong`, `đồng`) và `%` cuối chuỗi (đặt `semantic_hint = percent`).
- Hậu tố độ lớn (không phân biệt hoa/thường, bỏ dấu): `k`, `nghin`, `ngan` = 10³; `tr`, `trieu` = 10⁶; `ty`, `ti` = 10⁹. Dạng ghép `<int><suffix><digits>` nghĩa là `<int>.<digits> × suffix` (ví dụ `1tr2` = 1,200,000; `2k5` = 2,500).
- **Chọn quy ước dấu phân cách theo cột** bằng đánh giá ba quy ước trên mọi giá trị — `VN` (`.` phân nghìn, `,` thập phân), `EN` (`,` phân nghìn, `.` thập phân), `PLAIN` (không phân nghìn, `.` thập phân) — và chọn tỷ lệ parse cao nhất; hòa thì xét số bằng chứng (giá trị chỉ parse được theo một quy ước), rồi thứ tự `VN`, `EN`, `PLAIN`. Cột còn hòa giữa quy ước có kết quả mâu thuẫn nhận `W_NUMERIC_AMBIGUOUS` và giữ `VARCHAR`.
- Cột thành numeric nếu parse rate ≥ `numeric_accept_rate`. Giá trị không parse được thành NULL **và** giữ cột gốc dưới dạng `<name>__raw VARCHAR`.
- Kiểu SQL đích: `BIGINT` nếu mọi giá trị parse được là số nguyên vừa int64; nếu không, `DECIMAL(38,6)` nếu mọi giá trị có ≤ 6 chữ số thập phân; còn lại `DOUBLE`. (SC-4: kiểu chính xác giữ tổng VND lớn chính xác.)

#### 7.2.6 Parse ngày
- Định dạng ứng viên: `yyyy-mm-dd`, `dd/mm/yyyy`, `mm/dd/yyyy`, `dd-mm-yyyy`, `dd.mm.yyyy`, `yyyy/mm/dd`, `dd/mm/yy`, `yyyy-mm`, `mm/yyyy`, mỗi dạng có thể kèm phần giờ; Excel serial 20000–80000 trong cột có header sau fold chứa `ngay`, `date`, `thoi gian`, `time`, `thang` hoặc `month`.
- Quyết định thứ tự ngày/tháng theo cột: giá trị có trường đầu > 12 bắt buộc ngày trước; có trường thứ hai > 12 bắt buộc tháng trước; bằng chứng xung đột → `W_DATE_AMBIGUOUS`, giữ `VARCHAR`; không bằng chứng → ngày trước (quy ước locale Việt Nam), kèm `W_DATE_ASSUMED_DMY`.
- Cột thành `DATE` (hoặc `TIMESTAMP` nếu có giờ khác nửa đêm) khi parse rate ≥ `date_accept_rate`; giữ cột raw như số. Cột chỉ tháng thành `DATE` ngày đầu tháng với `format_note = "month"`.

#### 7.2.7 Identifier (SC-2)
- Tên table: `<file_stem>` (CSV), `<file_stem>__<sheet>[_<block>]` (XLSX), `<file_stem>__<table>` (SQLite).
- Identifier cột/table được tạo bằng bỏ dấu (§7.6.1), chuyển chữ thường, thay ký tự không phải chữ/số bằng `_`, gộp ký tự lặp, trim `_`, thêm prefix `c_` nếu bắt đầu bằng chữ số, và suffix `_2`, `_3`… khi trùng, theo thứ tự nguồn.
- Luôn giữ header gốc trong `original_name`, hiển thị trong SchemaCard. **Không bao giờ fold hoặc sửa giá trị dữ liệu.**

#### 7.2.8 Profiling
Mỗi cột: tỷ lệ null, số giá trị phân biệt chính xác, min/max, và `top_values`: mọi giá trị kèm số đếm nếu distinct count ≤ `low_cardinality_max`, nếu không lấy `top_values_max` giá trị thường gặp nhất (hòa thì giá trị tăng dần). `semantic_hint` từ từ khóa header đã fold: `ma`, `code`, `id` → code; `ten`, `name` → name; `trang thai`, `status` → status; `gia`, `tien`, `doanh thu`, `amount`, `price`, `cost` → money; `so luong`, `sl`, `qty`, `quantity` → quantity.
- **Candidate key:** cột đơn có distinct count = row count và không null; chỉ xét khóa hai cột với table ≤ 50 cột.
- **Join:** với cặp cột khác table, kiểu tương thích, tên sau fold khớp (chính xác, hoặc một tên bằng tên kia thêm/bớt token tên table) **hoặc** mức chứa giá trị ≥ 0.95 trong candidate key: ghi `JoinEdge` với `match_rate` = tỷ lệ giá trị trái không null tìm thấy bên phải. Chỉ giữ edge có `match_rate ≥ 0.90`.
- **Độ phủ ngày:** `date_columns` cho mọi cột DATE/TIMESTAMP; `data_range` = hợp dải ngày trên table không phải dimension ít giá trị (row count > 200 hoặc có cột money/quantity).

#### 7.2.9 SchemaCard
Plain text tất định, theo thứ tự table, rồi join, độ phủ ngày, cảnh báo. Định dạng:
```
TABLE orders  (12,345 rows; source orders.xlsx › "Đơn hàng")
  order_id     BIGINT        key  nulls 0%     1..12345              ["Mã đơn"]
  status       VARCHAR             nulls 0%     values: "Hoàn thành"(9800), "Đã hủy"(1200), "Trả hàng"(345)
  amount       BIGINT              nulls 0.2%   0..48500000   money   ["Thành tiền"]
JOIN orders.customer_id → customers.customer_id  (n:1, 99.8%)
DATES orders.order_date 2024-01-01..2025-06-30
WARN W_TOTAL_ROW_DROPPED orders row 12346
```
- Giới hạn bằng tokenizer model ở `schema_card_budget_tokens`. Thứ tự giảm khi vượt: (1) cắt top value cột cardinality cao còn 10; (2) rồi còn 5; (3) chế độ `relevant-subset` lúc xử lý câu (§7.7.1). Luôn lưu card đầy đủ trong business log.
- Định dạng SchemaCard là **contract mà consumer nhìn thấy**, dành cho M3 (prompt) và M2 (catalog check). Đổi định dạng cần consumer test pass (§14.4) và ghi chú trong merge request.

#### 7.2.10 Materialization
- Tạo `/tmp/datamate/biz/<bkey>/catalog.duckdb` bằng `duckdb.connect(path, config={"threads": concurrency.setup_threads_per_business, "autoinstall_known_extensions": false, "autoload_known_extensions": false})`, nạp table qua Arrow, tạo view (P2), `CHECKPOINT`, đóng. Sau đó chỉ C8 mở file read-only.
- Setup doanh nghiệp thất bại (exception chưa bắt) → `status = failed`, mọi câu doanh nghiệp đó abstain với `E_BUSINESS_SETUP`.

Test: fixture cho mọi quy tắc trên (dòng tiêu đề, header gộp, hai block mỗi sheet, tổng, note, `1.250.000`, `1,5`, `150k`, `1tr2`, `12,5%`, ngày mơ hồ `01/02/2025`, Excel serial, CSV cp1258, SQLite WAL-mode trên filesystem read-only); tính idempotent (hai setup tạo SchemaCard giống từng byte); ngân sách: XLSX 300k dòng ≤ 60 giây trên nhóm CPU tham chiếu.

### 7.3 C3 Semantic Compiler (P2, `features.compiled_views`, M1 phụ trách)
```python
async def compile_semantics(cat: BusinessCatalog, split: SplitContext, client: ModelClient, replica: int) -> SemanticAnnotations
```
- Một model call (template `semantics.compile.v1`) với rulebook, README, SchemaCard; schema output: vai trò table, ngữ nghĩa giá trị và tối đa 8 đề xuất `ViewSpec` cho định nghĩa cốt lõi rulebook.
- Mỗi view: DDL chỉ được là `CREATE VIEW v_<name> AS SELECT …`; tạo trong kết nối setup; kiểm tra validation — chạy không lỗi; không rỗng; không trùng giá trị trong cột key khai báo; với view tiền, `SUM(view) ≤ SUM(source)` khi quy tắc hàm ý loại trừ. View thất bại bị loại (`enabled = false`, giữ trong log).
- Cung cấp view cho solver cùng DDL và mục đích. Kill switch theo category: `features.compiled_views_categories` (list) CÓ THỂ giới hạn sử dụng.
- Mọi compile call vào business log; log từng câu tham chiếu view qua `views_used` với DDL hash.

### 7.4 C4 Question Parser (M3 phụ trách)
```python
async def parse_question(q: Question, split: SplitContext, cat: BusinessCatalog, client: ModelClient, replica: int) -> tuple[QuestionFrame | None, ModelCall]
```
- **Chuẩn hóa:** `normalized_question` = bản gốc được mở rộng viết tắt từ `lexicon/abbrev_vi.tsv` (theo token, đối sánh trên token chữ thường đã fold, chỉ nguyên token). Gửi cả văn bản gốc và chuẩn hóa; bản gốc là chuẩn.
- **Call:** template `parse.frame.v1`, JSON Schema = schema `QuestionFrame` đã export, `max_tokens` từ `decoding.stages.parse`. Context: rulebook, SchemaCard (cho phép subset), `as_of_date`, câu hỏi.
- **Validation:** pydantic validation và invariant §5.9. Output không hợp lệ → **không retry** trong P1; câu hỏi abstain với `E_PARSE_INVALID`.

### 7.5 C5 Temporal Resolver (M2 phụ trách)
```python
def resolve_windows(frame: QuestionFrame, as_of: date, params: TemporalParams,
                    calendar: LunarCalendar | None, data_range: DateRange | None) -> list[TimeWindow]
```
Pure function; không I/O; không model call. Quy tắc giải quyết (`a` = `as_of_date`):

| `kind` | Quy tắc |
|---|---|
| `date` | `[d, d]`, độ chi tiết `day` |
| `date_range` | `[start, end]`; thiếu năm → áp dụng `year_omitted_policy` cho `start`, `end` cùng năm (năm sau nếu end < start) |
| `calendar_period` | Kỳ xác định bằng unit/index/year; `year = null` → năm gần nhất có đầu kỳ ≤ `a`; `unit = week` dùng `week_start` và số tuần ISO |
| `relative_period` | Gọi P₀ là kỳ của `unit` chứa `a` (tuần theo `week_start`). Pₖ = P₀ dịch `offset`. Nếu `offset = 0` và `to_date`: end = `a` (hoặc `a − 1` nếu `to_date_end = day_before_as_of`). Nếu `offset = 0` và không `to_date`: toàn bộ P₀, gắn `F_WINDOW_EXTENDS_PAST_AS_OF` nếu end > `a`. Nếu `offset < 0`: toàn bộ Pₖ |
| `rolling` | end = `a` nếu `rolling_includes_as_of`, nếu không `a − 1`; `day`: start = end − (count − 1); `week`: start = end − (7·count − 1); `month`: start = (end − count tháng) + 1 ngày, kẹp ngày trong tháng (clamping) |
| `same_period_prior_year` | Dịch window được tham chiếu −1 năm; `calendar_dates`: cùng tháng/ngày, 29/2 → 28/2; `elapsed_days`: cùng độ dài, kết thúc ở end đã dịch |
| `all_time` | `data_range` nếu biết (độ chi tiết `range`); nếu không, không window và gắn `F_NO_DATA_RANGE` |
| `lunar_holiday` (P2) | Năm âm = năm âm của `a` + `year_offset`; anchor = `to_solar(anchor)`; window = `[anchor + start_offset, anchor + end_offset]` từ `HolidayWindow` khớp. Không khớp hoặc `calendar_ok = false` → `E_TIME_UNSUPPORTED` |
| `lunar_date_range` (P2) | Đổi start/end âm bằng `to_solar`; chỉ dùng tháng nhuận nếu rulebook nêu |
| `unsupported` | `E_TIME_UNSUPPORTED` |

- `coverage_ratio` = |window ∩ data_range| / |window|, tính theo ngày.
- Trong P1, mọi `E_TIME_UNSUPPORTED` làm câu hỏi abstain (AP §7.1).
- Provenance liệt kê mọi trường `TemporalParams` đã dùng và nguồn của nó.

Test: ca theo bảng cho mỗi dòng, qua ranh giới năm, năm nhuận, tuần bắt đầu thứ Hai/Chủ nhật, cả hai giá trị `to_date_end`, Tết trải qua hai năm dương lịch (P2); thêm property test: `start ≤ end` và độ dài window khớp quy tắc trên 10.000 cặp `(a, expr)` ngẫu nhiên.

### 7.6 C6 Entity Linker (P2, `features.entity_linker`, M1 phụ trách)
#### 7.6.1 Hàm fold (dùng chung, trong `lexicon/fold.py`)
`fold(s)` = NFD → bỏ dấu kết hợp (U+0300–U+036F) → ánh xạ `đ/Đ` → `d` → chữ thường → thay ký tự không phải chữ/số bằng khoảng trắng → gộp khoảng trắng. **Chỉ** dùng cho retrieval key, SQL identifier (SC-2), đối sánh từ khóa. Không áp dụng cho giá trị output hoặc input scorer (DEC-11). `fold()` thuộc public API của `lexicon`, được M1, M2, M3 dùng; hành vi đóng băng tại I0, thay đổi theo §15 như contract.

#### 7.6.2 Index và query
- Index: mỗi cột `VARCHAR` có `semantic_hint` thuộc {name, code, status} hoặc distinct count ≤ 100.000: map `fold(value)` → (table, column, value, code), với `code` là giá trị cột code cùng dòng nếu có cột code 1:1.
- Query từng mention: lấy ứng viên exact folded match, rồi `rapidfuzz.fuzz.token_set_ratio` và `partial_ratio` (score = max) với giá trị đã fold; giữ score ≥ `weak_threshold`, top `top_k`, hòa thì (table, column, value) tăng dần.
- `strength = strong` nếu score ≥ `strong_threshold`.

### 7.7 C7 Solver (M3 phụ trách)
```python
async def solve(q: Question, frame: QuestionFrame, windows: list[TimeWindow],
                cands: list[EntityCandidate], cat: BusinessCatalog, sem: SemanticAnnotations | None,
                split: SplitContext, client: ModelClient, executor: Executor,
                replica: int, deadline: Deadline) -> list[SolverAttempt]
```

#### 7.7.1 Context pack (thứ tự cố định để tái sử dụng prefix cache)
| # | Phần | Dùng chung trong | Quy tắc ngân sách |
|---|---|---|---|
| 1 | System instruction (template) | Lần chạy | Cố định |
| 2 | Rulebook (nguyên văn) | Lần chạy | Không cắt ngắn |
| 3 | README | Doanh nghiệp | ≤ `readme_budget_tokens`, head-truncated kèm dấu hiệu cắt |
| 4 | SchemaCard | Doanh nghiệp | ≤ `schema_card_budget_tokens` |
| 5 | View đã xác thực (P2) | Doanh nghiệp | DDL đầy đủ |
| 6 | Ví dụ few-shot | Câu hỏi | `fewshot_k`, bỏ từ cuối khi vượt ngân sách |
| 7 | Khối câu hỏi: câu gốc + chuẩn hóa, `as_of_date`, JSON QuestionFrame, window đã giải quyết dưới dạng ngày literal, entity candidate, type contract và quy tắc SQL cho type kỳ vọng | Câu hỏi | — |

- Phần 1–5 render giống nhau cho mọi câu của doanh nghiệp (từng byte) để prefix cache server có tác dụng.
- Tổng PHẢI ≤ `context_budget_tokens`. Thứ tự giảm: few-shot → README → SchemaCard chế độ relevant-subset (xếp table theo độ giao token đã fold với câu hỏi, metric, mention; đủ danh sách cột của 4 table đầu, còn lại chỉ tên). Vẫn vượt → `E_CONTEXT_OVERFLOW` (abstain).
- Đếm token bằng tokenizer model tải từ `model.path` với `local_files_only=True`.

#### 7.7.2 Kho few-shot
- File: `/code/src/datamate/assets/fewshot.jsonl`, dựng bởi `training_code/data_generation/build_fewshot.py` từ **chỉ training split** (§13.2). Entry: `{entry_id, source_business_id, question, frame, sql, expected_type, schema_excerpt}`.
- Lựa chọn: score = `token_set_ratio(fold(question + metric_text), fold(entry.question + entry.metric))`, cộng 10 nếu cùng `expected_type`; top `fewshot_k`, hòa theo `entry_id`.
- Trong cross-validation, PHẢI loại entry có `source_business_id` thuộc fold đang đánh giá (leakage guard, có test).

#### 7.7.3 Output model và quy tắc SQL
Template `solve.sql.v1`; JSON Schema `SolverOutput`. Quy tắc nêu trong prompt **và** thực thi bởi `check_sql` trước khi chạy:

| Quy tắc | Thực thi | Vi phạm |
|---|---|---|
| Đúng một statement, type SELECT (gồm `WITH`) | `extract_statements` của `duckdb` → một statement type SELECT | `E_SQL_NOT_SELECT` |
| Chỉ table catalog và view đã xác thực | Chạy trên DB read-only, tắt truy cập ngoài (§7.8) | `E_SQL_EXEC` |
| Shape scalar: 1 dòng × 1 cột (`value` hoặc `answer_column`) | Contract check | `E_TYPE_CONTRACT` |
| Shape list: cột `item`, `sort_key`, `tie_code` | Contract check | `E_TYPE_CONTRACT` |
| Shape table: ≥ 1 cột; tên theo quy ước (§7.10) | Contract check | `E_TYPE_CONTRACT` |
| `LIMIT` yêu cầu `ORDER BY` | Kiểm tra token ngoài string literal | `E_SQL_NONDETERMINISTIC` |
| Giá trị percent theo đơn vị phần trăm | Prompt + kiểm tra hợp lý của verifier | Cờ `F_PERCENT_SCALE` nếu mọi \|v\| ≤ 1.5 |
| Ngày cấp tháng là `DATE` (đầu tháng) hoặc text `'yyyy-mm'` | Contract check | `E_TYPE_CONTRACT` |

#### 7.7.4 Vòng lặp attempt
```
attempt 1: solve (stage=solve)
while not ok and repairs < max_repairs and not deadline.soft_expired and not degrade:
    repair (stage=repair): conversation = [context, question, previous assistant output,
                                            user message with the error code and error_text or contract violation]
P2: if still not ok, or frame.needs_procedural and python_fallback:
    fallback (stage=fallback, template solve.python.v1) + at most 1 fallback_repair
```
- `ok` = output model hợp lệ **và** thực thi thành công **và** contract check pass **và** kết quả không rỗng.
- Hội thoại repair tái dùng nguyên văn phần 1–7, append lượt hội thoại, nên prefix còn cache.
- Mỗi attempt là `SolverAttempt`; tất cả được truyền cho C9, log theo thứ tự.

#### 7.7.5 Kết quả → TypedValue (`to_typed_value`)
| Type kỳ vọng | Quy tắc |
|---|---|
| `number` | Một ô → `Decimal`; NULL → kết quả rỗng |
| `percent` | Một ô → `Decimal` (đã là đơn vị phần trăm) |
| `string` | Một ô → `str` đúng như lưu trữ |
| `date` | `DATE` → giá trị; text `'yyyy-mm'` → ngày đầu tháng với độ chi tiết `month`; độ chi tiết từ `frame.date_granularity` |
| `boolean` | Một ô BOOLEAN, hoặc integer 0/1 → bool |
| `list` | Dòng → `{item, sort_key, tie_code}` |
| `table` | Cột và dòng như trả về |

### 7.8 C8 Sandbox Executor (M3 phụ trách)
- Worker pool tùy chỉnh gồm `sandbox_workers` process (`multiprocessing`, spawn). Mỗi worker đặt `RLIMIT_AS = memory_limit_mb + 2048 MB`, làm việc trong `/tmp/datamate/sandbox/<pid>/`, cache một kết nối read-only cho mỗi `db_path`:
  ```python
  duckdb.connect(db_path, read_only=True, config={
      "threads": 1, "memory_limit": f"{memory_limit_mb}MB",
      "enable_external_access": False,
      "autoinstall_known_extensions": False, "autoload_known_extensions": False})
  # then: SET lock_configuration = true
  ```
- Fetch bằng `fetchmany(max_result_rows + 1)`.
- Mã hóa giá trị gửi parent: JSON có tag (§5.7). Chuyển `DOUBLE` bằng `Decimal(repr(x))`; `DECIMAL` giữ `Decimal`; ngày thành chuỗi ISO. Encoder nằm ở `sandbox/encode.py`, dùng chung với `FakeExecutor`, để cả hai cho kết quả giống hệt.
- **Timeout:** parent đợi `sql_timeout_s`; hết hạn thì `SIGKILL` worker, spawn thay thế, trả `E_SQL_TIMEOUT`. Worker crash trả `E_EXEC_CRASH` và được thay mới.
- **Python fallback (P2):** code PHẢI định nghĩa `def solve(con):`; thực thi bằng `exec` trong namespace mới có `__import__` chỉ cho phép `math, statistics, datetime, decimal, fractions, collections, itertools, functools, operator, re, json, pandas, numpy`. `open`, `eval`, `exec`, `compile`, `input` và `__import__` module khác phải raise. Giá trị trả về: scalar, list, `pandas.DataFrame` hoặc `pandas.Series`, chuyển thành dòng `ExecutionResult`. Đây là ranh giới cô lập lỗi, không phải ranh giới bảo mật.
- `ExecutionResult.code` là đúng text đã chạy; đặt `helper_call` khi mã là lời gọi helper đóng gói (DG §3.3).

Test: recursive CTE vô hạn bị dừng khi timeout; cross join 100 GB bị giới hạn bộ nhớ từ chối; từ chối `COPY … TO` và `read_csv('/etc/passwd')`; từ chối `ATTACH`; 16 worker truy cập read-only đồng thời một DB file; round-trip Decimal chính xác cho tổng cỡ 10¹⁴.

### 7.9 C9 Verifier & Decision (M2 phụ trách)
```python
def decide(q: Question, frame: QuestionFrame | None, windows: list[TimeWindow],
           attempts: list[SolverAttempt], cat: BusinessCatalog, cfg: RunConfig,
           pipeline_error: ReasonCode | None) -> Decision
```
**Rule gate (P1, `decision.policy = rule_gate`)** — xét theo thứ tự; quy tắc khớp đầu tiên quyết định:

| # | Điều kiện | Quyết định | Reason code |
|---|---|---|---|
| 1 | Có `pipeline_error` (input, setup, parse, time, context, deadline, internal) | abstain | Code đó |
| 2 | `frame.answerability.status = missing_field` **và** mọi trường được nêu đều không vượt catalog check bên dưới | `unanswerable` (`reason = "missing_field:<f1>[,<f2>]"`) | `D_UNANSWERABLE_CONFIRMED` |
| 3 | Không attempt nào có `ok = true` | abstain | Mã lỗi attempt cuối, nếu không có thì `E_NO_SUCCESS` |
| 4 | Kết quả attempt cuối chuyển thành `TypedValue` có type ≠ `frame.expected_type` | abstain | `E_TYPE_CONTRACT` |
| 5 | Có primary window với `coverage_ratio = 0` và `decision.abstain_on_zero_coverage` | abstain | `D_OUT_OF_RANGE` |
| 6 | Giá trị NaN/Infinity hoặc percent có \|v\| > 100.000 | abstain | `D_IMPLAUSIBLE` |
| 7 | Còn lại | Trả lời | `D_ANSWER` |

- **Catalog check cho trường thiếu:** trường là *vắng mặt* nếu `max(token_set_ratio(fold(field), fold(name)))` trên mọi giá trị `name`, `original_name`, `semantic_hint` của cột < 60, và không dòng README nào chứa tên trường đã fold như substring. Nếu check này tìm thấy trường, không tin hint của model (quy tắc 2 không kích hoạt).
- `features` luôn ghi: `n_attempts`, `n_repairs`, `used_fallback`, `row_count`, `min_coverage`, `temporal_generic_params`, `span_mismatch`, `percent_scale_flag`, `degrade`.
- **Feature verifier P2** (`features.verifier_features`) thêm z-score độ lớn so với miền cột, strength entity và cờ window; trong P2 chỉ ghi lại chúng.
- **Calibrator P3** (`decision.policy = calibrator`): `p_correct = model(features)`; trả lời khi và chỉ khi `p_correct ≥ threshold`; vẫn áp dụng quy tắc 1–6 trước.

### 7.10 C10 Formatter (M2 phụ trách)
```python
def to_submission(q_id: str, d: Decision, cfg: RunConfig) -> SubmissionRecord
```
| Type | Wire value |
|---|---|
| `number` | `Decimal.quantize(Decimal("0.01"), rounding=cfg.formatting.rounding)`; `-0` → `0`; nếu là số nguyên và `integer_literal_when_integral` → JSON integer, nếu không JSON number bỏ số 0 cuối (`12.50` → `12.5`). **[VERIFY chế độ làm tròn và xử lý int/float, Q5]** |
| `percent` | Như number; giá trị đã theo đơn vị phần trăm |
| `string` | Giá trị lưu trữ, trim khoảng trắng đầu/cuối, còn lại giữ nguyên (NFC) |
| `date` | `yyyy-mm-dd` (độ chi tiết `day`) hoặc `yyyy-mm` (độ chi tiết `month`) |
| `boolean` | JSON `true` / `false` **[VERIFY]** |
| `list` | Sắp theo `sort_key` (giảm dần cho `top`, tăng dần cho `bottom`), rồi `tie_code` tăng dần theo `tie_code_order`, rồi `item`; cắt tại `k` (lấy tất cả nếu ít hơn); xuất JSON array các giá trị `item`. **[VERIFY wire shape với Brief §2.2]** |
| `table` | `{"columns": [...], "rows": [[...], ...]}` với ô số định dạng như `number`. Tên cột theo quy ước tham chiếu training do M2 ghi trong `formatting/table_conventions.md`. **[VERIFY wire shape với Brief §2.2]** |
| `unanswerable` | `{"id", "type": "unanswerable", "reason"}` |
| `abstain` | `{"id", "type": "abstain"}` |

- Serialization dùng encoder tùy chỉnh ghi `Decimal` thành JSON number literal (không chuỗi, không qua float), `ensure_ascii=False`, separator `(",", ":")`, thứ tự key `id, type, answer|reason`.
- **Oracle độc lập.** Formatter (M2) và scorer (Lead, §7.14) do hai người khác nhau viết, cả hai PHẢI vượt golden test chung trong `tests/golden/`. Đổi golden test cần cả hai người phụ trách duyệt.

### 7.11 C11 Persistence & Compliance Logging (M4 phụ trách)
- Một writer task duy nhất nhận cặp `(SubmissionRecord, LogRecord)` từ asyncio queue.
- Mỗi cặp: append dòng log vào `questions.jsonl`, `flush`, `os.fsync`; rồi append dòng submission vào `submission.jsonl`, `flush`, `os.fsync`. (Thứ tự đảm bảo không có đáp án mà thiếu log record.)
- Từ chối record thứ hai cho ID đã ghi (`E_DUPLICATE_WRITE`, log trong `run.json`).
- Mở file append lúc bắt đầu. Production kỳ vọng thư mục result rỗng; nếu đã có `submission.jsonl`, đổi tên thành `submission.jsonl.prev-<n>` trước khi chạy (không xóa). Resume mode chỉ có trong dev harness.
- Định dạng: §8.

### 7.12 C12 Orchestrator (M4 phụ trách)
1. **Nhóm và thứ tự.** Nhóm câu theo `business_id`; sắp doanh nghiệp theo (số câu giảm dần, `business_id` tăng dần); câu trong doanh nghiệp theo `line_no`.
2. **Gán replica.** Theo thứ tự đó, gán mỗi doanh nghiệp cho replica có tổng số câu được gán nhỏ hơn (hòa → index thấp hơn). Tính phân công trước khi bắt đầu công việc và ghi log.
3. **Setup.** Gửi setup doanh nghiệp vào setup pool theo cùng thứ tự. Đưa câu của doanh nghiệp vào replica queue khi catalog `ready` và split context sẵn sàng.
4. **Worker.** Mỗi replica có `questions_per_replica` worker coroutine lấy việc từ queue. `elapsed_ms` bắt đầu khi worker lấy câu (câu vào batch), kết thúc khi giao record cho writer.
5. **Pipeline từng câu:** normalize → C4 → C5 → (P2) C6 → C7/C8 → C9 → C10 → C11. Bắt mọi exception tại ranh giới câu → abstain `E_INTERNAL`, traceback trong `run.json.errors` (100 đầu).
6. **Deadline.** Soft (`question_soft_s`): không bắt đầu repair hoặc fallback mới. Hard (`question_hard_s`): hủy task câu hỏi → abstain `E_DEADLINE`.
7. **Degrade mode.** Mỗi `progress_interval_s`, thời điểm hoàn thành dự kiến = thời gian đã qua + số câu còn lại × thời gian throughput trung bình mỗi câu gần đây. Nếu dự kiến > `degrade_if_projected_finish_s`, bật degrade (không repair, fallback, P3) cho phần còn lại; ghi thời điểm kích hoạt. Đây là biện pháp dự phòng, kỳ vọng không kích hoạt trên phần cứng tham chiếu.
8. **Global stop.** Tại `T0 + global_hard_stop_s`, hủy mọi công việc, ghi `abstain` (`E_GLOBAL_STOP`) cho mọi ID chưa ghi, finalization.
9. **SIGTERM:** giống global stop, thực hiện ngay.
10. **Replica lỗi:** thử restart một lần; trong lúc dừng, chuyển queue sang replica còn lại. Log sự kiện.
11. **Stub mode (chỉ dev).** Với `--dev --stub <stage>`, pipeline dùng đối tượng thay thế cho stage (§5.10), giúp Lead tích hợp từng stage (TASKS L-05).

### 7.13 C13 Model Serving (M4 phụ trách replica; M3 phụ trách client)
#### 7.13.1 Khởi động replica
Với replica `i` (`0 ≤ i < model.replicas`):
```
CUDA_VISIBLE_DEVICES=i  python3 -m vllm.entrypoints.openai.api_server \
  --model <model.path> --served-model-name <served_name> --dtype <dtype> \
  --max-model-len <max_model_len> --gpu-memory-utilization <gpu_memory_utilization> \
  --max-num-seqs <max_num_seqs> --seed <decoding.seed> \
  --host 127.0.0.1 --port <base_port + i> \
  [--enable-prefix-caching] [--reasoning-parser <reasoning_parser>] [--quantization <q>] \
  --generation-config vllm  <extra_server_args...>
```
- `--generation-config vllm` ngăn `generation_config.json` của checkpoint thay đổi sampling default. PHẢI kiểm tra lại tên flag theo phiên bản vLLM chốt ở DEC-3 **[VERIFY]**; checkpoint multimodal thêm flag tắt input ảnh/video cho phiên bản đó.
- Stdout/stderr server vào `/result/logs/replica-<i>.log`.
- Readiness: poll `GET /health` đến 200 hoặc `startup_timeout_s`; rồi một warm-up request (prompt cố định, `max_tokens = 8`). Ghi thời gian load từng replica trong `run.json`.
- Dự phòng TP (DEC-13): `replicas = 1`, `tensor_parallel_size = 2`, `CUDA_VISIBLE_DEVICES=0,1`, cùng thiết lập NCCL DG §9.

#### 7.13.2 Client request
`POST /v1/chat/completions` với: `model`, `messages`, `temperature`, `top_p`, `max_tokens`, `seed`, `n = 1`, `response_format = {"type": "json_schema", "json_schema": {"name": <template_id>, "schema": <schema>, "strict": true}}` khi có schema, và `chat_template_kwargs = {"enable_thinking": <bool>}`. Gửi tường minh mọi tham số trên mọi call.
- Lỗi transport: retry một lần với request giống hệt. Timeout (`model_call_timeout_s`): không retry; `ModelCall.error = "E_MODEL_TIMEOUT"`.
- `request_sha256` = SHA-256 của JSON chuẩn request body.
- Client trả `content` và `reasoning_content` đúng như nhận được.

#### 7.13.3 Fallback in-process
Nếu không có loopback serving, engine `AsyncLLM` với engine argument giống hệt triển khai cùng protocol `ModelClient`. Chọn bằng `model.serving = "inprocess"` (mặc định `"http"`). PHẢI vượt conformance test `ModelClient`.

#### 7.13.4 Tokenizer
Tải một lần mỗi process từ `model.path` (`local_files_only=True`) để đếm ngân sách bằng chat template của model.

#### 7.13.5 Prompt template
- Lưu tại `datamate/prompts/<template_id>.j2` (Jinja2), render với `StrictUndefined`.
- ID (P1): `rules.temporal.v1`, `parse.frame.v1`, `solve.sql.v1`, `repair.sql.v1`. (P2): `rules.profile.v1`, `semantics.compile.v1`, `solve.python.v1`, `repair.python.v1`.
- Mọi đổi câu chữ tạo suffix phiên bản mới; SHA-256 mỗi template được ghi trong `run.json`. Template KHÔNG ĐƯỢC chứa nội dung đặc thù doanh nghiệp hoặc câu hỏi.
- Template do component thành viên khác dùng (`rules.*` cho M2, `semantics.*` cho M1) do M3 phụ trách render và versioning; nội dung đồng tác giả với thành viên sử dụng, người này phải duyệt đổi câu chữ.
- Đổi phiên bản template PHẢI cập nhật fixture `ModelCall` phụ thuộc trong cùng merge (TASKS M3-13); nếu không, `ReplayModelClient` trả `E_REPLAY_MISS` và CI thất bại.

### 7.14 C14 Evaluation Harness (Lead phụ trách)
- `score_one(pred: SubmissionRecord | None, ref: ReferenceRecord) -> Literal[1, 0, -1]` triển khai chính xác Brief §2.1–2.2; `PA = Σ score / N`.
- Entry point: `python -m datamate.eval.harness --config <file> --data-dir <split> --answers <answers.jsonl> --out <dir> [--fold k] [--resume] [--dev --set key=value ...]`. Gọi cùng `datamate.run.main` như production.
- Fold: sắp doanh nghiệp theo `sha256(business_id)`, fold = rank mod 5 (chỉ dev). Leave-type-out dùng `eval/business_types.json` (nhãn thủ công, Lead, M0).
- Báo cáo: PA, accuracy trên câu đã trả lời, coverage, precision/recall `unanswerable`, theo type, reason code, component phát sinh reason code, category nếu dữ liệu training cung cấp **[VERIFY]**, latency p50/p95, dự báo runtime cho 500 và 1.000 câu.
- **Run record** (`<out>/run_record.json`): config và override, git commit, phiên bản contract, template hash, fingerprint môi trường (tên GPU, driver, CUDA, torch, vLLM, DuckDB, Python, lock hash), hash snapshot dữ liệu, revision model, kết quả từng câu, thời gian.
- **Khả năng so sánh.** `compare_runs(a, b)` báo dòng giống nhau, dòng thay đổi và ΔPA. Từ chối so sánh run khác fingerprint môi trường, hash snapshot dữ liệu hoặc revision model trừ khi có `--allow-env-diff`, đồng thời in những điểm khác.

---

## 8. Định dạng file output

### 8.1 Chung
UTF-8, mỗi dòng một JSON object, kết thúc bằng `\n`, `ensure_ascii=False`, separator gọn. Thứ tự trường như liệt kê.

### 8.2 `submission.jsonl` [REQ DG §3.2]
Xem §5.8 và §7.10.

### 8.3 `logs/questions.jsonl` [REQ DG §3.3]
| Trường | Yêu cầu bởi | Nội dung |
|---|---|---|
| `id` | DG | ID câu hỏi |
| `answer` | DG | Submission object bỏ `id`: `{"type", "answer"}`, `{"type": "unanswerable", "reason"}`, hoặc `{"type": "abstain"}` |
| `elapsed_ms` | DG | Int không âm (§7.12 bước 4) |
| `thinking` | DG | `null` nếu không call nào trả reasoning; nếu có, list một entry mỗi model call **theo thứ tự call**, mỗi entry là chính xác `reasoning_content`, hoặc `""` nếu call không trả reasoning (SC-7) |
| `code` | DG (khi thực thi) | `null` nếu không thực thi; chuỗi nếu một lần thực thi; nếu nhiều, list text thực thi chính xác theo thứ tự |
| `output` | DG (khi thực thi) | Output thực thi của attempt tạo đáp án (nếu không, attempt cuối): `{"columns", "rows" (≤ max_output_rows_logged), "row_count", "truncated"}` hoặc error text |
| `inputs` | DG (helper) | Đối số helper thực tế, khi có `helper_call` |
| `contracts_version` | SPEC | |
| `business_id` | SPEC | Chỉ kiểm toán |
| `calls` | SPEC | List `ModelCall` (mọi trường, gồm `content`) theo thứ tự call |
| `attempts` | SPEC | `[{attempt_no, stage, language, ok, error_code, duration_ms}]` |
| `windows` | SPEC | List `TimeWindow` |
| `decision` | SPEC | `{kind, reason_code, features, p_correct}` |
| `views_used` | SPEC (P2) | `[{name, ddl_sha256}]` |
| `degrade` | SPEC | bool |

### 8.4 `logs/businesses.jsonl`
`{business_id, bkey, status, setup_ms, warnings, tables (TableInfo list), joins, data_range, schema_card, schema_card_sha256, views (P2), compile_calls (P2, full ModelCall list)}`.

### 8.5 `logs/run.json`
`{contracts_version, config (effective), config_sha256, template_sha256: {id: sha}, model: {path, revision, weights_sha256_index}, environment, replica_assignment, timings: {replica_load_ms[], first_answer_ms, total_ms}, split: {rulebook_sha256, temporal_params, rule_profile, calls}, counts: {questions, distinct_ids, answered, unanswerable, abstained, by_reason}, degrade_activated_ms, errors: [...]}`. Ghi khi finalization; ghi lại bản tạm theo cách atomic (file tạm + rename) mỗi `progress_interval_s`.

---

## 9. Yêu cầu determinism

| ID | Yêu cầu | Xác minh bằng |
|---|---|---|
| D1 | Greedy decoding: `temperature = 0`, `top_p = 1`, `seed` cố định, `max_tokens` cố định, `enable_thinking` tường minh trên mọi call | Unit test client assert mọi request body |
| D2 | Concurrency cố định (`questions_per_replica`, `max_num_seqs`) và gán replica cố định (§7.12) | Review config; log và so sánh phân công giữa run |
| D3 | Context phần 1–5 giống từng byte trong cùng doanh nghiệp | Test render hai lần, so byte |
| D4 | Mọi vòng lặp set/dict ảnh hưởng output đều theo key đã sắp xếp | Checklist code review; `PYTHONHASHSEED=0` |
| D5 | Ingestion và SchemaCard là pure function của file input | Test idempotent (§7.2) |
| D6 | Thực thi DuckDB query với `threads = 1`; kiểu số chính xác (BIGINT/DECIMAL) | Test C8 |
| D7 | `LIMIT` chỉ khi có `ORDER BY`; formatter sắp lại list tất định | Test §7.7.3, §7.10 |
| D8 | Không logic phụ thuộc wall-clock trừ deadline, degrade mode, global stop; ghi log khi kích hoạt | Code review; run.json |
| D9 | Pin thư viện bằng lock; pin revision model; hash snapshot dữ liệu | Fingerprint môi trường run record |
| D10 | `VLLM_BATCH_INVARIANT` theo kết quả DEC-3 | G4 |
| D11 | Lựa chọn few-shot và xếp hạng entity có thứ tự toàn phần (tie-break tường minh) | Unit test |
| D12 | Nghiệm thu: hai run cùng host cho `submission.jsonl` giống hệt (mục tiêu) hoặc \|ΔPA\| ≤ 0.005 (gate G4/G7) | `compare_runs` |
| D13 | CPU determinism CI: hai run trên fixture với `ReplayModelClient` tạo `submission.jsonl` giống từng byte và `questions.jsonl` giống nhau sau bỏ trường thời gian | §14.5, mỗi merge |

---

## 10. Xử lý lỗi

### 10.1 Chính sách
Lỗi không lan qua ranh giới câu hỏi hoặc doanh nghiệp. Mọi thất bại ánh xạ thành reason code; câu hỏi nhận `abstain` trừ khi áp dụng quy tắc 2 tại §7.9. Cảnh báo không trực tiếp đổi quyết định; được ghi lại và CÓ THỂ làm feature verifier.

### 10.2 Reason code
| Code | Phát sinh bởi | Ý nghĩa |
|---|---|---|
| `D_ANSWER` | C9 | Đã xuất đáp án |
| `D_UNANSWERABLE_CONFIRMED` | C9 | Xác nhận thiếu trường |
| `D_OUT_OF_RANGE` | C9 | Window ngoài độ phủ dữ liệu |
| `D_IMPLAUSIBLE` | C9 | Giá trị không hữu hạn hoặc không hợp lý |
| `E_INPUT_AS_OF`, `E_INPUT_BUSINESS_MISSING` | 7.0 | Trường input không hợp lệ |
| `E_BUSINESS_SETUP` | C2/C3 | Setup doanh nghiệp thất bại |
| `E_PARSE_INVALID` | C4 | QuestionFrame không hợp lệ |
| `E_TIME_UNSUPPORTED` | C5 | Không giải quyết được biểu thức |
| `E_CONTEXT_OVERFLOW` | C7 | Context pack vượt ngân sách |
| `E_MODEL_TIMEOUT`, `E_MODEL_TRANSPORT` | C13 | Model call thất bại |
| `E_REPLAY_MISS` | `ReplayModelClient` (chỉ test) | Không có call ghi sẵn cho request |
| `E_SOLVER_OUTPUT_INVALID` | C7 | SolverOutput không hợp lệ |
| `E_SQL_NOT_SELECT`, `E_SQL_NONDETERMINISTIC` | C7 | Vi phạm quy tắc SQL |
| `E_SQL_EXEC`, `E_SQL_TIMEOUT`, `E_EXEC_CRASH`, `E_EXEC_MEMORY` | C8 | Thực thi thất bại |
| `E_PY_EXEC`, `E_PY_TIMEOUT`, `E_PY_IMPORT` | C8 (P2) | Python fallback thất bại |
| `E_EMPTY_RESULT` | C7/C9 | Không có dòng hoặc NULL |
| `E_TYPE_CONTRACT` | C7/C9 | Kết quả không khớp type kỳ vọng |
| `E_NO_SUCCESS` | C9 | Không attempt thành công |
| `E_DEADLINE`, `E_GLOBAL_STOP` | C12 | Giới hạn thời gian |
| `E_INTERNAL` | C12 | Exception chưa bắt |
| `E_DUPLICATE_WRITE` | C11 | Ghi lần hai cho ID (không phải kết quả câu hỏi) |

Warning code (`W_*`) được định nghĩa tại nơi phát sinh (§7.1, §7.2), liệt kê trong `contracts/codes.py`. Component phụ trách mỗi code cũng có ở đó, để phân tích lỗi chuyển lỗi đến đúng người (TASKS L-14).

---

## 11. Ngân sách hiệu năng

Đo ngân sách trên Colab G4 với giới hạn bộ nhớ đích (AP §4.2), xác nhận trên E5.
| Hạng mục | Ngân sách | Phụ trách | Đo tại |
|---|---|---|---|
| Tải + warm-up replica (cả hai, song song) | ≤ 300 giây | M4 | M1 |
| Call TemporalParams | ≤ 30 giây | M2 | M1 |
| Setup doanh nghiệp (300k dòng, XLSX) | ≤ 60 giây/doanh nghiệp, chạy chồng thời gian | M1 | M1 |
| Parse call | p95 ≤ 15 giây ở concurrency production | M3 | M1 |
| Solve/repair call | p95 ≤ 30 giây ở concurrency production | M3 | M1 |
| Thực thi SQL | p95 ≤ 2 giây; hard limit 20 giây | M3 | M1 |
| Thời gian throughput mỗi câu trên mỗi replica | Trung bình ≤ 17 giây (AP §7.8) | M4 | M1, M3 |
| Lần chạy đầy đủ, 1.000 câu | ≤ 9.000 giây (gate G3) | M4 | M1 (dự báo), M3 (đo) |
| RAM host đỉnh | ≤ 128 GB | M4 | M3 |
| Dung lượng `/tmp` | ≤ 50 GB | M1 | M3 |
| Bộ nhớ GPU mỗi replica | Trong `gpu_memory_utilization × 32 GB` | M4 | M1 |

---

## 12. Bảo mật và cô lập (khoanh vùng lỗi)
- Container chạy không mạng; socket duy nhất là cổng loopback `base_port … base_port + replicas − 1`.
- SQL được sinh chạy read-only, tắt truy cập ngoài, khóa config; Python được sinh chạy trong worker process có thể hủy, có giới hạn tài nguyên và import allow-list.
- Không mã được sinh nào chạy trong process chính. Không mã được sinh nào được ghi ngoài `/tmp/datamate/sandbox/<pid>/`.

---

## 13. Artifact tuân thủ (M4 phụ trách, Lead duyệt)

### 13.1 `/code/README.md` [REQ DG §8]
PHẢI có: phương pháp (đọc dữ liệu, sinh/thực thi mã, chọn đáp án); với **mỗi** model (LLM và calibrator P3 nếu dùng): tên, URL nguồn công khai, revision cố định, ngày phát hành gốc, license, số tham số tính bằng `tools/count_params.py` (tổng số phần tử tensor trong mọi safetensors ở thư mục đóng gói, gồm vision tower); nguồn/phiên bản dữ liệu, tiền xử lý, số mẫu train/validation; hướng dẫn chạy; vị trí thư mục (DG §4); tuyên bố có thực hiện training hoặc sinh dữ liệu hay không.

### 13.2 `/code/training_code/` [REQ DG §4, §8]
- Ngay cả khi không fine-tuning, **kho few-shot** và mọi **calibrator** đều được tạo từ training split, nên phải đóng gói quy trình sinh:
  - `data_generation/build_fewshot.py`, `data_generation/build_calibrator_data.py` (P3), `configs/`, `logs/`, `data/` (file dẫn xuất), `requirements.txt` (pin phiên bản), `README.md` với lệnh chính xác và tuyên bố “không thực hiện fine-tuning model” (“no model fine-tuning was performed”), trừ khi DEC-9 áp dụng LoRA.
- `data_manifest.json`: `[{path, sha256, size_bytes, source, version, split, record_count}]` cho mỗi file dữ liệu đóng gói; với base checkpoint chỉ dùng training không đưa vào image: URL công khai, revision, license, file cần thiết, SHA-256.
- `.dockerignore` KHÔNG ĐƯỢC loại `training_code/`.

### 13.3 Checklist trước khi nộp (ánh xạ DG §10)
Tự động hóa bằng `tools/precheck.sh` trên E5: chạy đúng lệnh chấm; xác minh một dòng submission mỗi câu; xác thực mọi dòng log với schema `LogRecord`; xác minh quy tắc hiện diện `thinking`/`code`/`output`; so sánh hai run; báo cáo dự báo runtime; kiểm tra platform và kích thước chưa nén của image; xác minh `md5sum -c` trên máy thứ hai.

---

## 14. Kiểm thử, tương thích và tích hợp

### 14.1 Bố cục test và phân công
```
tests/
├── contract/
│   ├── test_schemas.py           # round-trip, invariants (§5.9), schema diff — Lead
│   ├── conformance/              # one suite per protocol (§14.3) — Lead
│   └── consumers/                # consumer tests (§14.4) — written by consumers
├── unit/<package>/               # owner of the package
├── integration/                  # ReplayModelClient on fixture businesses — Lead
├── determinism/                  # two runs, byte comparison (§14.5) — Lead
├── golden/                       # Brief examples shared by scorer and formatter — Lead + M2
└── fixtures/
    ├── businesses/               # M1
    ├── catalogs/                 # M1 (fake catalogs)
    ├── rulebooks/                # M2
    └── model_calls/              # M3 (recorded ModelCalls with template versions)
```

### 14.2 Yêu cầu
- **Truy vết.** Mỗi MUST trong mục component có ít nhất một test với tên bắt đầu bằng `test_spec_<section>_` (ví dụ `test_spec_7_5_rolling_excludes_as_of`). CI báo các MUST trong mục của người phụ trách chưa có test.
- Mục tiêu line coverage ≥ 80% cho `ingest`, `catalog`, `temporal`, `formatting`, `decision`, `sandbox`, `eval`.
- `pytest -q` pass trên CPU cho mọi test trừ test đánh dấu `gpu`. Test `gpu` chạy trên Colab.
- Static check: import graph và phân lớp (§4.3), quy tắc public API (§4.3), quét ID literal (§2.5), schema diff (§5.1), `ruff`, `mypy --strict` cho `contracts/`, `temporal/`, `formatting/`.

### 14.3 Bộ conformance test
Mỗi protocol §5.10 có một bộ trong `tests/contract/conformance/`, parameterize trên mọi implementation (đối tượng thay thế và bản thật). Không được merge implementation trước khi pass.

| Bộ test | Implementation | Kiểm tra |
|---|---|---|
| `test_model_client.py` | `ScriptedModelClient`, `ReplayModelClient`, `HttpModelClient` (đánh dấu `gpu`), client in-process (đánh dấu `gpu`) | Đủ mọi trường `ModelCall`; `request_sha256` giống cho request giống, khác cho request khác; `content`/`reasoning` chính xác từng byte (tiếng Việt, khoảng trắng, chuỗi rỗng); lỗi trả qua `ModelCall.error`, không raise; `params` phản ánh mọi tham số đã gửi |
| `test_executor.py` | `FakeExecutor`, sandbox pool | Round-trip mã hóa có tag cho mọi SQL type; Decimal chính xác; ngữ nghĩa `truncated`/`row_count`; code lỗi cú pháp, timeout, bộ nhớ, thử ghi; hai implementation cho kết quả giống hệt trên fixture catalog |
| `test_lunar_calendar.py` | `FixtureLunarCalendar`, implementation C5 | `to_solar(to_lunar(d)) == d` trong miền bao phủ; `covers()` nhất quán với chuyển đổi; xử lý tháng nhuận; lỗi xác định khi ngoài miền |
| `test_submission_sink.py` | `InMemorySink`, writer C11 | Một write mỗi ID; từ chối trùng; `written_ids()` chính xác; lưu log trước dòng submission (kiểm tra file đối với C11) |

### 14.4 Fake và consumer test
- **Fake.** Trước khi có component thật, consumer viết code dựa trên đối tượng thay thế §5.10 và fake catalog (M1-11). Đối tượng thay thế vượt cùng conformance test như component thật.
- **Consumer test.** Khi consumer phụ thuộc hành vi output của thành viên khác mà kiểu contract không diễn đạt (ví dụ “SchemaCard liệt kê mọi giá trị của cột status ít giá trị”, “kết quả list luôn có `tie_code`”), consumer viết test trong `tests/contract/consumers/`, đặt tên `<consumer>__<producer>__<assumption>.py`. Test chạy trên implementation thật của producer với fixture.
- Producer KHÔNG ĐƯỢC merge thay đổi làm consumer test hỏng. Nếu cần đổi giả định, producer và consumer thống nhất trước, đổi test cùng merge và cả hai phê duyệt.

### 14.5 Determinism CI
- Với mọi merge request, `tests/determinism/` chạy `run.main` hai lần trên fixture doanh nghiệp bằng `ReplayModelClient` và `--dev --set model.replicas=1`, trong hai process mới.
- `submission.jsonl` PHẢI giống từng byte. `questions.jsonl`, `businesses.jsonl`, `run.json` PHẢI giống sau bỏ trường thời gian (`elapsed_ms`, `latency_ms`, `duration_ms`, `setup_ms`, `timings`, timestamp).
- Thất bại sẽ chặn merge (D13).

### 14.6 Giai đoạn tích hợp
| Stage | Ngày | Nội dung | Hoàn thành khi |
|---|---|---|---|
| **I0** | 11-07 12:00 | Lead merge `contracts/` v1.0.0, protocol, đối tượng thay thế, schema, conformance test | Contract và conformance test pass |
| **I1** | 11-08 | Walking skeleton: mọi stage thật hoặc stub (`--stub`); `run.main` end-to-end với `ReplayModelClient`; output hợp lệ trên fixture | Integration và determinism test pass |
| **I2** | 11-09 | Component thật trên Colab G4 với training split | Gate G1–G3 (AP §9.2) |
| **I3** | 11-11 | Tính năng P2 dưới switch | G4–G5 |
| **I4** | 11-13 | Container trên E5 | G6 |

### 14.7 Quy tắc phát triển song song
- Mỗi thành viên phát triển theo contract, đối tượng thay thế và fake, không dựa vào code chưa hoàn tất của người khác.
- M3 tạo fixture `ModelCall` ghi sẵn trên Colab (TASKS M3-13), cập nhật mỗi lần đổi phiên bản template để công việc chỉ CPU chạy integration test không cần GPU.
- Merge vào `main` trong merge window hằng ngày (`IMPLEMENTATION_PLAN.md` §4.3), theo thứ tự phụ thuộc; mỗi merge có unit, contract, conformance, consumer, integration, determinism test pass và reviewer bắt buộc §4.2 phê duyệt.

---

## 15. Quản lý thay đổi và tương thích

### 15.1 Contract
- Lead phụ trách `contracts/`. Thay đổi cần: đề xuất bằng văn bản (một đoạn), danh sách producer/consumer bị tác động, tăng phiên bản, sinh lại schema, cập nhật đối tượng thay thế và conformance test — trong cùng merge.
- **Quy tắc phiên bản.**
  | Thay đổi | Phiên bản | Được phép sau I0 |
  |---|---|---|
  | Tài liệu, validator chặt hơn nhưng chấp nhận mọi dữ liệu đang được tạo | patch | Có |
  | Trường optional mới có default; enum member mới mà consumer có thể bỏ qua; reason/warning code mới | minor | Có, thông báo consumer |
  | Bỏ/đổi tên trường, đổi type, chuyển optional thành bắt buộc, đổi ý nghĩa giá trị | major | Chỉ khi Lead duyệt và thông báo toàn nhóm trong ngày; không bao giờ sau đóng băng 11-13 |
- **Thay đổi hai bước.** Thay đổi major thực hiện như sau: (1) thêm trường mới (minor), (2) chuyển producer/consumer sang trường mới, (3) bỏ trường cũ (major), để `main` pass ở mọi bước.

### 15.2 Các phần dùng chung khác
Xử lý như contract (cùng quy tắc phiên bản, reviewer = mọi consumer):
- Hành vi `lexicon.fold()` (§7.6.1).
- Định dạng text SchemaCard (§7.2.9).
- ID và phiên bản prompt template (§7.13.5).
- Khóa config (§6): thêm khóa cần default; bỏ/đổi tên khóa là major.
- Reason/warning code (§10.2): không tái dùng code với ý nghĩa khác.
- Golden test trong `tests/golden/` (§7.10): thay đổi cần Lead và M2 duyệt.

### 15.3 Đóng băng
Sau đóng băng 11-13, chỉ sửa bug, mỗi bản sửa xác thực lại trên E5 (G6). Có thể đổi default config đến lúc đóng băng qua thay đổi `run_config.json` được review, kèm kết quả harness làm căn cứ.

Cập nhật đặc tả này trong cùng merge với mọi thay đổi do nó điều chỉnh.

---

## 16. Làm rõ kiến trúc

Không điểm nào dưới đây thay đổi ranh giới component hoặc quyết định đã duyệt.

| ID | Làm rõ | Tham chiếu AP | Lý do |
|---|---|---|---|
| **SC-1** | C1 trích xuất tham số thời gian P1 **một lần mỗi split** (`TemporalParams`), không để parser làm từng câu | AP §7.1 (“tham số do parser điền”) | Cùng tham số cho mọi câu (determinism, ít token); vẫn đọc rulebook mount, fallback generic tường minh |
| **SC-2** | SQL identifier là ASCII đã bỏ dấu; giữ header gốc trong metadata/SchemaCard; không sửa giá trị dữ liệu | AP §6.2, DEC-11 | Sinh SQL tin cậy. **Mở rộng DEC-11 sang identifier; cần Lead xác nhận cùng DEC-11** |
| **SC-3** | **Thiết yếu:** đọc SQLite bằng thư viện chuẩn Python (`mode=ro&immutable=1`); tắt tự cài/load extension DuckDB ở mọi nơi | AP §6.2 (“attach SQLite read-only”) | Extension `sqlite` của DuckDB được tải lúc chạy, sẽ lỗi dưới `--network none`; mở SQLite thông thường cũng có thể thử ghi journal vào `/data` read-only |
| **SC-4** | DuckDB query single-thread; cột nguyên `BIGINT`, fixed-point `DECIMAL(38,6)` | AP §7.7 | Tổng hợp floating point song song có thể đổi kết quả giữa run; tổng VND lớn có thể vượt độ chính xác double ở độ phân giải 2 chữ số thập phân |
| **SC-5** | Query list trả `item, sort_key, tie_code`; formatter sắp thứ tự, tie-break, cắt | AP §5.3 (“xếp hạng tất định”) | Cụ thể hóa helper xếp hạng tất định |
| **SC-6** | Biểu thức thời gian xuất theo từ vựng có cấu trúc khép kín (`TimeExpr`) cùng span nguyên văn | AP §7.1 (“LLM trích xuất nguyên văn biểu thức”) | Code giải quyết biểu thức có cấu trúc chính xác; text tiếng Việt tự do không thể xử lý tất định |
| **SC-7** | `thinking` là list theo call, dùng `""` cho call không reasoning nếu ít nhất một call có reasoning; `null` nếu tất cả không có | AP §7.6, DG §3.3 | Giữ khớp thứ tự với `calls[]`, không bịa reasoning |

---

## 17. Mục còn mở và danh sách xác minh

| ID | Hạng mục | Phụ trách | Hạn | Default trước khi giải quyết |
|---|---|---|---|---|
| V1 | JSON wire shape đáp án `list` (chỉ item? code hay tên?) theo Brief §2.2 | Lead (L-11) | I0 | Array giá trị `item` |
| V2 | JSON wire shape đáp án `table` theo Brief §2.2 | Lead (L-11) | I0 | `{"columns", "rows"}` |
| V3 | Chế độ làm tròn 2 chữ số; literal int/float (AP Q5) | Lead (L-11) | I0, xác nhận ban tổ chức | `ROUND_HALF_UP`, integer literal nếu là số nguyên |
| V4 | Mã hóa `boolean` | Lead (L-11) | I0 | JSON `true`/`false` |
| V5 | Thứ tự `tie_code` (số hay từ điển) | Lead (L-11), M2 | I1 (từ tham chiếu training) | Theo số nếu tất cả là số |
| V6 | Tên cột và mã hóa tháng nhuận của `calendar.csv` | M2 (M2-01) | M0 | Bảng alias |
| V7 | Hành vi tham chiếu với window ngoài miền (AP Q7) | Lead | I2 | Abstain khi độ phủ bằng 0 |
| V8 | Phân bổ thời gian setup doanh nghiệp trong `elapsed_ms` (AP Q8) | Lead | I1 | Không tính; log trong businesses.jsonl |
| V9 | Tên flag CLI vLLM, hỗ trợ `chat_template_kwargs` / `response_format` của phiên bản DEC-3 | M4, M3 | I2 | Như §7.13 |
| V10 | Loopback dưới `--network none` | M4 (M4-10) | G6 | HTTP serving; chuẩn bị fallback in-process |
| V11 | Category câu hỏi có trong dữ liệu training (để báo cáo) | Lead | M0 | Chỉ báo theo type và reason |
| V12 | DEC-11 gồm identifier folding SC-2 | Lead | I0 | Chỉ fold retrieval key và identifier |
| V13 | Câu chữ chính xác trong Brief cho mọi [REQ] kế thừa từ AP (không có nguồn khi viết) | Lead | I0 | Nội dung AP |

---

## Phụ lục A. Ví dụ xử lý (minh họa)

Câu hỏi: `{"id": "q_00042", "business_id": "biz_007", "question": "doanh thu thang truoc la bao nhieu", "as_of_date": "2025-06-18"}`

1. C4 `QuestionFrame`: `expected_type = number`, `metric_text = "doanh thu"`, `time = [{span: "thang truoc", role: primary, expr: {kind: relative_period, unit: month, offset: -1, to_date: false}}]`, `answerability = answerable`.
2. C5 với `prior_period_full = true`: window `[2025-05-01, 2025-05-31]`, độ chi tiết `month`, độ phủ 1.0.
3. SQL C7 (`solve.sql.v1`): `SELECT SUM(amount) AS value FROM orders WHERE order_date BETWEEN DATE '2025-05-01' AND DATE '2025-05-31' AND status NOT IN (…)`.
4. Kết quả C8: một dòng, `{"t": "dec", "v": "48250000"}` (tổng BIGINT).
5. C9: quy tắc 7 → `D_ANSWER`. C10: số nguyên → `48250000`.
6. Dòng submission: `{"id":"q_00042","type":"number","answer":48250000}`.
7. Dòng log: `{"id":"q_00042","answer":{"type":"number","answer":48250000},"elapsed_ms":7312,"thinking":null,"code":"SELECT SUM(amount) AS value …","output":{"columns":["value"],"rows":[[48250000]],"row_count":1,"truncated":false},"contracts_version":"1.0.0","business_id":"biz_007","calls":[…2 calls…],"attempts":[{"attempt_no":1,"stage":"solve","language":"sql","ok":true,"error_code":null,"duration_ms":41}],"windows":[…],"decision":{"kind":"answer","reason_code":"D_ANSWER","features":{…},"p_correct":null},"degrade":false}`

## Phụ lục B. Tóm tắt interface theo người phụ trách

| Phụ trách | Cung cấp | Sử dụng | Đối tượng thay thế người khác dùng lúc chờ | Sản phẩm đầu tiên |
|---|---|---|---|---|
| Lead | Kiểu contract, protocol, đối tượng thay thế, conformance test, scorer, harness, so sánh run | Mọi output | — | `contracts/` v1.0.0 (11-07 12:00) |
| M1 | `BusinessCatalog`, file DuckDB, SchemaCard, `fold()`, lexicon, `EntityCandidate` (P2), `SemanticAnnotations` (P2) | `RunConfig`, `ModelClient` (P2) | Fake catalog (M1-11) | Fake catalog (11-07); `setup_business` trên fixture (11-08) |
| M2 | `SplitContext`, `TemporalParams`, `TimeWindow`, `LunarCalendar`, `Decision`, định dạng `SubmissionRecord` | `QuestionFrame`, `SolverAttempt`, `BusinessCatalog`, `ModelClient` | `fixture_split_context()`, window literal | `resolve_windows` P1 (11-08 12:00) |
| M3 | `QuestionFrame`, `SolverOutput`, `SolverAttempt`, `ExecutionResult`, implementation `ModelClient`, prompt, `ModelCall` ghi sẵn | `SplitContext`, `BusinessCatalog`, `TimeWindow`, `fold()` | `ScriptedModelClient`, `ReplayModelClient`, `FakeExecutor` | Client (11-07); fixture ghi sẵn (11-08 12:00) |
| M4 | `run.main`, stub mode, Orchestrator, Writer, `LogRecord`, replica, Docker image, artifact tuân thủ | Mọi thứ | `InMemorySink`, gọi pipeline trực tiếp | Môi trường Colab + replica (11-07); stub mode `run.main` (11-08) |
