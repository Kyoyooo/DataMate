# DataMate 2026 — Kiến trúc hệ thống

| Trường | Giá trị |
|---|---|
| **Tài liệu** | `ARCHITECTURE.md` |
| **Phiên bản** | 1.1 — phân công cho một trưởng nhóm và bốn thành viên; các điểm kết nối (seam) phục vụ phát triển song song (§10) |
| **Trạng thái** | Baseline triển khai |
| **Ngày** | 2026-11-06 (GMT+7) |
| **Dựa trên** | `ARCHITECTURE_PROPOSAL.md` v2.1 (**AP**) — thiết kế và cơ sở lập luận đã được phê duyệt |
| **Tài liệu quy định đi kèm** | `SPEC.md` v1.1 (**SPEC**) — contract, cấu hình, thuật toán, kiểm thử nghiệm thu |
| **Nguồn quy định tuân thủ** | `COMPETITION_BRIEF.md` (**Brief**) và Hướng dẫn nộp Docker (**DG**) |

### Mối liên hệ giữa bốn tài liệu kỹ thuật
| Tài liệu | Trả lời | Thay đổi khi |
|---|---|---|
| `ARCHITECTURE_PROPOSAL.md` | *Vì sao* chọn thiết kế này; phương án thay thế; rủi ro; quyết định | Một quyết định được xem xét lại |
| `ARCHITECTURE.md` (tài liệu này) | *Cấu trúc hệ thống*: các góc nhìn, module, hành vi runtime, deployment | Ranh giới module hoặc luồng xử lý thay đổi |
| `SPEC.md` | *Chính xác* từng interface, trường, thuật toán và test phải như thế nào | Contract, khóa config hoặc quy tắc thay đổi |
| `IMPLEMENTATION_PLAN.md` / `TASKS.md` | *Ai xây dựng gì, khi nào*; quy tắc cộng tác và khả năng tái lập | Lịch trình hoặc phân công thay đổi |

Nếu tài liệu này và `SPEC.md` không thống nhất về contract, trường hoặc giá trị, **SPEC được ưu tiên** và tài liệu này phải được sửa. Người phụ trách bên dưới tương ứng với các vai trò trong `IMPLEMENTATION_PLAN.md` §2: **Lead**, **M1** Dữ liệu và ngữ nghĩa, **M2** Quy tắc, thời gian và câu trả lời, **M3** Reasoning Engine, **M4** Nền tảng và tuân thủ.

---

## 1. Các yếu tố chi phối kiến trúc

| Yếu tố | Nguồn | Cách kiến trúc đáp ứng |
|---|---|---|
| Chấm điểm exact-match, trừ 1 điểm khi trả lời sai | Brief §2 | Xác định kiểu/định dạng tất định (deterministic) (C10); gate thận trọng để trả lời/abstain (C9) |
| Rulebook private có thể khác; có loại hình kinh doanh chưa từng gặp | Brief §3 | Xem rulebook là dữ liệu (C1); ingestion và prompting dựa trên schema (C2, C7) |
| 2 × RTX 5090, 6 giờ, ≤ 15B tham số, offline | DG §2 | Hai replica một GPU của cùng một model (C13); runtime scheduler (C12) |
| \|ΔPA\| ≤ 0.03 khi chạy lại | DG §6 | Greedy decoding, concurrency cố định, luồng dữ liệu tất định (§8.1) |
| Log thinking/code/output thực tế cho từng câu hỏi | DG §3.3 | Ghi nhận tại ranh giới model client và executor (C11, C13, C8) |
| Phát triển trên Google Colab (một GPU, không có Docker) | AP §4 | Serving kiểm thử được trên một GPU; cùng package và lock trong Colab và image |
| Mười ngày, năm kỹ sư | AP §0 | Bàn giao theo giai đoạn; đóng băng contract; test double cho công việc song song |

---

## 2. Góc nhìn ngữ cảnh

```
                ┌──────────────────────────── Docker container (--network none) ──────────────────────────┐
 /data (ro) ───►│                                                                                          │
  data/<biz>/   │   DataMate inference system  (bash /code/predict.sh)                                     │──► /result
  rulebook.md   │                                                                                          │    submission.jsonl
  calendar.csv  │   uses: /code/models/<model> (weights), /code/config/run_config.json, /tmp (scratch)    │    logs/*
  questions.jsonl                                                                                          │
                └────────────────────────────── GPU0, GPU1 (RTX 5090, 32 GB each) ─────────────────────────┘
```
Tác nhân bên ngoài: runner của ban tổ chức (khởi động container, mount `/data` và `/result`); trong quá trình phát triển còn có evaluation harness (C14), gọi cùng entry function với training split và đáp án tương ứng.

---

## 3. Góc nhìn process (container)

```
python3 -m datamate.run   ── main process, single asyncio event loop
│
├── runtime.Orchestrator (C12)  — schedules everything; owns deadlines and global stop
├── runtime.Writer (C11)        — sole writer of /result
├── llm.ModelClient (C13)       — sole HTTP client to the replicas
│
├── replica 0  ─ subprocess: vLLM OpenAI server, CUDA_VISIBLE_DEVICES=0, 127.0.0.1:8100
├── replica 1  ─ subprocess: vLLM OpenAI server, CUDA_VISIBLE_DEVICES=1, 127.0.0.1:8101
│
├── setup pool    ─ ProcessPoolExecutor(spawn), setup_workers   → ingest + catalog (C2), view DDL (C3)
└── sandbox pool  ─ killable worker processes(spawn), sandbox_workers → SQL / Python execution (C8)
```

**Lý do phân chia.** Model inference phụ thuộc chủ yếu vào GPU và chạy trong các server process riêng; ingestion và thực thi truy vấn phụ thuộc chủ yếu vào CPU, được cô lập trong worker process để truy vấn mất kiểm soát hoặc parser crash không làm sập event loop. Event loop chỉ điều phối, render prompt và xác thực các JSON object nhỏ.

**Giao tiếp.**
| Từ → Đến | Cơ chế | Payload |
|---|---|---|
| Orchestrator → setup pool | `run_in_executor` | Thư mục doanh nghiệp, config → `BusinessCatalog` (pydantic được pickle) |
| Solver → sandbox pool | Pipe riêng cho từng worker | `(db_path, code, limits)` → `ExecutionResult` (JSON có tag) |
| Bất kỳ stage nào → replica | `ModelClient` qua loopback HTTP | Chat request → `ModelCall` |
| Pipeline → Writer | `asyncio.Queue` | `(SubmissionRecord, LogRecord)` |

---

## 4. Góc nhìn module (package)

### 4.1 Cây mã nguồn
```
src/datamate/
├── __init__.py
├── run.py                    # M4 — entry point; lifecycle (SPEC §2.3); stub mode
├── config.py                 # M4 — RunConfig load/validate/hash; dev overrides
├── contracts/                # Lead — no imports from datamate
│   ├── __init__.py           # CONTRACTS_VERSION
│   ├── enums.py              # AnswerType, Stage, ExprKind, …
│   ├── codes.py              # ReasonCode, warning codes
│   ├── inputs.py             # Question
│   ├── split.py              # TemporalParams, HolidayWindow, RuleProfile, SplitContext
│   ├── business.py           # ColumnInfo, TableInfo, JoinEdge, BusinessCatalog, ViewSpec, SemanticAnnotations
│   ├── question.py           # TimeExpr, TimeRef, Mention, QuestionFrame, TimeWindow, EntityCandidate
│   ├── execution.py          # ModelCall, ExecutionResult, SolverOutput, SolverAttempt, ExecLimits
│   ├── decision.py           # TypedValue, Decision
│   ├── output.py             # SubmissionRecord, LogRecord, BusinessLogRecord, RunRecord
│   ├── protocols.py          # ModelClient, LunarCalendar, Executor, Deadline, SubmissionSink
│   ├── testing.py            # ReplayModelClient, ScriptedModelClient, InMemorySink, FakeDeadline
│   └── schemas/              # exported JSON Schemas (committed)
├── lexicon/                  # M1
│   ├── fold.py               # fold() — retrieval/identifier keys only
│   ├── normalize.py          # NFC, whitespace, abbreviation expansion
│   └── abbrev_vi.tsv
├── rules/                    # M2 — C1
│   ├── bootstrap.py          # bootstrap_split()
│   ├── rulebook.py           # load verbatim, span validation
│   └── temporal_params.py    # extraction call + validation + generic fallback
├── temporal/                 # M2 — C5
│   ├── calendar.py           # LunarCalendar implementation over calendar.csv
│   ├── periods.py            # period arithmetic (weeks, months, quarters, shifts, clamping)
│   └── resolver.py           # resolve_windows()
├── semantics/                # M1 — C3 (P2)
│   ├── compiler.py           # compile_semantics()
│   └── validate_views.py
├── ingest/                   # M1 — C2 readers and value parsing
│   ├── discover.py
│   ├── csv_reader.py
│   ├── excel_reader.py       # calamine; block/header/total-row detection
│   ├── sqlite_reader.py      # stdlib sqlite3, immutable read-only
│   ├── numbers.py            # VN/EN/PLAIN conventions, suffixes, voting
│   ├── dates.py              # format inference, DMY/MDY evidence, Excel serials
│   └── identifiers.py        # SQL identifier derivation (SC-2)
├── catalog/                  # M1 — C2 materialization and profiling
│   ├── materialize.py        # DuckDB file creation
│   ├── profile.py            # column stats, keys, joins, date coverage
│   ├── schema_card.py        # deterministic SchemaCard rendering + budgeting
│   └── setup.py              # setup_business()
├── entities/                 # M1 — C6 (P2)
│   ├── index.py
│   └── link.py
├── llm/                      # M3 client.py, tokenizer.py; M4 replicas.py, inprocess.py — C13
│   ├── client.py             # HttpModelClient
│   ├── inprocess.py          # AsyncLLM fallback client
│   ├── replicas.py           # launch, health, warm-up, restart
│   └── tokenizer.py          # token counting with chat template
├── prompts/                  # M3
│   ├── render.py             # Jinja2 StrictUndefined; template hashing
│   └── *.j2                  # rules.temporal.v1, parse.frame.v1, solve.sql.v1, repair.sql.v1, …
├── parse/                    # M3 — C4
│   └── parser.py             # parse_question()
├── solver/                   # M3 — C7
│   ├── context_pack.py       # sections 1–7, budgeting, relevant-subset mode
│   ├── fewshot.py            # bank loading + deterministic selection
│   ├── sql_rules.py          # check_sql()
│   ├── contract_check.py     # result shape vs expected type
│   ├── typed_value.py        # to_typed_value()
│   └── solver.py             # solve(): attempt loop
├── sandbox/                  # M3 — C8
│   ├── pool.py               # killable worker pool
│   ├── worker.py             # worker main: duckdb read-only connections, exec
│   ├── encode.py             # tagged JSON value encoding
│   └── py_guard.py           # import allow-list (P2)
├── decision/                 # M2 — C9
│   ├── features.py
│   ├── gate.py               # rule gate
│   ├── catalog_check.py      # missing-field confirmation
│   └── calibrator.py         # P3
├── formatting/               # M2 — C10
│   ├── numbers.py            # Decimal quantize, integer literal rule
│   ├── lists.py              # ranking, tie-break, truncation
│   ├── tables.py
│   ├── serialize.py          # Decimal-preserving JSON encoder
│   └── table_conventions.md
├── runtime/                  # M4 — C11, C12
│   ├── orchestrator.py       # grouping, assignment, workers, deadlines, degrade, stop
│   ├── pipeline.py           # per-question pipeline composition
│   ├── deadline.py
│   ├── writer.py             # fsync writer
│   └── records.py            # LogRecord / BusinessLogRecord / RunRecord assembly
├── eval/                     # Lead — C14 (never imported by run.py)
│   ├── scorer.py
│   ├── harness.py
│   ├── folds.py
│   ├── report.py
│   └── compare_runs.py
└── assets/
    └── fewshot.jsonl         # M3 — generated from training split (training_code/data_generation)
```

### 4.2 Phân lớp
```
 L5  run.py, eval/                      entry points
 L4  runtime/                           orchestration, persistence
 L3  parse/, solver/, decision/, semantics/   reasoning stages
 L2  catalog/, temporal/, rules/, entities/, sandbox/, formatting/, llm/, prompts/   services
 L1  ingest/, lexicon/                  primitives
 L0  contracts/, config.py              shared types
```
Một module chỉ được import từ cùng lớp hoặc các lớp thấp hơn. `llm/` và `prompts/` là các service được L3 và `rules/`/`semantics/` sử dụng. Kiểm tra import graph trong CI thực thi bảng này (SPEC §4.3).

### 4.3 Trách nhiệm của component (tóm tắt)
Hành vi đầy đủ nằm trong SPEC §7; bảng này ấn định người phụ trách và các ranh giới mà mỗi component không được vượt qua.

| Component | Package | Phụ trách | Chịu trách nhiệm | Không được |
|---|---|---|---|---|
| C1 Split Bootstrap | `rules/` | M2 | Văn bản rulebook, `TemporalParams`, `RuleProfile` (P2) | Chứa bất kỳ hằng số nào lấy từ training rulebook |
| C2 Ingestion & Catalog | `ingest/`, `catalog/` | M1 | File DuckDB, SchemaCard, profiling | Thay đổi giá trị dữ liệu; gọi model |
| C3 Semantic Compiler (P2) | `semantics/` | M1 | View đã xác thực | Cung cấp view chưa xác thực |
| C4 Question Parser | `parse/` | M3 | `QuestionFrame` | Tính ngày hoặc đáp án |
| C5 Temporal Resolver | `temporal/` | M2 | `TimeWindow` | Thực hiện I/O hoặc gọi model |
| C6 Entity Linker (P2) | `entities/` | M1 | `EntityCandidate` | Trả về giá trị đã fold |
| C7 Solver | `solver/` | M3 | Context pack, vòng lặp thử, `SolverAttempt` | Tự thực thi mã |
| C8 Sandbox Executor | `sandbox/` | M3 | Thực thi, giới hạn, mã hóa giá trị | Ghi ra ngoài thư mục tạm của mình |
| C9 Verifier & Decision | `decision/` | M2 | `Decision` | Gọi model (P1/P2) |
| C10 Formatter | `formatting/` | M2 | Giá trị ở dạng truyền đi (wire value) | Đọc trực tiếp chuỗi output của model |
| C11 Persistence | `runtime/writer.py` | M4 | Các file `/result` | Để bất kỳ writer nào khác ghi mà bỏ qua nó |
| C12 Orchestrator | `runtime/` | M4 | Lập lịch, deadline, phân công | Thay đổi concurrency khi đang chạy |
| C13 Model Serving | `llm/` | M3 (client), M4 (replica) | Replica, request, `ModelCall` | Dùng giá trị mặc định của server hoặc template |
| C14 Evaluation | `eval/` | Lead | Chấm điểm, CV, bản ghi lần chạy | Được import vào luồng inference |

---

## 5. Góc nhìn runtime

### 5.1 Khởi động
```
run.main
 ├─ config.load(run_config.json) ─► RunConfig, config_sha256
 ├─ read questions.jsonl ─► Question[] (invalid → pre-abstained)
 ├─ orchestrator.plan(): group by business, order, assign replicas   (deterministic)
 ├─ in parallel ─────────────────────────────────────────────────────────────────
 │   ├─ replicas.start(0), replicas.start(1) → /health → warm-up
 │   ├─ setup pool: setup_business(b) for b in planned order
 │   └─ after replica 0 ready: rules.bootstrap_split() → SplitContext
 └─ when SplitContext ready and business b ready → enqueue b's questions on its replica queue
```

### 5.2 Luồng xử lý từng câu hỏi (P1)
```
worker(replica r) takes q            ← elapsed_ms starts
 │
 ├─ lexicon.normalize(q.question) → normalized
 ├─ parse.parse_question()   ──ModelCall#1──► replica r ──► QuestionFrame | E_PARSE_INVALID
 ├─ temporal.resolve_windows()                         ──► TimeWindow[] | E_TIME_UNSUPPORTED
 ├─ solver.solve()
 │    ├─ context_pack.build()  (sections 1–5 byte-identical per business)
 │    ├─ attempt 1: ModelCall#2 ─► SolverOutput ─► check_sql ─► sandbox.run_sql ─► contract_check
 │    └─ ≤ 2 repairs (append turns; same prefix) while not ok and before soft deadline
 ├─ decision.decide()  → Decision (rule gate)
 ├─ formatting.to_submission() → SubmissionRecord
 └─ writer.put(SubmissionRecord, LogRecord)            ← elapsed_ms ends
```
P2 chèn `entities.link()` sau bước giải quyết thời gian và Python fallback sau các lần thử SQL thất bại; các view C3 xuất hiện ở phần 5 của context.

### 5.3 Các luồng lỗi
| Sự kiện | Xử lý | Kết quả |
|---|---|---|
| Exception khi setup doanh nghiệp | Bắt trong setup pool; `status = failed` | Mọi câu hỏi của doanh nghiệp đều abstain với `E_BUSINESS_SETUP` |
| Model call timeout | `ModelCall.error`; stage xem đây là lần thử thất bại | Repair nếu được phép, nếu không thì abstain |
| SQL timeout / OOM | Hủy worker và thay mới | Lần thử thất bại với `E_SQL_TIMEOUT` / `E_EXEC_MEMORY` |
| Exception chưa được bắt trong một câu hỏi | Bắt tại ranh giới câu hỏi | Abstain `E_INTERNAL`; traceback trong run.json |
| Câu hỏi vượt hard deadline | Hủy task | Abstain `E_DEADLINE` |
| Replica crash | Restart một lần; chuyển hàng đợi sang replica còn lại | Tiếp tục xử lý câu hỏi trên replica còn lại |
| Lần chạy chậm tiến độ | Degrade mode (không repair/fallback/P3) | Ghi log thời điểm kích hoạt |
| `T0 + global_hard_stop_s` hoặc SIGTERM | Hủy tất cả; hoàn tất | ID chưa được ghi sẽ abstain `E_GLOBAL_STOP` |

### 5.4 Tắt hệ thống
Writer xử lý hết hàng đợi → ghi các dòng abstain cho ID chưa ghi → ghi `run.json` theo cách atomic → gửi SIGTERM cho replica (sau 30 giây gửi SIGKILL) → đóng các pool → exit code theo SPEC §2.1.

---

## 6. Góc nhìn dữ liệu

### 6.1 Vòng đời dữ liệu
| Artifact | Tạo bởi | Vị trí | Vòng đời | Bên sử dụng |
|---|---|---|---|---|
| `RunConfig` | Build image | `/code/config/run_config.json` | Đóng băng | Tất cả |
| Kho few-shot | `training_code/data_generation/build_fewshot.py` | `/code/src/datamate/assets/fewshot.jsonl` | Đóng băng | C7 |
| `SplitContext` | C1 | Bộ nhớ | Lần chạy | C4, C5, C7 |
| DuckDB của doanh nghiệp | C2 (+view C3) | `/tmp/datamate/biz/<bkey>/catalog.duckdb` | Lần chạy | C8 (read-only) |
| `BusinessCatalog` | C2 | Bộ nhớ + `businesses.jsonl` | Lần chạy | C4, C6, C7, C9 |
| Object theo từng câu hỏi | C4–C10 | Bộ nhớ | Câu hỏi | C11 |
| Output | C11 | `/result/...` | Lưu bền vững | Ban tổ chức |

### 6.2 Bố cục database của doanh nghiệp
- Một file DuckDB cho mỗi doanh nghiệp, một table cho mỗi bảng nguồn/khối trong sheet (quy tắc đặt tên tại SPEC §7.2.7).
- Cột đã parse chứa giá trị có kiểu; cột VARCHAR `<col>__raw` chỉ tồn tại khi parsing đã thay đổi hoặc đưa giá trị về null.
- View P2 có tên `v_<name>` và được lưu trong cùng file; DDL của chúng cũng nằm trong business log.
- Không tạo index; DuckDB scan đủ nhanh với ≤ 300k dòng và giữ setup đơn giản.

### 6.3 Xử lý văn bản
| Văn bản | Dạng chuẩn | Có fold không? |
|---|---|---|
| Giá trị dữ liệu trong DuckDB | Như khi đọc, NFC | Không bao giờ |
| Header gốc | NFC | Không bao giờ (giữ trong `original_name`) |
| SQL identifier | ASCII từ `fold()` | Có (SC-2) |
| Câu hỏi gửi cho model | Bản gốc NFC + bản chuẩn hóa | Không |
| Khóa entity index | `fold()` | Có (chỉ để retrieval) |
| Chuỗi output | Giá trị đã lưu | Không bao giờ |

---

## 7. Góc nhìn deployment

### 7.1 Image
```
FROM <base image chosen by DEC-3>        # vLLM + PyTorch with sm_120 support
ENTRYPOINT []
ENV  (SPEC §2.4)
COPY requirements.txt → pip install (lock)            layer: dependencies
COPY models/<selected>/ → /code/models/<selected>/    layer: weights (cached across code changes)
COPY training_code/ → /code/training_code/            layer: compliance artifacts
COPY config/ predict.sh README.md → /code/
COPY src/ → /code/src/                                layer: code (changes most often)
CMD ["bash", "/code/predict.sh"]
```
Build cho `linux/amd64` trên build host (E4); gắn tag `zaic2026_datamate_<team_name>:final` (DG §9).

### 7.2 Môi trường
| Môi trường | Nội dung chạy | Khác biệt so với môi trường đích |
|---|---|---|
| E1 Colab G4 (sm_120) | Cài package từ lock vào venv; replica chạy dưới dạng subprocess; harness | Một GPU → `replicas = 1` với `--dev`; giới hạn bộ nhớ tương đương 32 GB; không có Docker |
| E2 Colab A100/H100 | Thử nghiệm độ chính xác | Kiến trúc GPU khác; số đo runtime và determinism không có giá trị cho môi trường đích |
| E3 CPU (Colab hoặc laptop) | Unit test, contract test, integration test với test double | Không có model |
| E4 Build host | `docker build`, `save`, checksum, upload | Không cần GPU |
| E5 Rehearsal host (sm_120, Docker) | Lệnh chấm điểm chính xác; chạy private test bằng image đã đóng băng | Phải khớp môi trường đích sát nhất có thể (AP RISK-1, RISK-2) |

### 7.3 Cấu hình theo môi trường
Production dùng `run_config.json` đã đóng băng. Development dùng cùng file cộng với các override `--dev --set` được ghi lại, chẳng hạn `model.replicas=1`, `model.gpu_memory_utilization=0.30` trên G4, `model.path=/content/models/<m>`. Không cho phép override trong image.

---

## 8. Các vấn đề xuyên suốt hệ thống

### 8.1 Tính tất định (determinism)
Các nguồn gây không tất định và biện pháp kiểm soát:

| Nguồn | Biện pháp | Vị trí |
|---|---|---|
| Sampling | Greedy, seed cố định, tham số tường minh | Client C13 |
| Thành phần batch trên GPU | Concurrency và phân công cố định; batch-invariant mode nếu đã xác thực | C12, C13 |
| Byte của prompt | Render tất định; prefix dùng chung giống nhau từng byte | C7, prompts |
| Thứ tự duyệt trong Python | `PYTHONHASHSEED=0`; duyệt có sắp xếp khi output phụ thuộc thứ tự | Tất cả |
| Tổng hợp float song song | DuckDB `threads = 1` trong sandbox; kiểu số chính xác | C2, C8 |
| Kết quả SQL không có thứ tự | `LIMIT` yêu cầu `ORDER BY`; formatter sắp xếp lại list | C7, C10 |
| Thay đổi phiên bản thư viện | Tạo lock bên trong base image | Build |
| Hành vi phụ thuộc thời điểm | Chỉ giới hạn ở deadline, degrade mode, global stop; đều được log | C12 |

### 8.2 Khả năng quan sát (observability)
- **Log tuân thủ** (`questions.jsonl`): các trường DG yêu cầu cộng với call, attempt, window, decision (SPEC §8.3).
- **Business log** (`businesses.jsonl`): cảnh báo ingestion, SchemaCard, DDL của view và các compile call.
- **Bản ghi lần chạy** (`run.json`): hash cấu hình, hash template, fingerprint môi trường, phân công, thời gian, số lượng theo reason code.
- **Progress log**: mỗi `progress_interval_s` ghi một dòng gồm số câu đã trả lời/abstain và thời điểm hoàn thành dự kiến.
- **Báo cáo harness**: PA theo type, category và reason code; các percentile latency; so sánh lần chạy.

### 8.3 Xử lý lỗi
Lỗi là giá trị: mỗi thất bại trở thành một `ReasonCode` trên attempt hoặc decision. Chỉ bắt exception tại ba ranh giới — task câu hỏi, task setup doanh nghiệp và lần chạy — và mọi exception được bắt đều được ghi cùng traceback vào `run.json` (100 exception đầu).

### 8.4 Cấu hình
Một `RunConfig` bất biến, được truyền tường minh (không dùng biến global). Tính năng chưa vượt gate bị tắt bằng config (SPEC §1.3), nhờ đó có thể merge code P2/P3 sớm mà không thay đổi hành vi production.

### 8.5 Thời gian
- Mọi ngày nghiệp vụ đều là `datetime.date`; không có logic múi giờ vì input chứa ngày, không phải thời điểm.
- `as_of_date` là khái niệm “hôm nay” duy nhất; không bao giờ dùng đồng hồ hệ thống để trả lời.
- Dùng monotonic clock cho `elapsed_ms`, deadline và global stop.

### 8.6 Cách tiếp cận bảo mật
Không có mạng; mã được sinh chạy trong process riêng có thể hủy, với dữ liệu read-only, DuckDB vô hiệu hóa truy cập bên ngoài và Python có import allow-list. Đây là cách cô lập lỗi do model gây ra, không phải biện pháp chống đối tượng tấn công có chủ đích (SPEC §12).

---

## 9. Bản ghi quyết định kiến trúc

| ADR | Quyết định | Trạng thái | Nguồn |
|---|---|---|---|
| ADR-001 | Hybrid pipeline (dữ liệu/thời gian/định dạng tất định + LLM SQL) | Chấp thuận | AP DEC-1 |
| ADR-002 | DuckDB SQL là chính, Python fallback có giới hạn (P2) | Chấp thuận | AP DEC-2 |
| ADR-003 | Chọn model và base image bằng thử nghiệm đối chiếu trên Colab G4 | Chấp thuận (kết quả 11-09) | AP DEC-3 |
| ADR-004 | View biên dịch cho từng doanh nghiệp, điều khiển bằng switch | Đề xuất (P2, 11-11) | AP DEC-4 |
| ADR-005 | Giải quyết thời gian tất định với `TimeExpr` có cấu trúc | Chấp thuận | AP DEC-5, SPEC SC-6 |
| ADR-006 | Rulebook là dữ liệu; `TemporalParams` ở cấp split | Chấp thuận | AP DEC-6, SPEC SC-1 |
| ADR-007 | Không dùng ensemble hoặc learned calibration trong P1 | Chấp thuận | AP DEC-7 |
| ADR-008 | Rule gate làm chính sách quyết định của P1 | Đề xuất (mặc định) | AP DEC-8 |
| ADR-009 | Không fine-tuning trên critical path | Chấp thuận | AP DEC-9 |
| ADR-010 | Mặc định tắt thinking; switch riêng cho từng stage | Đề xuất (mặc định) | AP DEC-10 |
| ADR-011 | Chỉ bỏ dấu (accent folding) cho retrieval key và SQL identifier | Đề xuất (Lead xác nhận) | AP DEC-11, SPEC SC-2 |
| ADR-012 | Hai replica một GPU độc lập; baseline không dùng TP | Đề xuất (mặc định) | AP DEC-13 |
| ADR-013 | SQLite qua stdlib, tắt DuckDB extension | Chấp thuận (thiết yếu) | SPEC SC-3 |
| ADR-014 | Thực thi truy vấn single-thread, kiểu số chính xác | Chấp thuận | SPEC SC-4 |
| ADR-015 | Formatter áp dụng xếp hạng từ `item/sort_key/tie_code` | Chấp thuận | SPEC SC-5 |
| ADR-016 | HTTP serving trên loopback, fallback là engine in-process | Chấp thuận, xác minh tại G6 | AP §6.3 |
| ADR-017 | Ghi và fsync log record trước dòng submission tương ứng | Chấp thuận | SPEC §7.11 |
| ADR-018 | Scorer (Lead) và formatter (M2) do hai người khác nhau viết, dùng chung golden test | Chấp thuận | IMPLEMENTATION_PLAN §2.1 |
| ADR-019 | Import chéo package chỉ qua `__all__` của từng package; implementation của protocol phải vượt bộ conformance test dùng chung | Chấp thuận | SPEC §4.3, §14.3 |

Thêm quyết định mới tại đây cùng một đoạn giải thích lý do và liên kết đến thay đổi triển khai quyết định đó.

---

## 10. Các điểm kết nối phục vụ phát triển song song

Hệ thống được chia để công việc của mỗi thành viên chỉ kết nối với người khác tại một số ít seam có kiểu. Mỗi seam có một contract (SPEC §5), một đối tượng thay thế mà consumer có thể dùng trước khi component thật tồn tại, và một test sẽ thất bại nếu producer và consumer không còn tương thích.

### 10.1 Danh mục seam
| Seam | Producer → Consumer | Contract | Đối tượng thay thế tạm thời | Kiểm tra tương thích |
|---|---|---|---|---|
| Catalog | M1 → M2 (kiểm tra catalog tại gate), M3 (context pack, executor) | `BusinessCatalog` + file DuckDB | Fake catalog (TASKS M1-11) | Consumer test trên SchemaCard và các trường catalog |
| Split context | M2 → M3 | `SplitContext`, `TemporalParams` | Fixture `SplitContext` trong `contracts/testing.py` | Consumer test; bộ perturbation test (P2) |
| Khoảng thời gian | M2 → M3, M2 (gate) | `TimeWindow` | Window literal trong test | Property test của resolver; consumer test |
| Model | M3 + M4 → M2 (C1), M1 (C3), M3 (C4, C7) | `ModelClient` → `ModelCall` | `ScriptedModelClient`, `ReplayModelClient` | Bộ conformance test `ModelClient` |
| Thực thi | M3 (C8) → M3 (C7) | `Executor` → `ExecutionResult` | Fake executor in-process trong `contracts/testing.py` | Bộ conformance test `Executor` |
| Các lần thử | M3 → M2 | `SolverAttempt`, `TypedValue` | Attempt theo kịch bản | Consumer test trong `decision/` |
| Đáp án | M2 → M4 | `Decision`, `SubmissionRecord` | Stub decision trong stub mode của `run.py` | Golden test của formatter dùng chung với scorer |
| Bản ghi | M4 → Lead (harness), ban tổ chức | `LogRecord`, `BusinessLogRecord`, `RunRecord` | — | Xác thực từng dòng bằng JSON Schema |
| Sink | M4 → mọi stage trong pipeline | `SubmissionSink` | `InMemorySink` | Bộ conformance test `SubmissionSink` |
| Lịch | M2 → M2 | `LunarCalendar` | Fixture lịch nhỏ | Bộ conformance test `LunarCalendar` |

### 10.2 Quy tắc giữ seam ổn định
1. **Contract là nơi duy nhất chứa các kiểu dùng chung.** Không import chéo package bất kỳ thứ gì khác ngoài các tên trong `__all__` của mỗi package (ADR-019; SPEC §4.3).
2. **Đối tượng thay thế vượt cùng test như component thật.** Test double và fake chạy với bộ conformance test, nên vượt test với đối tượng thay thế đồng nghĩa vượt với thành phần thật (SPEC §14.3).
3. **Consumer ghi rõ các giả định.** Mọi giả định về output của thành viên khác trở thành consumer test mà producer phải duy trì ở trạng thái pass (SPEC §14.4).
4. **Stub mode phục vụ tích hợp.** `run.py` có thể thay bất kỳ stage nào bằng đối tượng thay thế qua config (`--dev --stub <stage>`), để Lead tích hợp lần lượt từng component (TASKS L-05).
5. **Replay fixture cố định hành vi model trên CPU.** `ModelCall` đã ghi được lập khóa bằng request hash và chứa phiên bản template; thay đổi prompt phải cập nhật chúng trong cùng lần merge (SPEC §7.13.5).
6. **Switch cô lập công việc chưa hoàn tất.** Merge code P2/P3 với switch ở trạng thái tắt (SPEC §1.3).

### 10.3 Cây test theo seam
```
tests/
├── contract/
│   ├── test_schemas.py           # round-trip, invariants, schema diff (Lead)
│   ├── conformance/              # one suite per protocol (Lead); run against doubles and real implementations
│   │   ├── test_model_client.py
│   │   ├── test_executor.py
│   │   ├── test_lunar_calendar.py
│   │   └── test_submission_sink.py
│   └── consumers/                # written by consumers; named <consumer>__<producer>__<assumption>.py
├── unit/<package>/               # owner of the package
├── integration/                  # Lead; ReplayModelClient on fixture businesses
├── determinism/                  # Lead; two runs, byte comparison
├── golden/                       # Brief examples shared by scorer (Lead) and formatter (M2)
└── fixtures/
    ├── businesses/               # M1
    ├── catalogs/                 # M1 (fake catalogs)
    ├── rulebooks/                # M2
    └── model_calls/              # M3
```

---

## 11. Thuộc tính chất lượng

| Thuộc tính | Mục tiêu | Cơ chế | Xác minh bằng |
|---|---|---|---|
| Đúng định dạng | 100% dòng hợp lệ | Golden test của formatter; schema validation | SPEC §9, G2 |
| Khả năng tái lập | Submission giống hệt khi chạy lại | §8.1 | G4, G7 |
| Runtime | ≤ 2.5 giờ cho 1.000 câu hỏi | Hai replica, prefix caching, deadline, degrade mode | G3, G6 |
| Độ bền vững | Không crash nào kết thúc cả lần chạy | Bắt exception tại ranh giới, cô lập process | Fault-injection test (TASKS M4-11) |
| Tuân thủ | Vượt mọi kiểm tra DG §10 | Writer, record, script precheck | G6, G8 |
| Khả năng khái quát hóa | Theo dõi PA trên doanh nghiệp held-out | Thiết kế dựa trên schema; grouped CV | Báo cáo C14 |
| Phát triển song song | Bốn thành viên cùng xây dựng mà không làm hỏng công việc của nhau | Seam tại §10: contract, fake, conformance test và consumer test, quy tắc public API | Walking skeleton I1; CI cho mỗi lần merge |

---

## 12. Rủi ro kiến trúc còn lại
Danh mục đầy đủ nằm ở AP §12. Những rủi ro mà kiến trúc này đặc biệt phụ thuộc:

| Rủi ro | Phụ thuộc kiến trúc | Fallback tích hợp sẵn |
|---|---|---|
| RISK-1 Không có host Docker sm_120 | Diễn tập G6/G7 và chạy private test | Không có giải pháp phần mềm; phải xử lý qua DEC-14 |
| RISK-3 vLLM mới hơn không chạy trên sm_120 | C13 trên base image đã chọn | Chọn model trên image tham chiếu (ADR-003) |
| RISK-4 Không có batch-invariant mode | Determinism khi chạy đồng thời | Sinh output có cấu trúc ngắn; giảm concurrency bằng config |
| V10 Loopback không hoạt động dưới `--network none` | HTTP serving | Client `AsyncLLM` in-process (ADR-016) |
| Model không vừa 32 GB khi tính cả KV cache | Topology DP | Config dự phòng TP=2 (SPEC §7.13.1) |
