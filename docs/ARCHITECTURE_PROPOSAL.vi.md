# DataMate 2026 — Đề xuất kiến trúc

| Trường | Giá trị |
|---|---|
| **Tài liệu** | `ARCHITECTURE_PROPOSAL.md` |
| **Phiên bản** | 2.1 — cập nhật phân công cho một trưởng nhóm và bốn thành viên |
| **Trạng thái** | **Baseline để triển khai.** Quyết định đã duyệt ở §3 có tính ràng buộc. Mục đánh dấu **[DEC-n] OPEN** tại §13 vẫn cần Lead phê duyệt trước ngày ghi kèm. |
| **Ngày** | 2026-11-06 (GMT+7) |
| **Phụ trách** | Kiến trúc sư phần mềm chính, thay mặt trưởng nhóm |
| **Thay thế** | Phiên bản 1.0 (bản nháp, 2026-11-06) |
| **Làm đầu vào cho** | `SPEC.md`, `ARCHITECTURE.md`, `IMPLEMENTATION_PLAN.md`, `TASKS.md` (sẽ được tạo trong các nhiệm vụ sau) |

### Thẩm quyền của nguồn
1. **Quy định cuộc thi chính thức** (`COMPETITION_BRIEF.md`, dẫn là **Brief §x**) và **Hướng dẫn nộp Docker** (`zac2026_DataMate_docker_guideline_final.md`, dẫn là **DG §x**) có thẩm quyền cao nhất. Nếu tài liệu này xung đột với một trong hai, ưu tiên nguồn đó và phải sửa tài liệu này.
2. `CLAUDE.md` quy định các quy ước kỹ thuật của nhóm.
3. Tài liệu này xác định kiến trúc trong các ràng buộc trên.

### Quy ước nhãn
| Tag | Ý nghĩa |
|---|---|
| **[REQ]** | Yêu cầu từ Brief hoặc hướng dẫn Docker |
| **[APPROVED]** | Quyết định được Lead xác nhận |
| **[OBS]** | Sự kiện quan sát được từ workspace hoặc nguồn bên ngoài được trích dẫn |
| **[HYP]** | Giả thuyết; phải xác thực trước khi dựa vào |
| **[PROP]** | Lựa chọn kỹ thuật đề xuất trong phạm vi quyết định đã duyệt |
| **[DEC-n]** | Mã quyết định (danh mục ở §13) |
| **[RISK-n]** | Mã rủi ro (danh mục ở §12) |

---

## 0. Tóm tắt điều hành

DataMate trả lời câu hỏi tiếng Việt đời thường trên dữ liệu CSV, XLSX và SQLite của từng doanh nghiệp, theo chấm điểm exact-match (+1 / 0 / −1), trên 2 × RTX 5090 trong Docker container offline, trong 6 giờ, với tổng ngân sách tham số 15B. Hạn nộp giải pháp Docker cuối cùng là **2026-11-16 23:59 GMT+7**, mười ngày theo lịch tính từ hôm nay.

Kiến trúc đã duyệt là **hybrid pipeline**: ingestion và profiling dữ liệu tất định; LLM dựa trên schema viết **DuckDB SQL** (có Python fallback giới hạn); xử lý thời gian, xếp hạng, xác định kiểu và định dạng **tất định**, dựa trên **rulebook riêng của từng split**; và gate thận trọng để quyết định trả lời/abstain. Ensemble, learned calibration và fine-tuning được xác định rõ là **ngoài critical path ban đầu**.

Bản sửa đổi này có ba thay đổi cấu trúc so với v1:

1. **Môi trường phát triển.** Phát triển và evaluation chạy trên **Google Colab**, có runtime Blackwell **G4 (RTX PRO 6000, sm_120)** nhưng **không chạy được Docker** và chỉ cung cấp **một GPU mỗi runtime**. Vì vậy, kiến trúc cho phép xác thực mọi thứ trong Colab, trừ buổi diễn tập container cuối (§4).
2. **Topology serving.** Hai **replica model một GPU độc lập** (data parallelism), baseline **không dùng tensor parallelism và NCCL**. Điều này loại bỏ các kiểu lỗi NCCL treo và shared memory mô tả tại DG §9–10, đồng thời cho phép kiểm thử đầy đủ luồng serving trên một GPU Colab (§6.3, DEC-13).
3. **Bàn giao theo giai đoạn.** Component được chia thành Phase 1 (baseline, end-to-end trước 2026-11-09), Phase 2 (độ chính xác), hoặc Phase 3 (tùy chọn, có gate). Chỉ riêng Phase 1 phải tạo được submission hợp lệ, tuân thủ và tái lập (§10).

Rủi ro chưa giải quyết nghiêm trọng nhất nằm ở **hạ tầng, không phải mô hình**: nhóm cần **host GPU sm_120 chạy được Docker** để diễn tập container và chạy image đã đóng băng trên private test (DG §1). Chưa xác định được host này (RISK-1, DEC-14).

---

## 1. Phạm vi và đầu vào

### 1.1 Trong phạm vi
Kiến trúc hệ thống inference đóng gói trong Docker image: component, luồng dữ liệu, interface, serving, determinism, runtime, logging, tuân thủ, môi trường phát triển, tiêu chí xác thực và rủi ro.

### 1.2 Ngoài phạm vi tài liệu
Schema cấp trường (→ `SPEC.md`), thiết kế cấp module (→ `ARCHITECTURE.md`), lịch trình và người phụ trách (→ `IMPLEMENTATION_PLAN.md`, `TASKS.md`) và code production.

### 1.3 Đầu vào và tình trạng
- **[OBS]** Nguồn có sẵn cho bản sửa đổi: `ARCHITECTURE_PROPOSAL.md` v1 và Hướng dẫn nộp Docker. `CLAUDE.md` và `COMPETITION_BRIEF.md` không được đính kèm phiên làm việc này. **Các dẫn chiếu Brief bên dưới được kế thừa từ v1**; Lead nên đối chiếu mẫu với Brief trước khi viết `SPEC.md`.
- **[OBS]** Tác giả chưa kiểm tra training split, repository hoặc GPU. Nhận định về hình dạng dữ liệu và phân bố câu hỏi vẫn là **[HYP]** cho đến báo cáo kiểm tra dữ liệu M0 (§11).

---

## 2. Tóm tắt yêu cầu

### 2.1 Chấm điểm
- **[REQ]** +1 nếu đúng, 0 nếu abstain hoặc thiếu, −1 nếu sai; không có điểm một phần; sai type tính là sai (Brief §2.1, §2.3).
- **[REQ]** `unanswerable` là một lớp đáp án được chấm: +1 nếu đáp án tham chiếu là unanswerable, ngược lại −1.
- **Suy ra.** Chỉ đáng trả lời khi p(đúng) > 0.5. Điểm kỳ vọng ≈ Σᵢ max(2pᵢ − 1, 0) khi confidence được calibration. **Quyết định trả lời/abstain là component trọng yếu.**
- **Suy ra.** Chọn sai type đáp án gây mất điểm ngang với tính sai giá trị.

### 2.2 Các type đáp án (Brief §2.1–2.2; DG §3.2)
| Type | Hệ quả đối với kiến trúc |
|---|---|
| `number` | Làm tròn 2 chữ số thập phân. **[HYP]** Xuất integer literal nếu giá trị sau làm tròn là số nguyên; cần xác nhận cách xử lý int/float (Q5). |
| `percent` | Đơn vị phần trăm (−12.45, không phải −0.1245), 2 chữ số thập phân, đúng dấu; chiều công thức theo rulebook hoặc quy ước có tài liệu. |
| `string` | Scorer local tái hiện chính xác chuẩn hóa (NFC → chữ thường → ký tự không phải chữ/số/khoảng trắng thành khoảng trắng → gộp khoảng trắng). **Giữ dấu tiếng Việt.** Output sao chép nguyên văn từ giá trị dữ liệu. |
| `date` | `yyyy-mm-dd`, hoặc `yyyy-mm` cho câu hỏi cấp tháng. Độ chi tiết là một phần tính đúng. |
| `boolean` | **[REQ]** Được liệt kê là kiểu giá trị ở DG §3.2. Mã hóa (JSON `true`/`false`) cần xác nhận trong `SPEC.md`. |
| `list` | Thứ tự có ý nghĩa; hòa điểm thì code tăng dần; chỉ xếp hạng trên đơn hợp lệ; cắt tại k. |
| `table` | Ghép cột sau chuẩn hóa, fallback theo vị trí; ghép dòng như tập hợp. |
| `unanswerable` | Có thể kèm `reason` (DG §3.2). |
| `abstain` | Không cần answer; thiếu dòng cũng tính là abstain (DG §3.2). |

### 2.3 Input (DG §3.1)
```
/data/                      (read-only)
├── data/<business_id>/  *.csv | *.xlsx | *.sqlite, README.md
├── rulebook.md             split-specific rules and vocabulary
├── calendar.csv            shared solar–lunar calendar
└── questions.jsonl         id, business_id, question, as_of_date
```
- **[REQ]** Rulebook private có thể khác training rulebook; không được hard-code quy tắc nào (Brief §3.4).
- **[REQ]** Private test chứa loại hình kinh doanh chưa gặp (Brief §3.1, §3.3). Chất lượng README trải từ đầy đủ đến không hữu ích (Brief §3.2).
- **[REQ]** Mỗi doanh nghiệp có 12–30 tháng dữ liệu, tối đa khoảng 300.000 dòng, trong một hoặc nhiều file.

### 2.4 Output (DG §3.2–3.3)
- **[REQ]** `/result/submission.jsonl`: mỗi dòng một JSON object với `id`, `type`, `answer` (`reason` tùy chọn cho `unanswerable`). Ghi đáp án **ngay lập tức**; nếu dừng chạy, chỉ đáp án đã lưu được tính.
- **[REQ]** `/result/logs/`: một record mỗi câu hỏi, chứa `id`, `answer`, `elapsed_ms`, `thinking`; thêm `code` và `output` khi đã thực thi mã. `thinking` phải **đúng như đã sinh, không tóm tắt hoặc cắt ngắn**; là list chuỗi theo thứ tự call nếu có nhiều model call; `null` nếu không sinh reasoning. Helper function được tham chiếu phải có trong image.
- **[REQ]** `elapsed_ms` là thời gian wall-clock từ lúc bắt đầu câu hỏi đến đáp án cuối, gồm đọc dữ liệu, reasoning và thực thi mã; với batching, đo từ lúc câu hỏi vào batch. Tải model dùng chung không tính vào `elapsed_ms` nhưng tính trong 6 giờ.

### 2.5 Môi trường thực thi (DG §2, §5, §10)
| Hạng mục | Yêu cầu |
|---|---|
| GPU | 2 × RTX 5090, mỗi GPU 32 GB; compute capability 12.0; cặp đã thử **không có P2P** (DG Hình 1) |
| RAM | 512 GB |
| CUDA stack | CUDA ≥ 12.8; PyTorch/vLLM hỗ trợ Blackwell. Base khuyến nghị `vllm/vllm-openai:v0.10.1.1`; phương án khác phải hỗ trợ sm_120 |
| Mạng | Không có trong inference (`--network none`) |
| Cách gọi | `bash /code/predict.sh`, không đối số; default cố định cho model, seed, temperature, batch size; không can thiệp thủ công |
| Lệnh chấm bài | `--gpus '"device=0,1"' --network none --shm-size=16g --entrypoint bash -v …:/data:ro -v …:/result` |
| Thời gian | 6 giờ cho toàn bộ private test, gồm tải model |
| Model | Tổng ≤ 15B tham số cho **mọi** model inference (language, embedding, reranking, classification; mọi tham số MoE); được quantization; weight phát hành trước 2026-10-26 với license cho phép |
| Image | `linux/amd64`; tar chưa nén từ `docker save` ≤ 100 GB |
| Bị cấm | Hard-code đáp án; logic dựa trên ID câu hỏi/doanh nghiệp; training trên test; thu thập đáp án test |

### 2.6 Khả năng tái lập và quy trình nộp (DG §1, §6, §11)
- **[REQ]** Nộp và **đóng băng** image trước khi công bố private test, **sau đó chạy image đó** trên private test và upload `submission.jsonl`. Lần chạy lại của ban tổ chức quyết định điểm cuối.
- **[REQ]** |PA(uploaded) − PA(re-run)| ≤ 0.03; chênh lớn hơn mà không giải thích được sẽ bị loại. Với N = 500, giới hạn này là ≤ 15 điểm ròng: khoảng 7 lần đổi đúng↔sai hoặc 15 lần đổi đúng↔abstain.
- **[REQ]** Phân hạng khi bằng điểm: tổng thời gian inference trong lần chạy lại của ban tổ chức thấp hơn, rồi thời điểm nộp sớm hơn (DG §7).
- **[REQ]** Sau deadline, không được đổi bất kỳ thứ gì trong image, mã, config, model hoặc artifact training (DG §11).

---

## 3. Quyết định đã duyệt

| ID | Quyết định | Trạng thái | Hệ quả kiến trúc |
|---|---|---|---|
| **DEC-1** | Kiến trúc hybrid (Phương án E của v1) | **[APPROVED]** | §5–§7 |
| **DEC-2** | DuckDB SQL là chính; Python fallback có giới hạn | **[APPROVED]** | §7.3; fallback thuộc Phase 2 |
| **DEC-3** | Chọn model dựa trên bằng chứng, tương thích Colab | **[APPROVED] quy trình**; kết quả trước 2026-11-09 | §8 bake-off trên Colab G4 |
| **DEC-5** | Xử lý thời gian tất định | **[APPROVED]** | §7.1; LLM trích xuất biểu thức, code xác định ngày |
| **DEC-6** | Quy tắc theo split; không hard-code từ training rulebook | **[APPROVED]** | §7.2 |
| **DEC-7** | Ensemble nằm ngoài critical path ban đầu | **[APPROVED] hoãn** | Chỉ Phase 3, có gate |
| **DEC-9** | Fine-tuning ngoài critical path ban đầu | **[APPROVED] hoãn** | Chỉ Phase 3, quyết định triển khai ngày 2026-11-12 |
| **DEC-12** | Giữ deadline 2026-11-16; nộp bản dự phòng trước | **[APPROVED]** | §11 |
| — | Baseline end-to-end hoạt động được là ưu tiên cao nhất | **[APPROVED]** | Định nghĩa Phase 1 tại §10 |
| — | Định dạng đáp án chính xác và tuân thủ evaluation | **[APPROVED]** | §7.5, §7.6, §9 |

Quyết định còn mở (DEC-4, DEC-8, DEC-10, DEC-11, DEC-13, DEC-14) được liệt kê tại §13.

---

## 4. Môi trường

Nhóm phát triển trên Google Colab, build image ở nơi khác và được chấm trên 2 × RTX 5090 trong Docker. Kiến trúc phải đúng trong cả ba môi trường.

### 4.1 Ma trận môi trường
| Môi trường | Phần cứng | Docker | Mạng | Mục đích |
|---|---|---|---|---|
| **E1 Colab G4** | 1 × RTX PRO 6000 Blackwell, 96 GB, **sm_120** [OBS] | Không [OBS] | Có | Chính: tương thích kernel, benchmark runtime, test determinism, bake-off |
| **E2 Colab A100 / H100** | 1 × 40/80 GB, sm_80 / sm_90 | Không | Có | Thử nghiệm độ chính xác khi không có G4 |
| **E3 Colab CPU / laptop** | CPU | Tùy môi trường | Có | Ingestion, temporal resolver, scorer, formatter, unit test |
| **E4 Build host** | Linux x86_64 bất kỳ, ≥ 200 GB ổ đĩa trống; không cần GPU | Có | Có | `docker build`, `docker save`, checksum, upload |
| **E5 Host diễn tập / chạy private** | **GPU sm_120**, lý tưởng là 2 × RTX 5090 | **Có**, với NVIDIA Container Toolkit | Tắt lúc chạy | Diễn tập đúng lệnh chấm bài; chạy image đã đóng băng trên private test |
| **E6 Ban tổ chức** | 2 × RTX 5090, 512 GB RAM | Có | Không | Chạy lại chính thức |

- **[OBS]** Colab liệt kê runtime G4 dùng RTX PRO 6000 (Blackwell). RTX PRO 6000 và RTX 5090 đều báo compute capability 12.0, nên kernel chạy được trên G4 là chỉ báo tốt cho môi trường đích. Băng thông bộ nhớ G4 (~1.6 TB/s) thấp hơn đôi chút so với RTX 5090 (~1.8 TB/s), nên decode throughput đo trên G4 có thể hơi thận trọng. **[HYP]** Cần xác nhận bằng một benchmark trên E5.
- **[OBS]** Colab không hỗ trợ chạy Docker container trực tiếp. Có workaround rootless (udocker, Apptainer với `--nv`) nhưng không chính thức.
- **Chưa xác định E5.** Xem RISK-1 và DEC-14.

### 4.2 Quy tắc thiết kế do Colab đặt ra
| Đặc điểm Colab | Quy tắc kiến trúc |
|---|---|
| Một GPU mỗi runtime | Serving phải hoạt động bằng **replica một GPU độc lập**. Baseline không dùng tensor parallelism (DEC-13). Chỉ kiểm thử hành vi hai GPU trên E5. |
| G4 có 96 GB, đích có 32 GB | Mọi benchmark đặt `gpu_memory_utilization` của vLLM để ngân sách engine tương đương đích (≈ 0.30 trên 96 GB ≈ 0.90 × 32 GB), cùng `max_model_len` và `max_num_seqs` cố định. Loại config chỉ hoạt động khi có nhiều bộ nhớ hơn. |
| Không Docker | Colab chạy **cùng Python package và cùng dependency lock đã pin** như image, trong virtual environment cô lập. Lock được tạo từ base image đã chọn (`pip freeze` trong container) để khớp phiên bản thư viện. |
| Có mạng | Mọi harness run đặt `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` và tải model từ local path, để phụ thuộc mạng ngoài ý muốn gây lỗi ngay trên Colab thay vì máy ban tổ chức. |
| Session tạm thời, giới hạn quota | Harness **resume được**: append kết quả theo câu hỏi (cùng atomic writer của production), tiếp tục từ câu hỏi hoàn tất cuối. Weight và training split được cache trên Google Drive, sao chép sang ổ local đầu session. |
| SKU GPU khác nhau giữa session | Mỗi run record lưu tên GPU, driver, CUDA, vLLM và revision model. So sánh độ chính xác giữa SKU có giá trị cho quyết định phát triển; **số đo runtime và determinism chỉ có giá trị từ G4 hoặc E5**. |

---

## 5. Tổng quan kiến trúc

### 5.1 Các cấp xử lý
```
Build time (offline, baked into image)
  model weights · prompt templates · few-shot bank (training split only)
  Vietnamese abbreviation lexicon · frozen run configuration

Split startup (once per run)
  rulebook.md (verbatim) ─► RuleProfile (Phase 2)      calendar.csv ─► LunarCalendar
  start model replicas (GPU0, GPU1)

Business startup (once per business, cached under /tmp)
  discover files ─► ingest ─► DuckDB ─► profile ─► SchemaCard
                                         └─► SemanticAnnotations + validated views (Phase 2)
                                         └─► EntityIndex (Phase 2)

Per question
  normalize ─► parse (QuestionFrame) ─► resolve time ─► link entities
  ─► solve (SQL; Python fallback) ─► execute (sandbox) ─► verify ─► decide
  ─► format ─► persist submission line + log record
```

### 5.2 Sơ đồ component
```
                         ┌──────────────────────────────────────────────┐
 /data (ro) ──────────►  │ C1 Split Bootstrap   C2 Ingestion & Catalog   │
                         │ C3 Semantic Compiler (P2)  C6 Entity Linker   │
                         └──────────────┬───────────────────────────────┘
                                        │ SplitContext, BusinessCatalog
 questions.jsonl ─► C12 Orchestrator ───┤
                   (scheduler, budget)  ▼
                         ┌──────────────────────────────────────────────┐
                         │ C4 Question Parser ─► C5 Temporal Resolver    │
                         │ C7 Solver ◄──► C8 Sandbox Executor            │
                         │ C9 Verifier & Decision ─► C10 Formatter       │
                         └──────────────┬───────────────────────────────┘
                                        ▼
                         C11 Persistence & Compliance Logging ─► /result
 C13 Model Serving (replica GPU0, replica GPU1) ◄── used by C3, C4, C7
 C14 Evaluation Harness & Local Scorer (development only, not on the inference path)
```

### 5.3 Nguyên tắc thiết kế
1. **Tất định ở nơi quy tắc tổng quát.** Ngày, xếp hạng, tie-break, xác định kiểu, làm tròn và serialization được thực hiện bằng code, không phải output model.
2. **Model chỉ reasoning ở nơi schema đặc thù.** LLM suy ra vai trò table, ý nghĩa cột và logic truy vấn từ bằng chứng profiling.
3. **Rulebook là dữ liệu.** Luôn truyền nguyên văn; code không chứa tham số training rulebook.
4. **Khi lỗi thì abstain.** Mọi tình huống chưa xử lý sinh `abstain`, không crash và không đoán.
5. **Log được capture, không dựng lại.** Mọi chuỗi log xuất phát từ đúng object do model hoặc executor trả về.
6. **Cùng code path ở mọi nơi.** Colab, E5 và ban tổ chức chạy cùng entry point với cùng config đã đóng băng.

---

## 6. Component

Chú giải phase: **P1** baseline (bắt buộc cho lần chạy end-to-end đầu tiên), **P2** độ chính xác, **P3** tùy chọn và có gate.

| ID | Component | Trách nhiệm | Phase | Phụ trách |
|---|---|---|---|---|
| C1 | Split Bootstrap | Tải rulebook nguyên văn; tải calendar; (P2) trích xuất và xác thực RuleProfile | P1 / P2 | M2 |
| C2 | Ingestion & Catalog | Đọc CSV/XLSX/SQLite; parse số và ngày tiếng Việt; materialize DuckDB; profile; tạo SchemaCard | P1 | M1 |
| C3 | Semantic Compiler | Annotation từng doanh nghiệp và view đã xác thực cho định nghĩa cốt lõi của rulebook | P2 (DEC-4) | M1 |
| C4 | Question Parser | LLM → QuestionFrame (type đáp án, metric, mention, biểu thức thời gian, đặc tả xếp hạng) | P1 | M3 |
| C5 | Temporal Resolver | Khoảng ngày tất định từ `as_of_date`, rulebook, calendar | P1 cốt lõi / P2 âm lịch | M2 |
| C6 | Entity Linker | Retrieval ứng viên fuzzy, bỏ dấu, trên giá trị và code thực tế | P2 | M1 |
| C7 | Solver | Dựng context pack; LLM viết DuckDB SQL; repair giới hạn; (P2) Python fallback | P1 / P2 | M3 |
| C8 | Sandbox Executor | Chạy SQL/Python trong subprocess có truy cập read-only và giới hạn tài nguyên | P1 | M3 |
| C9 | Verifier & Decision | Kiểm tra type contract và tính hợp lý; trả lời / `unanswerable` / abstain | P1 quy tắc / P3 học | M2 |
| C10 | Formatter | Serialization chuẩn theo type | P1 | M2 |
| C11 | Persistence & Logging | Ghi submission và log atomic; trường tuân thủ | P1 | M4 |
| C12 | Orchestrator | Nhóm câu hỏi, concurrency, deadline, degrade mode, global stop | P1 | M4 |
| C13 | Model Serving | Replica vLLM, client, thiết lập decoding tất định | P1 | M4 (replica), M3 (client) |
| C14 | Evaluation Harness | Scorer local, grouped CV, phân tích lỗi, run record | P1 | Lead |

### 6.1 C1 Split Bootstrap
- **P1.** Đọc `rulebook.md` thành chuỗi UTF-8, chuẩn hóa NFC, không chỉnh sửa. Tải `calendar.csv` vào bảng tra dương↔âm lịch trong bộ nhớ có validation (ngày đơn điệu, không có khoảng trống trong dải dữ liệu).
- **P2.** Dùng LLM trích xuất **RuleProfile** (ngày đầu tuần, tính bao hàm của “tháng này”, định nghĩa khoảng ngày lễ, tiêu chí xếp hạng mặc định, định nghĩa doanh thu và chi phí dưới dạng văn bản trích dẫn), rồi xác thực: mỗi trường phải dẫn một span trong rulebook; trường enum phải nhận giá trị được phép. Trường không qua validation được đánh dấu `unresolved`; consumer fallback về rulebook nguyên văn.
- **Hành vi khi lỗi.** Calendar thiếu hoặc không đọc được: câu hỏi phụ thuộc âm lịch abstain; câu khác tiếp tục.

### 6.2 C2 Ingestion & Catalog
- Phát hiện file, encoding và dialect CSV, đọc mọi sheet XLSX (phát hiện dòng header, dòng tổng, nhiều bảng), attach SQLite read-only.
- Parsing theo locale (`1.250.000`, `1,5`, `150k`, `1tr2`), suy ra định dạng ngày từ miền giá trị, ngày Excel serial. **Giữ cột raw cạnh cột đã parse**; không ép kiểu âm thầm.
- Output: file DuckDB theo doanh nghiệp dưới `/tmp/datamate/<run>/<business>/` và **SchemaCard** (table, cột, type, tỷ lệ null, miền giá trị, giá trị phân biệt cho cột ít giá trị, dòng mẫu, candidate key, join suy ra, cảnh báo ingestion).
- Ngân sách: **[PROP]** ≤ 60 giây/doanh nghiệp ở 300k dòng trên CPU đích; đọc XLSX bằng reader nhanh (nhóm calamine). Ingestion doanh nghiệp chạy chồng thời gian với xử lý câu hỏi của doanh nghiệp khác.

### 6.3 C13 Model Serving
- **[PROP] Topology (DEC-13).** Hai server vLLM tương thích OpenAI trên `127.0.0.1`, mỗi GPU một server (`CUDA_VISIBLE_DEVICES=0` và `=1`), khởi động bởi `predict.sh`, mỗi server giữ bản sao model đầy đủ. Baseline không dùng tensor parallelism và NCCL.
  - Lý do: kiểm thử được trên một GPU Colab; tránh NCCL treo khi khởi tạo, thiếu P2P và lỗi `/dev/shm` trong DG §9–10; tăng gấp đôi throughput nếu model vừa 32 GB.
  - **[HYP]** Loopback hoạt động dưới `--network none`. Xác minh trong diễn tập E5 đầu tiên; fallback là engine in-process (`AsyncLLM`) với cùng client interface.
- **Dự phòng.** Nếu model đã chọn không vừa một GPU 32 GB với KV cache đủ dùng, dùng tensor parallelism trên cả hai GPU với workaround DG §9 (`nvidia-nccl-cu12==2.27.7`, `NCCL_P2P_DISABLE=1`), chấp nhận luồng này chỉ xác thực được trên E5.
- **Client.** Một `ModelClient` dùng chung cho C1, C3, C4 và C7. Đặt tường minh mọi tham số decoding, không dựa vào default của server hoặc chat template (kể cả thinking switch); trả raw content, reasoning content, số token và finish reason để log.
- **Khởi động.** Hai replica tải song song; số liệu tham chiếu khoảng 2 phút cho Qwen3-14B, gồm capture CUDA graph (DG §7). Kiểm tra readiness bằng warm-up prompt tất định.

### 6.4 C4 Question Parser
- Input: câu hỏi gốc, `as_of_date`, rulebook, tóm tắt SchemaCard.
- Output: **QuestionFrame** dưới dạng JSON ràng buộc (vLLM guided decoding theo JSON Schema): type đáp án kỳ vọng, mô tả metric, entity mention, biểu thức thời gian raw, grouping, k và chiều xếp hạng, đặc tả so sánh, cùng `answerability_hint` nêu trường mà câu hỏi cần.
- Chuẩn hóa từ vựng nhẹ (mở rộng viết tắt từ lexicon) trên **bản sao**; luôn giữ và truyền câu hỏi gốc cho model.

### 6.5 C5 Temporal Resolver
Xem §7.1.

### 6.6 C6 Entity Linker (P2)
- Index giá trị phân biệt và code theo từng cột text, lập khóa bằng token viết thường đã bỏ dấu (chỉ retrieval, DEC-11), chấm fuzzy bằng character n-gram.
- Output: ứng viên được xếp hạng `(table, column, value, code, score)` truyền cho solver. **Xuất giá trị đúng như lưu trữ**, bao gồm dấu tiếng Việt.
- **Thay thế trong P1.** Danh sách giá trị phân biệt của SchemaCard nằm trong context pack; model tự đối sánh.

### 6.7 C7 Solver và C8 Sandbox Executor
Xem §7.3.

### 6.8 C9 Verifier & Decision
Xem §7.4.

### 6.9 C10 Formatter
Xem §7.5.

### 6.10 C11 Persistence & Logging
Xem §7.6.

### 6.11 C12 Orchestrator
- Đọc mọi câu hỏi, nhóm theo doanh nghiệp và sắp doanh nghiệp tất định (chỉ dùng business identifier làm khóa thứ tự; ID không bao giờ ảnh hưởng logic đáp án, DG §5.4).
- Gán doanh nghiệp cho replica bằng quy tắc cố định (cân bằng greedy theo số câu hỏi, hòa thì theo thứ tự). Phân công chỉ phụ thuộc file input, nên giống nhau giữa các lần chạy.
- Concurrency cố định trên mỗi replica, đặt trong config đóng băng, không thích ứng khi chạy.
- Deadline: giới hạn soft và hard cho từng câu; bộ giám sát thời điểm hoàn thành dự kiến kích hoạt **degrade mode** (không repair, không fallback) khi chậm mục tiêu; tại global hard stop (mặc định 5 giờ 30 phút sau khởi động), ghi mọi câu còn lại thành `abstain`.
- Cô lập crash: exception trong pipeline của câu hỏi tạo `abstain` cho câu đó, kèm log lỗi; lỗi cấp doanh nghiệp tạo `abstain` cho các câu của doanh nghiệp đó.

### 6.12 C14 Evaluation Harness
- Scorer local triển khai chính xác Brief §2.1–2.2, unit test trên mọi ví dụ Brief. Đây là nguồn chuẩn duy nhất cho metric phát triển.
- Cross-validation 5 fold nhóm theo doanh nghiệp; evaluation bỏ riêng một loại hình kinh doanh; (P2) bộ perturbation test rulebook.
- Run record: hash config, commit code, revision model, fingerprint môi trường, kết quả từng câu, runtime.
- Chỉ dùng public leaderboard để kiểm tra sơ bộ end-to-end (≤ 5/ngày); không tuning theo bảng và không dò đáp án (Brief §5.2.6).

---

## 7. Chi tiết thiết kế chính

### 7.1 Xử lý thời gian (DEC-5, đã duyệt)
- **LLM trích xuất** nguyên văn biểu thức thời gian vào QuestionFrame. **Code xác định** khoảng ngày `[start, end]` bao gồm hai biên, với độ chi tiết (`day`, `week`, `month`, `quarter`, `year`, `lunar-window`).
- Tham số (đầu tuần, tính bao hàm của kỳ hiện tại, “tuần trước” so với “7 ngày qua”, cùng kỳ năm trước, khoảng lễ) lấy từ rulebook: P1 dùng bộ nhỏ **tham số được parser điền từ văn bản rulebook nguyên văn**; P2 dùng RuleProfile đã xác thực. Không biên dịch default của training rulebook vào code.
- **Phạm vi P1:** ngày và tháng tường minh, ngày/tuần/tháng/quý/năm tương đối, kỳ từ đầu đến nay, cùng kỳ năm trước, so sánh hai khoảng.
- **Phạm vi P2:** khoảng âm lịch và ngày lễ qua `calendar.csv` (Tết qua hai năm dương lịch, Trung thu, tháng âm lịch nhuận).
- **Biểu thức không giải quyết được:** P1 → `abstain`. P2 → model đề xuất window và giải thích từ rulebook; resolver xác thực bằng calendar và độ phủ dữ liệu; kết quả được gắn cờ, giảm confidence.
- **Kiểm tra độ phủ:** nếu window nằm toàn bộ hoặc một phần ngoài dải dữ liệu doanh nghiệp, tỷ lệ giao nhau trở thành feature verifier. Hành vi tham chiếu cho window ngoài phạm vi (`0` hay `unanswerable`) được rút ra từ đáp án training (Q7).

### 7.2 Xử lý rulebook (DEC-6, đã duyệt)
- Rulebook nguyên văn có trong mọi context pack model, thuộc prefix dùng chung (phù hợp prefix cache).
- Component tất định không giữ hằng số quy tắc; nhận tham số từ C1.
- Bộ perturbation test rulebook (P2) thay tham số quy tắc trên câu hỏi tổng hợp có đáp án tính bằng chương trình, xác minh output theo rulebook được mount.

### 7.3 Giải bài và thực thi (DEC-2, đã duyệt)
- **Context pack** (thứ tự phục vụ tái sử dụng prefix): system instruction → rulebook → SchemaCard (hoặc phần liên quan) → (P2) annotation và view đã xác thực → few-shot từ doanh nghiệp training → câu hỏi, QuestionFrame, window đã giải quyết, entity candidate, type contract.
- **Luồng SQL (P1).** Model viết một truy vấn DuckDB. Quy tắc prompt yêu cầu `ORDER BY` tường minh, tie-break code tăng dần cho mọi kết quả xếp hạng hoặc list, và cấm DDL/DML.
- **Vòng repair (P1).** Tối đa 2 lần repair, kích hoạt do lỗi thực thi, kết quả rỗng khi type contract cấm, hoặc vi phạm type contract. Mỗi repair call được log thành mục riêng trong `thinking` và `code`.
- **Python fallback (P2).** Kích hoạt khi parser đánh dấu câu hỏi cần logic thủ tục, hoặc sau khi repair SQL thất bại. Giới hạn ở pandas/DuckDB trên database doanh nghiệp, tối đa 1 attempt cộng 1 repair.
- **Sandbox (C8, P1).** Subprocess riêng; mở DuckDB **read-only**; thư mục làm việc dưới `/tmp`; giới hạn wall-time (mặc định 20 giây), bộ nhớ, số dòng kết quả; không mạng (vốn đã không có) và không ghi ngoài thư mục tạm. Python fallback chạy với import allow-list. Timeout hoặc vượt giới hạn là lỗi thực thi.
- **Helper đóng gói.** Mã được sinh có thể gọi helper trong `/code/src` (DG §3.3). Log ghi lời gọi thực tế và input.

### 7.4 Xác minh và quyết định (DEC-8 còn mở)
- **Rule gate P1.** Chỉ trả lời nếu thỏa tất cả: thực thi thành công; kết quả đúng type contract; không rỗng và không null; window giao với dải dữ liệu; không có cảnh báo nghiêm trọng từ verifier. Nếu không thì `abstain`.
- **`unanswerable` trong P1** chỉ được xuất khi `answerability_hint` của parser nêu trường bắt buộc **và** kiểm tra catalog tất định xác nhận thiếu trường đó. Mọi nghi ngờ khác thành `abstain`.
- **Feature verifier (P2):** số repair, số dòng, độ hợp lý của độ lớn so với miền cột, điểm entity match, tỷ lệ phủ window, cờ thời gian, việc dùng fallback.
- **Calibrator học từ dữ liệu (P3, có gate).** Model cổ điển nhỏ (logistic regression hoặc monotonic GBT) trên feature verifier, train từ các lần chạy training split với CV nhóm theo doanh nghiệp; chỉ dùng nếu tăng PA held-out so với rule gate. Khai báo trong README và tính vào tổng tham số (không đáng kể).
- **Đồng thuận nhiều chiến lược (P3, DEC-7 hoãn).** Chạy greedy các chiến lược khác nhau; dừng sớm khi hai chiến lược đồng ý. Chỉ dùng nếu tăng PA held-out một mức đo được, đồng thời giữ gate runtime và determinism.

### 7.5 Định dạng
- Mỗi type có một formatter, nhận giá trị có kiểu từ executor, không nhận chuỗi do model viết.
- `number` và `percent`: làm tròn half-up bằng `Decimal` (không làm tròn binary float), quy tắc xuất số nguyên theo Q5.
- `date`: độ chi tiết lấy từ QuestionFrame và window đã giải quyết.
- `list`: sắp theo tiêu chí, hòa thì code tăng dần, cắt tại k.
- `table`: tên cột theo quy ước rút ra từ đáp án tham chiếu training.
- `string`: sao chép từ giá trị dữ liệu; không đổi hoa/thường hoặc dấu.
- JSON output dùng `ensure_ascii=False`, UTF-8, một object mỗi dòng.

### 7.6 Lưu bền vững và log tuân thủ
- **Submission writer.** Append một dòng mỗi câu ngay khi quyết định cuối cùng, sau đó `flush` và `fsync`. Mỗi câu được ghi đúng một lần. Khi khởi động, writer tạo `/result` và `/result/logs` nếu chưa có.
- **Log record** (một dòng JSON mỗi câu trong `/result/logs/questions.jsonl`):

| Trường | Nguồn | Quy tắc |
|---|---|---|
| `id` | Input | — |
| `answer` | Decision | Cùng object với dòng submission |
| `elapsed_ms` | Orchestrator | Số nguyên không âm; từ khi câu vào worker (batch của nó) đến đáp án cuối |
| `thinking` | ModelClient | Reasoning text chính xác theo call, theo thứ tự; list nếu nhiều call; `null` nếu không có |
| `code` | Executor | SQL/Python thực thi chính xác theo từng attempt, theo thứ tự |
| `output` | Executor | Giá trị trả về hoặc output thực thi của attempt cuối |
| `inputs` | Executor | Với helper đóng gói: đối số thực tế |
| `calls` (bổ trợ) | ModelClient | Theo call: stage, prompt hash, finish reason, số token |
| `views_used` (bổ trợ, P2) | Solver | Tên và hash compiled view được tham chiếu |
| `decision_reason` (bổ trợ) | Verifier | Kết quả gate và check thất bại |

- **Log cấp doanh nghiệp** (`/result/logs/businesses.jsonl`): cảnh báo ingestion, hash SchemaCard, DDL compiled view và model call (kèm thinking) tạo ra chúng, thời gian setup. Record từng câu tham chiếu log này, để SQL dùng compiled view được truy về phép tính thực tế.
- **Quy tắc capture.** Chuỗi log lấy từ object do model server và executor trả về. Không diễn đạt lại, rút ngắn hoặc sinh lại.

### 7.7 Tính tất định
- Greedy decoding (`temperature = 0`), `seed`, `max_tokens`, stop sequence cố định và thinking switch tường minh trên mọi call.
- Concurrency cố định; gán doanh nghiệp–replica cố định; thứ tự SQL tất định; `PYTHONHASHSEED`, số thread BLAS và DuckDB cố định; pin phiên bản ở mọi nơi.
- `VLLM_BATCH_INVARIANT=1` **chỉ khi** xác thực thành công trên sm_120 với model đã chọn. **[HYP]** v1 ghi nhận tài liệu vLLM hỗ trợ compute capability ≥ 8.0, nhưng model hybrid linear-attention chưa nằm trong danh sách đã kiểm thử; cần kiểm tra trên G4 (RISK-4).
- **Giảm rủi ro bằng cấu trúc.** Output model chỉ ảnh hưởng đáp án qua SQL text và trường đã parse. Sai lệch số học nhỏ không đổi SQL được sinh thì không đổi đáp án; vì vậy output ngắn có cấu trúc ít nhạy với sai lệch hơn reasoning tự do dài.
- **Gate nghiệm thu** tại §9.

### 7.8 Ngân sách runtime
- **Ngân sách.** 6 giờ = 21.600 giây. **[PROP] Mục tiêu ≤ 2.5 giờ** (9.000 giây) trên phần cứng tham chiếu, dự trù tối đa **1.000 câu hỏi** nếu số lượng vượt ước tính “~500”.
- **Yêu cầu throughput.** 1.000 câu trên 2 replica trong khoảng 8.700 giây xử lý ≈ 17 giây throughput mỗi câu trên mỗi replica.
- **Ước tính token [HYP].** P1 trung bình hai call mỗi câu (parse, solve), thêm repair thỉnh thoảng; khoảng 4k output token mỗi câu với thinking giới hạn → ~4M output token ≈ 460 tok/s tổng. v1 dẫn số liệu cộng đồng ~1.280 output tok/s ở concurrency 64 cho Qwen3.5-9B trên một RTX 5090; nếu đúng, dư địa khoảng 5×. Chi phí prefill phụ thuộc kích thước context pack và tỷ lệ hit prefix cache. **Cả hai được đo tại M1 trên G4 với giới hạn bộ nhớ đích.**
- **Công thức dự báo** (DG §10): tải model + setup doanh nghiệp (phần không chồng thời gian) + (thời gian throughput trung bình mỗi câu × số câu). Phải ≤ 2.5 giờ ở 1.000 câu để vượt gate runtime.

### 7.9 Docker image
- **Base image (DEC-3).** Bản tham chiếu `vllm/vllm-openai:v0.10.1.1` có rủi ro thấp nhất nhưng không serve được Qwen3.5 (recipe vLLM yêu cầu ≥ 0.17.0). Có báo cáo image vLLM chính thức cũ thiếu kernel sm_120, nên **mọi tag mới hơn phải được xác thực trên sm_120 trước khi dùng**, không được mặc định là chạy được.
- **Bố cục** theo DG §4: `/code/predict.sh`, `/code/README.md`, `/code/requirements.txt`, `/code/src/`, `/code/models/`, `/code/training_code/` (có `data_manifest.json` và tuyên bố rõ nếu không training hoặc sinh dữ liệu).
- **Dockerfile** theo mẫu DG §9: `ENTRYPOINT []`, biến môi trường offline, các layer `COPY` riêng với weight trước code, `CMD ["bash", "/code/predict.sh"]`.
- **Ngân sách kích thước [suy ra].** Image mẫu DG là 50.5 GB với thư mục model 28 GB, nên base và dependency khoảng 22 GB. Model BF16 ~20 GB cho tổng ~45 GB, thấp hơn nhiều so với 100 GB. Chỉ đóng gói weight của model đã chọn, vì mọi model có thể tải đều tính vào giới hạn 15B.
- **Build và export (DG §9, §11).** `docker build --platform linux/amd64 -t zaic2026_datamate_<team_name>:final .`; export với `set -o pipefail` trước `docker save | pigz`, đo kích thước chưa nén từ archive và ghi `.md5` trước upload; không đổi tên archive sau đó. `.dockerignore` không được loại dữ liệu training.
- **Upload.** Mẫu DG nén từ 50.6 GB xuống 34.4 GB. Phải hoàn tất upload, download trên máy thứ hai và `md5sum -c` trước 18:00 ngày 11-16 (§11).

---

## 8. Chiến lược model (DEC-3, quy trình đã duyệt)

### 8.1 Ứng viên
Trước khi lựa chọn, phải xác minh lại mọi thông tin dưới đây từ model card và metadata safetensors (đếm tham số từ checkpoint thực tế, ngày phát hành, license, revision hash).

| Model | Tham số gồm mọi tower (cần xác minh) | Weight BF16 (xấp xỉ) | Vừa một GPU 32 GB cùng KV? | Yêu cầu vLLM | Vai trò |
|---|---|---|---|---|---|
| **Qwen3.5-9B** | ~9–10B gồm vision encoder [OBS, nguồn mâu thuẫn] | ~19–20 GB | Có; hybrid attention gợi ý KV nhỏ [HYP] | ≥ 0.17.0 → **không phải** image tham chiếu | Ứng viên hàng đầu |
| **Qwen3-8B** | ~8.2B | ~16.4 GB | Có | Image tham chiếu hỗ trợ | Fallback rủi ro thấp; v1 ghi nhận có trong danh sách batch-invariance được vLLM xác thực |
| **Qwen3-14B** | ~14.8B | ~29.5 GB | **Không** ở BF16; có ở FP8 (~15 GB) [HYP] | Image tham chiếu hỗ trợ | Phương án năng lực cao hơn; cần FP8 quantization hoặc TP=2 |
| Qwen3.5-4B | ~4–5B gồm vision | ~9 GB | Có | ≥ 0.17.0 | Tham chiếu tốc độ; không phải model thứ hai trong baseline |
| Gemma 4 (nhỏ) | Cần xác minh | Cần xác minh | Cần xác minh | Cần xác minh | Chỉ đưa vào nếu xác minh được ngày phát hành, license, kích thước, hỗ trợ vLLM |

- **[OBS]** Không tìm thấy model dense Qwen3.6 dưới 15B; các bản Qwen3.6 từ 27B trở lên, ngoài ngân sách.
- **[OBS]** Nguồn mâu thuẫn về việc model Qwen3.5 nhỏ có bật thinking mặc định hay không. ModelClient đặt tường minh trên mọi call, nên default không ảnh hưởng.
- **Baseline chỉ có một model.** Thêm model thứ hai (ví dụ 9B + 4B) có thể gần giới hạn 15B khi tính vision tower, đồng thời tăng gấp đôi áp lực bộ nhớ mỗi GPU.

### 8.2 Quy trình bake-off (Colab G4, trước 2026-11-09)
1. **Tương thích:** phiên bản vLLM của ứng viên khởi động được trên G4 với giới hạn bộ nhớ đích, serve greedy output, chạy CUDA graph không lỗi.
2. **Determinism:** chạy cùng 200 câu training hai lần ở concurrency production phải tạo dòng submission giống hệt.
3. **Độ chính xác:** PA pipeline P1 trên doanh nghiệp held-out (grouped CV), cùng prompt cho mọi model.
4. **Throughput:** số câu/giờ/replica ở concurrency đích, gồm prefill.
5. **Quy tắc chọn:** chọn PA held-out cao nhất trong các ứng viên vượt 1, 2 và 4 (dự báo ≤ 2.5 giờ cho 1.000 câu). Nếu Qwen3.5-9B không vượt 1 hoặc 2 trước 11-09, chọn Qwen3-8B hoặc Qwen3-14B-FP8 trên image tham chiếu.

### 8.3 Model khác
- **Không embedding model** trong P1/P2. **[HYP]** Entity linking lexical và fuzzy là đủ; chỉ xem xét lại nếu phân tích lỗi cho thấy linking là nguồn lỗi lớn.
- **Fine-tuning (DEC-9, hoãn).** Thử nghiệm LoRA tùy chọn sau khi Phase 1 ổn định, quyết định triển khai vào **2026-11-12**: chỉ dùng nếu tăng PA trên doanh nghiệp held-out ≥ 3 điểm mà không hại runtime hoặc determinism. Khi áp dụng, bắt buộc đầy đủ bộ bằng chứng training DG §8 (mã, config, dữ liệu, log, manifest, checksum); chi phí này phải được tính khi quyết định.

---

## 9. Chiến lược xác thực và tiêu chí nghiệm thu

### 9.1 Xác thực cấp component
| Component | Xác thực | Tiêu chí pass |
|---|---|---|
| C2 Ingestion | File fixture bao phủ dòng tiêu đề, header gộp, dòng tổng, số Việt Nam, ngày mơ hồ, ngày serial; mọi doanh nghiệp training | Mọi fixture parse ra giá trị kỳ vọng; không ép kiểu âm thầm (mỗi parse lỗi được tính trong cảnh báo); ≤ 60 giây/doanh nghiệp ở 300k dòng |
| C5 Temporal | Unit test theo bảng cho từng lớp biểu thức và bộ tham số rulebook; test âm lịch đối chiếu `calendar.csv` | 100% unit test; không lỗi lệch một ngày trong window của câu training (đối chiếu mẫu với tham chiếu) |
| C8 Sandbox | Đoạn mã đối kháng (vòng lặp vô hạn, cấp phát lớn, thử ghi, DDL) | Mỗi đoạn bị dừng hoặc từ chối trong giới hạn; process pool vẫn hoạt động |
| C10 Formatter | Golden test từng type, gồm ca biên làm tròn (x.xx5), phần trăm âm, list rỗng, hòa điểm | 100% |
| C11 Logging | Xác thực schema từng dòng log; kiểm tra bằng nhau từng byte giữa model text trả về và text ghi log | 100% câu có record hợp lệ; không khác biệt |
| C14 Scorer | Mọi ví dụ trong Brief §2 | Khớp 100% |

### 9.2 Gate cấp hệ thống
| Gate | Khi nào | Môi trường | Tiêu chí |
|---|---|---|---|
| **G0 Scorer** | M0, 11-07 | E3 | Scorer vượt mọi ví dụ Brief |
| **G1 Tương thích** | M1, 11-09 | E1 (G4) | Model và phiên bản vLLM đã chọn serve trên sm_120 trong giới hạn 32 GB |
| **G2 Baseline** | M1, 11-09 | E1 | Xử lý mọi câu training không crash; 100% dòng submission và log record hợp lệ; báo cáo PA theo type và category |
| **G3 Runtime** | M1 rồi mọi mốc | E1, sau đó E5 | Dự báo ≤ 2.5 giờ cho 1.000 câu (§7.8) |
| **G4 Determinism** | M2, 11-11 | E1 | Hai lần chạy training đầy đủ: file submission giống hệt, hoặc trường hợp xấu nhất \|ΔPA\| ≤ 0.005 |
| **G5 Giá trị của gate** | M2, 11-11 | E1 | PA rule gate ≥ PA trả lời mọi câu trên doanh nghiệp held-out |
| **G6 Diễn tập container** | M3, 11-13 | **E5** | Đúng lệnh chấm DG §10, `--network none`, `/data:ro`, cả hai GPU, toàn bộ training split: chạy xong, output/log hợp lệ, runtime đạt G3, khớp E1 trong \|ΔPA\| ≤ 0.01 |
| **G7 Chạy lại** | M3–M4 | **E5** | Hai lần chạy container cùng input: file submission giống hệt, hoặc \|ΔPA\| ≤ 0.005 |
| **G8 Đóng gói** | M4, 11-15 | E4 | Image `linux/amd64`; tar chưa nén ≤ 100 GB; khai báo model trong README đầy đủ; `training_code/` đầy đủ; xác minh md5 từ máy thứ hai |

Gate chất lượng dùng PA held-out, không dùng điểm public leaderboard. Chưa đặt mục tiêu PA tuyệt đối trước khi có baseline M1.

### 9.3 Khả năng truy vết (yêu cầu → component → xác thực)
| Yêu cầu | Component | Xác thực bằng |
|---|---|---|
| Type và định dạng exact-match | C4, C9, C10 | Golden test C10, PA theo type G2 |
| Quy tắc theo split | C1, C3, C5 | Bộ perturbation test (P2), test C5 |
| Loại hình kinh doanh chưa gặp | C2, C3, C7 | Leave-type-out CV |
| Offline, read-only, entry point không đối số | C11, C12, C13, image | G6 |
| Log từng câu với thinking/code/output thực tế | C7, C8, C11, C13 | So sánh byte C11, G6 |
| Giới hạn 6 giờ gồm tải model | C12, C13 | G3, G6 |
| \|ΔPA\| ≤ 0.03 | C12, C13, §7.7 | G4, G7 |
| ≤ 15B tham số; license; ngày phát hành | §8 | Review khai báo G8 |

---

## 10. Bàn giao theo phase và ưu tiên

| Phase | Nội dung | Hoàn thành | Quy tắc |
|---|---|---|---|
| **P1 Baseline** | C1 (nguyên văn), C2, C4, C5 (cốt lõi dương lịch), C7 (SQL + repair), C8, C9 (rule gate), C10, C11, C12, C13, C14 | G0–G3 trước **11-09** | Một nhánh công việc không bắt đầu P2/P3 cho đến khi sản phẩm P1 của mình vượt test |
| **P2 Độ chính xác** | RuleProfile, window âm lịch, C6, compiled view C3 (DEC-4), Python fallback, feature verifier, prompt và few-shot từ phân tích lỗi | G4–G5 trước **11-11** | Mỗi tính năng chỉ merge nếu PA held-out không giảm và được điều khiển bằng config switch |
| **P3 Tùy chọn** | Calibrator học từ dữ liệu, đồng thuận nhiều chiến lược, LoRA | Quyết định triển khai **11-12** | Chỉ dùng khi đo được cải thiện và vượt G3/G4 |
| **Đóng băng** | Chỉ sửa bug | **11-13** sau G6 | Mọi thay đổi sau đóng băng yêu cầu chạy lại G6/G7 |

Thứ tự ưu tiên khi thiếu thời gian: **tuân thủ và hợp lệ → determinism → runtime → độ chính xác**. Submission hợp lệ, tái lập được với PA vừa phải có giá trị hơn hệ thống mạnh hơn nhưng không vượt G6.

---

## 11. Các mốc

| Mốc | Ngày | Tiêu chí hoàn thành |
|---|---|---|
| **M0 Nền tảng** | Thứ Bảy 11-07 | Repository skeleton; đóng băng contract v0; G0; báo cáo kiểm tra training split; môi trường Colab với lock pin phiên bản; **xác định host E5 (DEC-14)** |
| **M1 Baseline** | Thứ Hai 11-09 | G1–G3; **quyết định model và base image (DEC-3)** |
| **M2 Độ chính xác** | Thứ Tư 11-11 | Merge hoặc bỏ tính năng P2; G4, G5 |
| **M3 Diễn tập + đóng băng** | Thứ Sáu 11-13 | G6; đóng băng tính năng |
| **Nộp bản dự phòng** | Thứ Bảy 11-14 | Upload giải pháp #1 và xác minh checksum |
| **M4 Bản ứng viên cuối** | Chủ nhật 11-15 | G7, G8; README và khai báo hoàn chỉnh |
| **M5 Bản cuối** | Thứ Hai 11-16, mục tiêu 18:00 | Upload image cuối, xác minh md5 từ máy thứ hai, nộp biểu mẫu sớm trước 23:59 |

Nhóm gồm một Lead và bốn thành viên (`IMPLEMENTATION_PLAN.md` §2):

| Vai trò | Phụ trách | Component |
|---|---|---|
| **Lead** | Contract, scorer và harness, CI, tích hợp, quyết định, nộp bài | C14 |
| **M1** Dữ liệu và ngữ nghĩa | `ingest/`, `catalog/`, `entities/`, `lexicon/`, `semantics/` | C2, C3, C6 |
| **M2** Quy tắc, thời gian và câu trả lời | `rules/`, `temporal/`, `decision/`, `formatting/` | C1, C5, C9, C10 |
| **M3** Reasoning Engine | `llm/client.py`, `prompts/`, `parse/`, `solver/`, `sandbox/` | C4, C7, C8, client C13 |
| **M4** Nền tảng và tuân thủ | `run.py`, `config.py`, `runtime/`, `llm/replicas.py`, Docker, tài liệu tuân thủ | C11, C12, replica C13 |

Interface contract ở §14 nằm trong một module dùng chung do Lead phụ trách; thay đổi cần Lead duyệt. Seam giữa các thành viên, đối tượng thay thế và test tương thích được mô tả tại `ARCHITECTURE.md` §10.

---

## 12. Danh mục rủi ro

Khả năng xảy ra (L) và tác động (I): H (cao) / M (trung bình) / L (thấp).

| ID | Rủi ro | L | I | Giảm thiểu | Ngưỡng kích hoạt / dự phòng | Phụ trách |
|---|---|---|---|---|---|---|
| **RISK-1** | **Không có host sm_120 chạy Docker** để diễn tập G6 và chạy image đóng băng trên private test; Colab không chạy Docker | **H** | **H** | Chốt E5 trước 11-07 (DEC-14): workstation RTX 5090 của thành viên, cloud VM RTX PRO 6000 hoặc RTX 5090 hỗ trợ Docker đầy đủ, hoặc thuê bare-metal | Nếu chưa có E5 trước 11-09: thử Apptainer `--nv` trên Colab G4 với image export **[HYP]**, chấp nhận mức tương đồng thấp hơn | M4 |
| **RISK-2** | **Sai lệch giữa SKU.** Lần chạy upload (E5) và chạy lại của ban tổ chức (2 × 5090) có thể khác nếu E5 không phải RTX 5090 | M | H | Ưu tiên RTX 5090 cho E5; output có cấu trúc ngắn; batch-invariant mode nếu hợp lệ | Đo chênh G4 và E5 trên training split; nếu \|ΔPA\| > 0.01, giảm độ dài sinh và concurrency | M4 |
| **RISK-3** | Image vLLM mới cần cho Qwen3.5 không chạy được trên sm_120 hoặc trong container | M | H | Xác thực trên G4 tại M1; chuẩn bị model fallback trên image tham chiếu | Fallback Qwen3-8B hoặc Qwen3-14B-FP8 trên `v0.10.1.1` | M4 |
| **RISK-4** | Batch-invariant mode không hỗ trợ model (hybrid) đã chọn, gây sai lệch giữa lần chạy | M | H | Test trên G4; giảm thiểu bằng cấu trúc §7.7 | Giảm concurrency; chuyển sang model thuộc danh sách đã xác thực | M4 |
| **RISK-5** | Tình trạng sẵn có hoặc quota Colab G4 cản benchmark | M | M | Đặt session sớm; harness resume; làm thử nghiệm độ chính xác trên A100/H100 | Chỉ lấy số runtime từ E5 | Lead |
| **RISK-6** | Rulebook private khác theo cách RuleProfile hoặc prompt xử lý sai | M | H | Rulebook nguyên văn trong mọi context; bộ perturbation test | Fallback từng tham số về văn bản nguyên văn; câu bị ảnh hưởng abstain | M2 |
| **RISK-7** | Loại hình kinh doanh chưa gặp làm hỏng ingestion hoặc giả định ngữ nghĩa | M | H | Thiết kế theo schema; leave-type-out CV; cảnh báo ingestion | Lỗi cấp doanh nghiệp → abstain các câu doanh nghiệp đó, không crash | M1 |
| **RISK-8** | Compiled view mã hóa cách hiểu quy tắc sai (lỗi tương quan) | M | M | Kiểm tra invariant; kill switch theo category | Tắt view theo category | M1 |
| **RISK-9** | Scorer mơ hồ (int/float, chiều phần trăm, mã hóa boolean) | M | M | Gửi Q5 cho ban tổ chức; rút ra từ tham chiếu training | Theo quy ước đáp án training | Lead |
| **RISK-10** | Vượt runtime private test (nhiều câu hơn, doanh nghiệp lớn hơn) | L | H | Mục tiêu 2.5 giờ ở 1.000 câu; degrade mode; global hard stop | Abstain câu còn lại; đáp án đã ghi vẫn được tính | M4 |
| **RISK-11** | Bị nghi ngờ độ trung thực log (thinking khác nội dung sinh, thiếu record) | L | H | Capture tại ranh giới client; test bằng nhau từng byte | — | M4 |
| **RISK-12** | Cách hiểu số tham số (vision tower; calibrator) | L | H | Đếm mọi tensor trong checkpoint đóng gói; khai báo README; không đóng gói weight không dùng | Chọn model text-only nếu cách đếm bị tranh luận | M4 |
| **RISK-13** | Môi trường Colab/image không khớp (phiên bản thư viện khác) | M | M | Lock tạo từ base image; fingerprint môi trường trong run record | G6 là chuẩn quyết định | M4 |
| **RISK-14** | Upload chậm hoặc link lỗi gần deadline | M | H | Nộp dự phòng 11-14; upload cuối trước 18:00 ngày 11-16; check md5 máy thứ hai | Nộp lại image dự phòng | M4 |
| **RISK-15** | Interface biến động hoặc tích hợp hỏng giữa năm kỹ sư làm song song trong mười ngày | M | M | Đóng băng contract tại I0, Lead duyệt thay đổi; fake/test double từng seam; conformance và consumer test; quy tắc public API; merge window hằng ngày; determinism CI (`ARCHITECTURE.md` §10) | Bàn giao trễ → consumer dùng đối tượng thay thế; Lead làm cùng producer | Lead |

---

## 13. Danh mục quyết định

| ID | Quyết định | Trạng thái | Khuyến nghị | Cần trước |
|---|---|---|---|---|
| DEC-1 | Kiến trúc hybrid | **APPROVED (đã duyệt)** | — | — |
| DEC-2 | SQL chính, Python fallback giới hạn | **APPROVED** | — | — |
| DEC-3 | Model và base image | **Quy trình APPROVED; kết quả OPEN (chưa chốt)** | Bake-off §8.2; ưu tiên Qwen3.5-9B nếu vượt G1, G3, G4 | 11-09 |
| **DEC-4** | Compiled view theo doanh nghiệp | **OPEN** | Dùng trong P2 dưới switch theo category, chỉ nếu PA held-out tăng | 11-11 |
| DEC-5 | Giải quyết thời gian tất định | **APPROVED** | — | — |
| DEC-6 | Quy tắc theo split, không hard-code | **APPROVED** | — | — |
| DEC-7 | Ensemble | **APPROVED việc hoãn** | Chỉ P3 | 11-12 |
| **DEC-8** | Chính sách abstain | **OPEN** | Rule gate P1 (§7.4); ngưỡng học chỉ trong P3 | 11-09 |
| DEC-9 | Fine-tuning | **APPROVED việc hoãn** | Quyết định 11-12, ≥ +3 PA | 11-12 |
| **DEC-10** | Thinking mode | **OPEN** | Tắt khi parsing; ngân sách giới hạn cho solving chỉ nếu tăng PA và đạt runtime gate | 11-09 |
| **DEC-11** | Chỉ accent folding cho entity retrieval key | **OPEN** | Phê duyệt; chuẩn hóa chấm điểm và chuỗi output giữ dấu. Cần đối chiếu quy tắc dấu trong `CLAUDE.md` | 11-07 |
| DEC-12 | Deadline và nộp dự phòng | **APPROVED** | — | — |
| **DEC-13** | Topology serving | **OPEN (mới)** | Hai replica một GPU độc lập; TP=2 chỉ dự phòng | 11-07 |
| **DEC-14** | Host diễn tập và chạy private (E5) | **OPEN (mới), thiết yếu** | Đảm bảo host sm_120 chạy Docker, ưu tiên 2 × RTX 5090 | **11-07** |

---

## 14. Interface contract

Schema cấp trường được xác định trong `SPEC.md`. Mục này ấn định người phụ trách và các trường mỗi consumer dựa vào.

| Contract | Producer → Consumer | Trường bắt buộc | Invariant |
|---|---|---|---|
| `RunConfig` | Image → tất cả | Đường dẫn model, revision, tham số decoding, seed, concurrency, giới hạn, feature switch | Đóng băng trong image; `predict.sh` không nhận đối số |
| `SplitContext` | C1 → tất cả | Văn bản rulebook, hash rulebook, RuleProfile (P2, có thể một phần), LunarCalendar | Không chỉnh sửa văn bản rulebook |
| `BusinessCatalog` | C2 → C3–C9 | Đường dẫn DuckDB, table, metadata cột (raw và đã parse), văn bản SchemaCard, dải ngày dữ liệu, cảnh báo | Read-only sau khi tạo |
| `SemanticAnnotations` | C3 → C7 | Vai trò table, ngữ nghĩa giá trị, đường join, view cùng DDL và kết quả validation | Chỉ cung cấp view đã xác thực |
| `QuestionFrame` | C4 → C5–C10 | Contract type đáp án, metric, mention, biểu thức thời gian raw, đặc tả xếp hạng, gợi ý answerability | JSON ràng buộc bằng schema |
| `TimeWindow` | C5 → C7, C9 | Start/end bao gồm hai biên, độ chi tiết, provenance (nguồn quy tắc), tỷ lệ phủ, cờ | start ≤ end; ngày ISO |
| `EntityCandidates` | C6 → C7 | Mention → (table, column, value, code, score) xếp hạng | Giá trị đúng như lưu trữ |
| `SolverAttempt` | C7/C8 → C9, C11 | Strategy, prompt hash, raw output, thinking, code, execution output, error, duration | Một record mỗi attempt, theo thứ tự |
| `Decision` | C9 → C10, C11 | Giá trị có kiểu hoặc `unanswerable`/`abstain`, reason, feature | — |
| `SubmissionRecord` | C10 → C11 | `id`, `type`, `answer` (`reason` tùy chọn) | Đúng DG §3.2 |
| `LogRecord` | C11 → `/result/logs` | `id`, `answer`, `elapsed_ms`, `thinking`, `code`, `output` (+ trường bổ trợ §7.6) | Đúng DG §3.3; capture, không dựng lại |

---

## 15. Đánh đổi triển khai

| Chủ đề | Lựa chọn | Phương án khác | Lý do chọn | Chi phí chấp nhận |
|---|---|---|---|---|
| Topology serving | 2 × replica một GPU | TP=2 trên hai GPU | Test được trên Colab; không rủi ro NCCL/P2P/shm; throughput 2× | Model phải vừa 32 GB cùng KV |
| Interface serving | Server local tương thích OpenAI | Engine in-process | Cùng client trên Colab và Docker; cô lập process | Phải xác minh loopback dưới `--network none` |
| Ngôn ngữ thực thi | DuckDB SQL | Python agent | Khai báo, tất định, nhanh ở 300k dòng | Logic thủ tục cần fallback (P2) |
| Logic thời gian | Resolver tất định | LLM tính ngày | Chính xác, dễ test | Biểu thức không hỗ trợ abstain đến P2 |
| Confidence | Rule gate (P1) | Calibrator học / ensemble | Đơn giản, vững với ít dữ liệu | Bỏ lỡ một số đáp án có thể khôi phục |
| Base image | Chọn bằng bake-off | Chọn image tham chiếu ngay | Có thể tăng độ chính xác nhờ Qwen3.5 | Thêm bước xác thực tương thích |
| Precision | BF16 mặc định | FP8 / AWQ | Không mất độ chính xác vì quantization | Loại Qwen3-14B một GPU trừ khi dùng FP8 |
| Entity linking | Lexical + fuzzy | Embedding model | Không tốn tham số; tất định | Yếu hơn với mention diễn đạt lại |
| Thinking | Tường minh theo stage | Luôn bật | Runtime và tái lập | Có thể giảm độ chính xác ở câu khó |

---

## 16. Câu hỏi còn mở

1. **(Thiết yếu) Host E5.** Máy sm_120 chạy Docker nào sẽ chạy G6 và image đóng băng trên private test? Có thành viên nào có RTX 5090 sẵn không?
2. Training split đã có local (và trên Google Drive cho Colab) chưa? Có baseline hoặc submission vòng public chưa?
3. Nhóm có gói Colab và ngân sách compute unit nào; có lấy G4 ổn định không?
4. Đã xác nhận kênh upload (link Google Drive công khai) cho archive ~35–45 GB chưa?
5. Ban tổ chức có thể làm rõ xử lý integer/float cho `number`, chiều thay đổi phần trăm khi rulebook không nêu, và mã hóa `boolean` không?
6. Khi nào công bố private test, và có bao lâu từ công bố đến upload `submission.jsonl`? Thông tin này quyết định thời gian đặt E5.
7. Đáp án tham chiếu khi window câu hỏi ngoài dải dữ liệu là gì (`0` hay `unanswerable`)? Cần rút ra từ tham chiếu training.
8. Có phân bổ thời gian setup doanh nghiệp (ingestion, compilation) vào `elapsed_ms` từng câu không? Đề xuất: không; log riêng trong business log; thời gian từng câu chỉ gồm đọc, reasoning và thực thi riêng của câu đó.
9. Xác nhận LLM preprocessing theo doanh nghiệp lúc inference (C3) được phép như phép tính trên input đã mount.
10. Xác nhận DEC-11 so với quy tắc dấu tiếng Việt trong `CLAUDE.md`.

---

## Phụ lục A. Thay đổi so với v1

| Phạm vi | v1 | v2 |
|---|---|---|
| Trạng thái | Bản nháp chờ duyệt | Baseline triển khai với quyết định đã duyệt |
| Môi trường | Chưa đề cập | Phát triển trên Colab, ma trận môi trường, quy tắc thiết kế Colab (§4) |
| Serving | DP hoặc TP, chưa chốt | Replica DP, không NCCL; TP dự phòng (DEC-13) |
| Bàn giao | Một pipeline | Phase P1/P2/P3 với quy tắc merge (§10) |
| Lớp quyết định | Ensemble + calibrator trong thiết kế chính | Rule gate P1; component học có gate trong P3 |
| Logging | Danh sách trường | Quy tắc capture từng trường, log cấp doanh nghiệp cho compiled view (§7.6) |
| Xác thực | Danh sách metric | Test component, gate hệ thống G0–G8, truy vết (§9) |
| Rủi ro | Chỉ rủi ro Phương án E | Danh mục đầy đủ gồm hạ tầng (§12) |
| Bảng model | Danh sách ứng viên | Khả năng vừa 32 GB, yêu cầu vLLM, baseline một model (§8) |
| Type output | — | Thêm `boolean` từ DG §3.2 |
| Quyết định mới | — | DEC-13 topology serving, DEC-14 host E5 |
| Mô hình nhóm (v2.1) | Năm nhánh công việc WS-A…WS-E | Một Lead (contract, evaluation, tích hợp) và bốn thành viên M1–M4; cập nhật người phụ trách component và rủi ro |

## Phụ lục B. Nguồn
- Zalo AI Challenge 2026 — Hướng dẫn nộp Docker DataMate (tài liệu dự án `zac2026_DataMate_docker_guideline_final.md`)
- Đề xuất kiến trúc DataMate v1 (nguồn liệt kê trong đó: báo cáo model Qwen3.5, recipe vLLM Qwen3.5-9B, thảo luận benchmark RTX 5090 trên Hugging Face, tài liệu batch-invariance vLLM)
- [GPU Colab: tính năng và giá (McCormick ML)](https://mccormickml.com/2024/04/23/colab-gpus-features-and-pricing/) — runtime G4 là RTX PRO 6000 Blackwell
- [Chạy LLM trên Google Colab (datawookie, 2026-07)](https://datawookie.dev/blog/2026-07-31-running-llms-google-colab/) — danh sách runtime Colab hiện tại gồm G4
- [Chạy Qwen3.5-35B trên RTX 5090 với vLLM](https://joshua8-ai-website.pages.dev/qwen35-35b-rtx-5090-vllm-practical-guide) — RTX PRO 6000 và RTX 5090 dùng chung sm_120
- [Diễn đàn vLLM: image v0.9.0 không chạy trên RTX 5090](https://discuss.vllm.ai/t/docker-image-vllm-vllm-openai-v0-9-0-doesnt-work-on-5090/761) — image cũ thiếu kernel sm_120
- [Recipe vLLM — Qwen3.5-9B](https://recipes.vllm.ai/Qwen/Qwen3.5-9B.md) — yêu cầu vLLM ≥ 0.17.0
- [Tổng quan model nhỏ Qwen3.5 (besthub.dev)](https://besthub.dev/articles/qwen3-5-small-models-unveiled-from-0-8b-to-9b-with-full-capabilities-e409056d2b3c) — số tham số gồm vision; nhận định về default thinking
- [Docker không được hỗ trợ trên Colab (lưu trữ Stack Overflow)](https://kiwix.lema.org/stackoverflow.com_en_all_2023-11/questions/60235353/docker-is-not-running-on-colab)
- [Các gói GPU Google Cloud (vpsbenchmarks)](https://www.vpsbenchmarks.com/gpu_plans/google_compute_engine) — phương án VM G4 cho E5
