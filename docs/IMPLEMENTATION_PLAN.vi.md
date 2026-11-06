# DataMate 2026 — Kế hoạch triển khai

| Trường | Giá trị |
|---|---|
| **Tài liệu** | `IMPLEMENTATION_PLAN.md` |
| **Phiên bản** | 1.1 — một trưởng nhóm và bốn thành viên |
| **Trạng thái** | Lịch trình baseline; Lead cập nhật hằng ngày |
| **Ngày** | 2026-11-06 (GMT+7) |
| **Khoảng thời gian** | 2026-11-06 (chiều thứ Sáu) → 2026-11-16 (thứ Hai) 23:59 GMT+7 — hạn nộp giải pháp Docker cuối cùng |
| **Đầu vào** | `ARCHITECTURE_PROPOSAL.md` v2.1 (AP), `ARCHITECTURE.md` v1.1 (ARCH), `SPEC.md` v1.1 (SPEC) |
| **Danh sách nhiệm vụ** | `TASKS.md` v1.1 (ID `L-xx`, `M1-xx` … `M4-xx`; prefix chỉ người phụ trách) |

Mọi giờ đều theo GMT+7. Ngày được viết dưới dạng `MM-DD` (năm 2026).

---

## 1. Mục tiêu và ưu tiên

1. **Bàn giao image hợp lệ, tuân thủ và có thể tái lập** trước 11-14 (bản dự phòng an toàn) và 11-16 18:00 (bản cuối).
2. **Có baseline end-to-end hoạt động được (P1)** trên toàn bộ training split trước **11-09**.
3. **Cải thiện PA held-out** bằng tính năng P2 trong khoảng 11-10 đến 11-12, mỗi tính năng được điều khiển bằng switch.
4. **Đóng băng tính năng ngày 11-13** sau diễn tập container; sau đó chỉ sửa bug.

Khi thiếu thời gian, thứ tự ưu tiên là: **tuân thủ và tính hợp lệ → determinism → runtime → độ chính xác** (AP §10).

---

## 2. Nhóm và phân công

### 2.1 Vai trò
| Vai trò | Người | Nhiệm vụ chính | Phụ trách (package) | Component |
|---|---|---|---|---|
| **Lead** | Trưởng nhóm | Giữ các phần tương thích và phép đo đáng tin cậy; ra quyết định | `contracts/`, `eval/`, CI, `CODEOWNERS` | C14; module contract; tích hợp; quyết định; nộp bài |
| **M1 — Dữ liệu và ngữ nghĩa** | Thành viên 1 | Chuyển file doanh nghiệp bất kỳ thành catalog đúng và truy vấn được | `ingest/`, `catalog/`, `entities/`, `lexicon/`, `semantics/` | C2, C3 (P2), C6 (P2) |
| **M2 — Quy tắc, thời gian và câu trả lời** | Thành viên 2 | Mọi xử lý tất định từ rulebook đến wire value | `rules/`, `temporal/`, `decision/`, `formatting/` | C1, C5, C9, C10 |
| **M3 — Reasoning Engine** | Thành viên 3 | Lấy SQL đúng từ model, tin cậy và tái lập được | `llm/client.py`, `prompts/`, `parse/`, `solver/`, `sandbox/` | C4, C7, C8, client C13 |
| **M4 — Nền tảng và tuân thủ** | Thành viên 4 | Chạy hệ thống trong container đúng thời gian, với output tuân thủ | `run.py`, `config.py`, `runtime/`, `llm/replicas.py`, `llm/inprocess.py`, Docker, `tools/`, tài liệu tuân thủ | C11, C12, replica C13 |

**Lý do phân chia.**
- Mỗi thành viên phụ trách một phần liên tục của pipeline, có **ít seam và có kiểu rõ ràng** với người khác (§4 và ARCH §10), để bốn người cùng xây dựng.
- Lead phụ trách **contract** (nội dung đi qua seam) và **scorer/harness** (cách xác định hệ thống hoạt động đúng). Scorer do người khác với tác giả formatter (M2) viết, để oracle độc lập với code được kiểm tra.
- M2 nắm toàn bộ logic đáp án tất định (đầu vào là ngày, đầu ra là đáp án có kiểu). Nhờ đó, diễn giải quy tắc, gate và formatting do một người phụ trách, có thể thấy cách chúng tương tác.
- Khối lượng dự kiến cân bằng: mỗi người 62–66 giờ (§12).

### 2.2 Trách nhiệm của Lead
1. Contract: viết v1.0.0 trước 11-07 12:00; phê duyệt mọi thay đổi sau đó (SPEC §15).
2. Tích hợp: điều hành merge window hằng ngày; giữ `main` ở trạng thái pass; chạy walking skeleton và lần chạy đầy đủ đầu tiên.
3. Đo lường: phụ trách scorer, harness, nightly run, kiểm tra determinism và phân tích lỗi. Chỉ công nhận kết luận về độ chính xác nếu có kết quả harness kèm run record.
4. Quyết định: DEC-3, -4, -8, -10, -11, -13, -14, quyết định triển khai P3 và đóng băng (§7).
5. Release: duyệt bản nộp dự phòng và bản cuối.
6. Gỡ vướng: Lead tiếp quản nhiệm vụ P1 của thành viên nếu chậm quá nửa ngày.

### 2.3 Người thay thế
| Nếu vắng | Người thay thế | Lý do |
|---|---|---|
| M1 | M2 | Cùng làm mã dữ liệu phía CPU và dùng chung `lexicon/` |
| M2 | Lead | Lead phụ trách scorer và golden test mà formatter của M2 phải khớp |
| M3 | Lead, M4 hỗ trợ serving | Lead phân tích bake-off; M4 phụ trách replica |
| M4 | Lead | Runbook (M4-12) được viết để Lead có thể build, export và nộp |
| Lead | M4 lo release, M3 cung cấp thông tin ra quyết định | Runbook release; dữ liệu bake-off |

---

## 3. Các mốc

| Ngày | Mốc / giai đoạn tích hợp | Tiêu chí hoàn thành | Gate (AP §9.2) |
|---|---|---|---|
| Chiều thứ Sáu 11-06 | **Khởi động** | Phân vai; tạo repo; bắt đầu tìm E5; xác nhận quyền truy cập Colab G4 | — |
| Thứ Bảy 11-07 12:00 | **I0 Đóng băng contract** | Merge `contracts/` v1.0.0; export schema; có test double và bộ conformance test | Contract test pass |
| Cuối ngày thứ Bảy 11-07 | **M0 Nền tảng** | Scorer vượt ví dụ Brief; báo cáo kiểm tra dữ liệu; công bố fake catalog; môi trường Colab theo lock; **xác định E5 (DEC-14)**; chốt DEC-11/13 | G0 |
| Cuối ngày Chủ nhật 11-08 | **I1 Walking skeleton** | `run.main` end-to-end trên fixture với `ReplayModelClient`; output/log hợp lệ; CI determinism pass | Integration test pass |
| Cuối ngày thứ Hai 11-09 | **M1 / I2 Baseline** | Toàn bộ training split trên G4; PA theo type; dự báo runtime; **chốt DEC-3, DEC-8, DEC-10** | G1, G2, G3 |
| Cuối ngày thứ Ba 11-10 | **Build container đầu tiên** | Build image trên E4; smoke run trên E5 (10 câu, lệnh chấm bài) | — |
| Cuối ngày thứ Tư 11-11 | **M2 / I3 Độ chính xác** | Merge hoặc bỏ tính năng P2; kiểm tra determinism; kiểm tra giá trị của gate; **chốt DEC-4** | G4, G5 |
| Cuối ngày thứ Năm 11-12 | **Quyết định P3; release candidate** | Quyết định P3; build image RC1; soạn README và khai báo | — |
| Cuối ngày thứ Sáu 11-13 | **M3 / I4 Diễn tập + đóng băng** | Chạy toàn bộ training split trong container trên E5 bằng đúng lệnh chấm bài | G6 |
| Thứ Bảy 11-14 | **Nộp bản dự phòng** | Upload giải pháp #1; xác minh md5 từ máy thứ hai | G8 (một phần) |
| Cuối ngày Chủ nhật 11-15 | **M4 Bản ứng viên cuối** | So sánh chạy lại; kiểm tra đóng gói; README cuối | G7, G8 |
| Thứ Hai 11-16 18:00 | **M5 Bản cuối** | Upload, xác minh và nộp image cuối | — |
| Sau khi công bố (chưa chốt ngày, AP Q6) | **Chạy private test** | Chạy image đã đóng băng trên E5; upload `submission.jsonl` | — |

---

## 4. Quy trình cộng tác

### 4.1 Interface trước
1. **Contract trước code.** Mọi kiểu đi qua ranh giới package nằm trong `contracts/` (SPEC §5), được đóng băng tại I0. Thành viên triển khai theo contract, không theo code của nhau.
2. **Fake trước component thật.** Trước cuối ngày 11-07, mọi consumer đều có thứ để lập trình dựa vào: test double (L-04), fake catalog (M1-11), model client theo kịch bản (L-04); trước 11-08 12:00 có model call đã ghi (M3-13). Xem bảng bàn giao trong `TASKS.md` §6.
3. **Chỉ dùng public API.** Package chỉ được import package khác thông qua các tên export trong `__all__` của `__init__.py` package đó (SPEC §4.3). Refactor nội bộ không được làm hỏng công việc thành viên khác.
4. **Bộ conformance test.** Mọi implementation của protocol (`ModelClient`, `Executor`, `LunarCalendar`, `SubmissionSink`) phải vượt bộ test chung trong `tests/contract/conformance/` (SPEC §14.3). Test double cũng vượt cùng bộ test, để component kiểm thử với double hoạt động với thành phần thật.
5. **Consumer test.** Khi một thành viên dựa vào hành vi output của thành viên khác (ví dụ “SchemaCard liệt kê giá trị phân biệt của cột trạng thái”), consumer viết test trong `tests/contract/consumers/`. Producer không được merge thay đổi làm test đó hỏng (SPEC §14.4).
6. **Switch cho mọi phần chưa hoàn tất.** Merge code P2/P3 với switch tắt (SPEC §1.3), để phần đang làm dở không thay đổi hành vi production.

### 4.2 Ma trận review
Mọi merge request cần một phê duyệt từ reviewer bên dưới (thực thi bằng `CODEOWNERS`, L-19). Reviewer là **consumer** chính của code, vì họ dễ phát hiện giả định bị phá vỡ nhất.

| Chủ sở hữu code | Reviewer bắt buộc | Lý do |
|---|---|---|
| Lead (`contracts/`) | Thành viên có component tạo hoặc sử dụng kiểu được thay đổi | Thay đổi contract tác động đến họ trước |
| Lead (`eval/`) | M2 (quy tắc chấm điểm) hoặc M4 (harness/run record) | Kiểm tra oracle độc lập |
| M1 | M3 | Solver là consumer chính của SchemaCard và catalog |
| M2 (`rules/`, `temporal/`) | M3 | Solver dùng window và tham số quy tắc |
| M2 (`decision/`, `formatting/`) | Lead | Phải thống nhất với scorer |
| M3 | M2 | Gate dùng attempt và giá trị có kiểu |
| M4 | M3 (serving, orchestration) hoặc Lead (record, tuân thủ) | Các bên kết nối tại ranh giới |

Mục tiêu thời gian review: **4 giờ làm việc**. Lead có thể tiếp quản review chưa hoàn tất sau thời hạn này.

### 4.3 Nhịp làm việc hằng ngày
| Giờ | Hoạt động | Phụ trách |
|---|---|---|
| 09:00 | Stand-up 15 phút: hôm qua, hôm nay, blocker, **các bàn giao đến hạn hôm nay** | Lead |
| 09:15 | Xem báo cáo nightly: PA, đáp án thay đổi so với đêm trước, reason code mới | Lead |
| 14:00–15:00 | **Merge window**: Lead merge request đã duyệt theo thứ tự phụ thuộc; chạy CI trên `main` sau mỗi merge | Lead |
| 15:00 | Gắn tag `daily-MMDD` cho `main` nếu pass | Lead |
| 20:00 | Nightly harness run trên Colab G4 từ daily tag (L-18) | Lead |

Ngoài merge window, chỉ cho phép merge bản sửa lỗi để gỡ blocker cho người khác.

### 4.4 Giao tiếp
- Một kênh dự án. Đăng chậm bàn giao, yêu cầu đổi contract và quyết định trong cùng giờ xảy ra.
- Ghi quyết định vào AP §13 và ARCH §9 trong cùng ngày.
- Báo blocker ngay, không đợi stand-up tiếp theo.

---

## 5. Môi trường chung và khả năng tái lập

### 5.1 Môi trường
| Môi trường | Mục đích | Người dùng |
|---|---|---|
| E1 Colab G4 (sm_120) | Serving, bake-off, chạy đầy đủ, số đo runtime và determinism | M3 (ngày), Lead (đêm), M4 (test serving) |
| E2 Colab A100/H100 | Thử nghiệm độ chính xác khi không có G4 | M3, Lead |
| E3 CPU (Colab hoặc laptop) | Unit, contract, integration, determinism CI | Mọi người |
| E4 Build host | `docker build`, `save`, checksum, upload | M4 |
| E5 Host diễn tập / chạy private (sm_120 + Docker) | Lệnh chấm bài chính xác; chạy private test | M4, Lead |

Yêu cầu E5: GPU sm_120, ưu tiên 2 × RTX 5090; NVIDIA driver R570 trở lên; Docker với NVIDIA Container Toolkit; sẵn sàng vào 11-10, 11-13, 11-14/11-15 và thời gian private test. Phương án theo thứ tự ưu tiên (AP DEC-14): workstation RTX 5090 của thành viên; cloud VM có GPU Blackwell và hỗ trợ Docker đầy đủ; thuê bare-metal.

### 5.2 Setup Colab
- Thư mục Google Drive chung `DataMate/` chứa `data/train/`, `models/<candidate>/`, `locks/requirements.lock`, `runs/<date>-<commit>/`.
- Mỗi session: sao chép dữ liệu và model từ Drive sang ổ local; tạo venv từ lock; cài package từ commit đang kiểm thử (notebook M4-02).
- Mọi harness run đặt `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` và override giới hạn bộ nhớ G4 (`model.gpu_memory_utilization=0.30`, `model.replicas=1`).

### 5.3 Quy tắc tái lập (áp dụng cho mọi thành viên)
| # | Quy tắc | Thực thi bằng |
|---|---|---|
| R1 | **Một môi trường.** Mọi người cài từ cùng `requirements.lock`, được tạo trong base image đã chọn. Không `pip install` tùy tiện trong các lần chạy có chia sẻ kết quả. | Fingerprint môi trường của harness (L-12) |
| R2 | **Một snapshot dữ liệu.** `DataMate/data/train/` và mỗi thư mục model có file `SHA256SUMS`; harness ghi lại và kiểm tra chúng. | L-12, M4-02 |
| R3 | **Không sửa config local.** Chỉ dùng `--dev --set key=value`, được ghi trong run record. | `config.py` (M4-06) |
| R4 | **Phải có run record mới được công nhận.** Mọi kết luận về độ chính xác hoặc runtime trong merge request phải liên kết run record dưới `runs/`. | Template merge request (L-19) |
| R5 | **So sánh cùng điều kiện.** `compare_runs` từ chối các lần chạy khác fingerprint môi trường, snapshot dữ liệu hoặc revision model, trừ khi override tường minh. | L-12 |
| R6 | **Thay đổi prompt có phiên bản.** Đổi câu chữ tạo phiên bản template mới; cập nhật fixture `ModelCall` đã ghi trong cùng lần merge. | SPEC §7.13.5, M3-13 |
| R7 | **Determinism CI.** Hai lần chạy trên fixture phải giống nhau từng byte trước mọi merge. | L-20 |
| R8 | **Golden diff nightly.** Liệt kê đáp án thay đổi giữa hai đêm và khoảng commit gây thay đổi. | L-18 |

---

## 6. Quy trình kỹ thuật

### 6.1 Branch và merge
- Trunk-based: branch ngắn hạn `<owner>/<task-id>-<slug>` (ví dụ `m2/M2-04-resolver`), merge trong khung giờ hằng ngày.
- `main` luôn vượt unit, contract, conformance, consumer, integration và determinism test trên CPU.
- Thay đổi contract theo SPEC §15 và chỉ do Lead merge.

### 6.2 Định nghĩa hoàn tất (cho từng nhiệm vụ)
1. Code khớp mục SPEC được nêu trong nhiệm vụ.
2. Mọi MUST trong mục đó có test tương ứng (`test_spec_<section>_<short_name>`, SPEC §14.2); test pass trên CPU.
3. Conformance test và consumer test của package được tác động đều pass.
4. Không phát sinh lỗi static check mới (import graph, quy tắc public API, quét ID literal, `ruff`, `mypy` ở nơi bắt buộc).
5. Nhiệm vụ ảnh hưởng độ chính xác: đính kèm run record (PA held-out trước/sau).
6. Nhiệm vụ ảnh hưởng runtime: đính kèm số đo thời gian G4.
7. Được reviewer bắt buộc phê duyệt (§4.2).

### 6.3 Kỷ luật thử nghiệm
- Chỉ merge tính năng ở trạng thái **bật** nếu cải thiện PA held-out và vượt kiểm tra runtime, determinism; nếu không, merge ở trạng thái **tắt** hoặc bỏ.
- Không tuning theo public leaderboard; tối đa 5 lần nộp public để kiểm tra sơ bộ mỗi ngày (AP §6.12).

---

## 7. Lịch ra quyết định

| Khi nào | Quyết định | Đầu vào | Mặc định nếu chưa chốt |
|---|---|---|---|
| 11-06 | DEC-11 + SPEC SC-2 (phạm vi accent folding) | Quy tắc `CLAUDE.md`, SPEC §7.6.1 | Chỉ fold retrieval key và identifier |
| 11-06 | DEC-13 (topology serving) | AP §6.3 | Hai replica một GPU |
| **11-07** | **DEC-14 (host E5)** | Tình trạng sẵn có, chi phí | **Không có mặc định — báo cấp quyết định** |
| 11-09 | DEC-3 (model + base image) | Bake-off (M3-08, L-13) | Qwen3-8B trên image tham chiếu |
| 11-09 | DEC-8 (chính sách quyết định) | Kết quả G2 | Rule gate |
| 11-09 | DEC-10 (thinking) | Bake-off có/không thinking | Tắt |
| 11-11 | DEC-4 (compiled view) | Phép đo M1-13 | Tắt |
| 11-12 | Áp dụng P3 (calibrator, multi-strategy, LoRA) | M2-13, M3-12 | Tắt |
| 11-13 | Đóng băng tính năng | G6 | — |

---

## 8. Quy trình nộp bài

### 8.1 Nộp giải pháp (11-14 dự phòng, 11-16 bản cuối)
1. Xác nhận commit `main`, `run_config.json` và revision model khớp lần chạy G6 pass gần nhất.
2. Build: `docker build --platform linux/amd64 -t zaic2026_datamate_<team_name>:final .`
3. Kiểm tra: platform `linux/amd64`; bố cục thư mục theo DG §4.
4. Chạy đúng lệnh chấm bài trên E5 với training split; chạy `tools/precheck.sh`.
5. Export: `set -o pipefail; docker save … | pigz -p 8 > zaic2026_datamate_<team_name>.tar.gz`.
6. Đo kích thước chưa nén: `pigz -dc … | wc -c` (phải ≤ 100 GB).
7. `md5sum … > ….tar.gz.md5`; không đổi tên archive sau đó.
8. Upload; download trên máy thứ hai; `md5sum -c` phải in `OK`.
9. Nộp link, dòng md5 và kích thước chưa nén; ghi mọi thứ vào submission log.

### 8.2 Chạy private test (sau công bố)
1. Dùng image cuối đã **đóng băng**; không build lại.
2. Chạy trên E5 bằng đúng lệnh chấm bài, mount private test tại `/data:ro`.
3. Kiểm tra: một dòng mỗi câu hỏi; log đầy đủ; số lượng trong `run.json`.
4. Upload `submission.jsonl` để lên bảng xếp hạng tạm thời.
5. Lưu trữ toàn bộ thư mục `/result` (bằng chứng cho việc xem xét khả năng tái lập, DG §6).

---

## 9. Kế hoạch từng ngày

### Thứ Sáu 11-06 (buổi chiều) — Khởi động
| Ai | Công việc |
|---|---|
| Lead | Phân M1–M4; chốt DEC-11 và DEC-13; bắt đầu tìm E5; tạo repository, CI, `CODEOWNERS` (L-01, L-02, L-03, L-19) |
| M1 | Kiểm tra training split; bắt đầu bộ fixture (M1-01) |
| M2 | Kiểm tra `rulebook.md` và `calendar.csv` (M2-01) |
| M3 | Chuẩn bị venv Colab G4 cho các phiên bản vLLM ứng viên (M3-01) |
| M4 | Pull các base image ứng viên; trích xuất lock (M4-01) |

### Thứ Bảy 11-07 — I0 và M0
| Ai | Công việc |
|---|---|
| Lead | Chốt quyết định định dạng trước 10:00 (L-11); contract v1.0.0 trước 12:00 (L-04); scorer (L-10) |
| M1 | `fold()` và lexicon (M1-02); reader (M1-03–M1-05); numeric parser (M1-06); **fake catalog (M1-11)** |
| M2 | Calendar (M2-02); phép toán kỳ thời gian (M2-03); bắt đầu resolver (M2-04) |
| M3 | Model client (M3-02); render prompt (M3-03); test serving (M3-01) |
| M4 | Môi trường Colab và snapshot dữ liệu (M4-02); replica manager (M4-03); writer (M4-04) |
| **Hoàn thành khi** | G0; có fake catalog và client; xác định E5 |

### Chủ nhật 11-08 — I1 walking skeleton
| Ai | Công việc |
|---|---|
| Lead | Tích hợp component vào skeleton (L-05); determinism CI (L-20) |
| M1 | Date parser (M1-07); phát hiện cấu trúc Excel (M1-08); materialization và SchemaCard (M1-09, M1-10) |
| M2 | Resolver trước 12:00 (M2-04); formatter (M2-06); rule gate (M2-07) |
| M3 | Parser (M3-04); solver (M3-05, M3-06); sandbox (M3-07); **fixture ghi sẵn trước 12:00 (M3-13)** |
| M4 | Orchestrator (M4-05); `run.py` có stub mode (M4-06); record (M4-07) |
| **Hoàn thành khi** | Integration test I1 và determinism CI pass |

### Thứ Hai 11-09 — M1 baseline
| Ai | Công việc |
|---|---|
| Lead | Lần chạy đầy đủ đầu tiên trước 15:00 (L-06); harness (L-12); phân tích bake-off (L-13); **DEC-3, DEC-8, DEC-10** lúc 18:00 |
| M1 | Sửa lỗi ingestion gây crash từ lần chạy đầy đủ (M1-14) |
| M2 | Trích xuất TemporalParams (M2-05); sửa lỗi (M2-14) |
| M3 | Chạy bake-off (M3-08) |
| M4 | Dự báo runtime (M4-08); bản nháp Dockerfile (M4-09) |
| **Hoàn thành khi** | G1, G2, G3 |

### Thứ Ba 11-10 — Phân tích lỗi và container đầu tiên
| Ai | Công việc |
|---|---|
| Lead | Phân tích lỗi cùng người phụ trách (L-14); báo cáo nightly (L-18) |
| M1 | Entity linker (M1-12, P2) |
| M2 | RuleProfile (M2-08); quy ước table (M2-11) |
| M3 | Công cụ dựng kho few-shot (M3-10); bắt đầu cải thiện prompt (M3-09) |
| M4 | Build image (M4-09); smoke test E5 (M4-10) |
| **Hoàn thành khi** | Báo cáo phân tích lỗi; container smoke test pass |

### Thứ Tư 11-11 — M2 độ chính xác
| Ai | Công việc |
|---|---|
| Lead | Kiểm tra determinism (L-15); merge hoặc bỏ từng tính năng P2; **DEC-4** |
| M1 | Compiled view (M1-13, P2) |
| M2 | Khoảng thời gian âm lịch (M2-09); bộ perturbation test (M2-10); kiểm tra giá trị của gate (M2-12) |
| M3 | Cải thiện prompt (M3-09); Python fallback (M3-11) |
| M4 | Fault-injection test (M4-11) |
| **Hoàn thành khi** | G4, G5 |

### Thứ Năm 11-12 — Quyết định P3 và release candidate
| Ai | Công việc |
|---|---|
| Lead | **Quyết định triển khai P3**; không bắt đầu LoRA nếu chưa phê duyệt (AP DEC-9) |
| M1 | Sửa lỗi (M1-14) |
| M2 | Thử nghiệm calibrator nếu được duyệt (M2-13) |
| M3 | Thử nghiệm multi-strategy nếu được duyệt (M3-12) |
| M4 | Runbook (M4-12); README và `training_code/` (M4-13); precheck (M4-14); RC1 (M4-15) |
| **Hoàn thành khi** | Build xong image RC1 |

### Thứ Sáu 11-13 — M3 diễn tập và đóng băng
| Ai | Công việc |
|---|---|
| M4 | Diễn tập đầy đủ trên E5 (M4-16) |
| Lead | So sánh lần chạy container và G4 (L-16); **đóng băng tính năng** sau G6 |
| M1, M2, M3 | Chỉ sửa lỗi phát hiện qua diễn tập |
| **Hoàn thành khi** | G6 |

### Thứ Bảy 11-14 — Nộp bản dự phòng
| Ai | Công việc |
|---|---|
| M4 + Lead | Export, checksum, upload, xác minh, nộp (M4-17, L-08) |
| Lead | So sánh lần chạy container thứ hai (L-17) |

### Chủ nhật 11-15 — M4 bản ứng viên cuối
| Ai | Công việc |
|---|---|
| Tất cả | Chỉ sửa lỗi phát hiện từ 11-13; mỗi bản sửa đều xác thực lại trên E5 |
| M4 | README cuối; kiểm tra đóng gói (M4-18) |
| Lead | Duyệt bản ứng viên cuối |

### Thứ Hai 11-16 — M5 bản cuối
| Giờ | Bước |
|---|---|
| Trước 12:00 | Build image cuối; chạy lại G6 trên E5 nếu có thay đổi kể từ bản nộp dự phòng |
| Trước 15:00 | Bắt đầu export, md5, upload |
| Trước 18:00 | `md5sum -c` trên máy thứ hai báo OK; nộp biểu mẫu (L-09) |
| 18:00–23:59 | Chỉ là thời gian dự phòng; không đổi code |

---

## 10. Đường găng (critical path)

```
L-04 contracts ─► M1 catalog (M1-03..M1-10) ─┐
                 M2 temporal (M2-03, M2-04) ──┤
                 M3 solver (M3-02..M3-07) ────┼─► L-05 skeleton ─► L-06 full run ─► DEC-3 ─► M4-09 image ─► M4-16 rehearsal ─► M4-17 safety ─► L-09 final
                 M2 answer (M2-06, M2-07) ────┤                                                      ▲
                 M4 runtime (M4-03..M4-07) ───┘                                                      │
 DEC-14 E5 host (L-03) ──────────────────────────────────────────────────────────────────────────────┘
```
- **Chuỗi dài nhất:** contract → catalog → solver → chạy đầy đủ → quyết định model → image → diễn tập → nộp.
- **Phụ thuộc bên ngoài:** host E5 (DEC-14). Không có nó thì không thể diễn tập và chạy private test (AP RISK-1).
- **Nhánh song song:** xác thực base image trên G4 (M3-01, M4-01) bắt đầu từ ngày 0 vì là điều kiện cho DEC-3.

---

## 11. Phương án dự phòng

| Tình huống | Cách xử lý | Người quyết định |
|---|---|---|
| Chưa có host E5 vào 11-09 | Báo cấp quyết định; thử chạy image đã export bằng Apptainer `--nv` trên Colab G4 (không chính thức, AP RISK-1); tiếp tục tìm | Lead |
| Model ưu tiên không đạt sm_120 hoặc determinism vào 11-09 | Chọn model dự phòng trên image tham chiếu | Lead |
| Baseline P1 chưa end-to-end vào cuối 11-09 | Dừng toàn bộ P2; mọi người tập trung critical path đến khi G2 pass | Lead |
| Bàn giao (TASKS §6) trễ > 4 giờ | Consumer tiếp tục dùng fake; Lead làm cùng producer | Lead |
| Phát hiện lỗi contract sau I0 | Sửa patch/minor qua SPEC §15 trong ngày; thay đổi major chỉ khi Lead duyệt và thông báo cùng ngày | Lead |
| Runtime dự báo > 2.5 giờ | Giảm `max_repairs`, ngân sách context, số few-shot | M4 + M3 |
| Kiểm tra determinism thất bại | Tắt thinking; giảm concurrency; dùng batch-invariant mode nếu đã xác thực | M4 |
| Tính năng P2 làm giảm PA held-out | Merge với switch tắt hoặc bỏ | Lead |
| Diễn tập thất bại ngày 11-13 | Sửa và chạy lại sáng 11-14; nộp bản dự phòng muộn nhất tối 11-14 | M4 + Lead |
| Upload hoặc md5 thất bại ngày 11-16 | Export và upload lại; image dự phòng 11-14 vẫn là phương án dự trữ | M4 |
| Một người vắng > 1 ngày | Người thay thế theo §2.3 tiếp quản nhiệm vụ P1 của người đó trước | Lead |

---

## 12. Tổng quan công sức

Theo `TASKS.md` §8, tính bằng giờ kỹ sư.

| Phụ trách | P1 | P2 | P3 | INT | COL | Tổng | Quỹ giờ (xấp xỉ) |
|---|---|---|---|---|---|---|---|
| Lead | 29 | — | — | 26 | 7 | 62 | 75 (sau khoảng 15 giờ stand-up, review, quyết định) |
| M1 | 38 | 14 | — | 10 | 2 | 64 | 90 |
| M2 | 33 | 18 | 6 | 8 | — | 65 | 90 |
| M3 | 34 | 14 | 6 | 6 | 4 | 64 | 90 |
| M4 | 37 | 4 | — | 22 | 3 | 66 | 90 |

Như vậy Lead còn khoảng 13 giờ dự phòng, mỗi thành viên còn 24–26 giờ, để xử lý lỗi từ các lần chạy đầy đủ và review (khoảng 1 giờ/ngày/người). Chỉ sử dụng giờ P3 nếu quyết định ngày 11-12 phê duyệt.
