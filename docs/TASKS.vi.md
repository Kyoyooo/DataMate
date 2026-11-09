# DataMate 2026 — Phân rã nhiệm vụ

| Trường | Giá trị |
|---|---|
| **Tài liệu** | `TASKS.md` |
| **Phiên bản** | 1.1 — tổ chức lại cho một trưởng nhóm và bốn thành viên |
| **Trạng thái** | Backlog baseline; người phụ trách nhiệm vụ cập nhật cột trạng thái, Lead rà soát hằng ngày |
| **Ngày** | 2026-11-06 (GMT+7) |
| **Đầu vào** | `SPEC.md` v1.1 (yêu cầu và acceptance test), `ARCHITECTURE.md` v1.1 (bố cục module và seam), `IMPLEMENTATION_PLAN.md` v1.1 (nhóm, lịch trình, quy tắc cộng tác) |

### Quy ước
- **Prefix người phụ trách**: `L` là Lead, `M1`–`M4` là các thành viên (vai trò trong `IMPLEMENTATION_PLAN.md` §2). Prefix chỉ người phụ trách. ID ổn định từ v1.1; nhiệm vụ mới thêm vào cuối, không đánh số lại. Ánh xạ ID v1.0 nằm ở §9.
- **Ph**: P1 baseline, P2 độ chính xác, P3 tùy chọn (có gate), INT tích hợp/release, COL hạ tầng cộng tác.
- **Est**: giờ kỹ sư. **Due**: cuối ngày (GMT+7), trừ khi ghi giờ cụ thể.
- **Rev**: reviewer bắt buộc (người phụ trách khác); xem `IMPLEMENTATION_PLAN.md` §4.2.
- **Hoàn tất khi**: tiêu chí nghiệm thu; mọi nhiệm vụ còn phải đáp ứng định nghĩa hoàn tất tại `IMPLEMENTATION_PLAN.md` §6.2.
- **Trạng thái**: `Todo` → `Doing` → `Review` → `Done` (hoặc `Dropped`, kèm lý do).
- Nhiệm vụ P2/P3 được merge dưới switch cấu hình, mặc định production **tắt** cho đến khi vượt gate (SPEC §1.3).

---

## 1. Lead — Tích hợp, Contract và Evaluation (`contracts/`, `eval/`, CI)

| ID | Nhiệm vụ | Ph | Est | Due | Phụ thuộc | Rev | Hoàn tất khi | Trạng thái |
|---|---|---|---|---|---|---|---|---|
| L-01 | Phân thành viên vào M1–M4; chốt DEC-11 (+ SPEC SC-2) và DEC-13 | P1 | 1 | 11-06 | — | — | Ghi quyết định vào AP §13 và ARCH §9 | Todo |
| L-02 | Repository, CI (pytest, ruff, mypy cho `contracts`/`temporal`/`formatting`, kiểm tra import graph, quét ID literal, kiểm tra schema diff), bảo vệ branch | COL | 4 | 11-07 | — | M4 | CI chạy trên mọi merge request; check thất bại chặn merge (SPEC §4.3, §2.5, §14.2, §15) | Todo |
| L-03 | Đảm bảo có host E5 để diễn tập/chạy private (DEC-14) | P1 | 3 | **11-07** | — | — | Host có GPU sm_120, Docker, NVIDIA Container Toolkit; `nvidia-smi` hoạt động trong container; đặt lịch 11-10, 11-13–11-15 và thời gian private test | Todo |
| L-04 | `contracts/` v1.0.0: mọi kiểu tại SPEC §5, enum, code, protocol, test double, schema export | P1 | 6 | **11-07 12:00** | L-02, L-11 | M1–M4 (mỗi người review kiểu mình tạo) | Contract test pass (round-trip, invariant §5.9); commit schema; có `ReplayModelClient`, `ScriptedModelClient`, `InMemorySink`, `FakeDeadline` | Todo |
| L-05 | Tích hợp walking skeleton: thay stub khi component sẵn sàng | INT | 3 | 11-08 | L-04; M1-11, M2-04, M3-05, M2-06, M4-06 | — | `run.main` tạo file submission và log hợp lệ trên fixture với `ReplayModelClient` (I1) | Todo |
| L-06 | Điều phối lần chạy toàn bộ training split đầu tiên trên G4 | INT | 2 | 11-09 15:00 | L-05, M4-02, M3-02 | — | Chạy hoàn tất; công bố PA theo type và danh sách crash | Todo |
| L-07 | Review quyết định: DEC-3/8/10 (11-09), DEC-4 (11-11), triển khai P3 (11-12), đóng băng (11-13) | INT | 2 | Theo kế hoạch §7 | L-13, M2-12, M2-13, M3-12, M4-16 | — | Mỗi quyết định được ghi cùng bằng chứng sử dụng | Todo |
| L-08 | Duyệt bản nộp dự phòng | INT | 1 | 11-14 | M4-17 | — | Đã nộp link, md5, kích thước; cập nhật submission log | Todo |
| L-09 | Nộp bản cuối | INT | 2 | 11-16 18:00 | M4-18 | — | Xác minh image cuối từ máy thứ hai và nộp | Todo |
| L-10 | Scorer local theo Brief §2.1–2.2 (oracle độc lập; không do tác giả formatter viết) | P1 | 6 | 11-07 | L-04 | M2 | Khớp 100% mọi ví dụ Brief (G0) | Todo |
| L-11 | Xác minh SPEC V1–V5 (wire shape của list/table, làm tròn, boolean, thứ tự tie-code) bằng Brief và đáp án training | P1 | 3 | **11-07 10:00** | — | M2 | Đăng kết quả trước khi đóng băng contract; cập nhật SPEC theo §15 nếu cần | Todo |
| L-12 | Harness: entry point, fold, resume, run record, kiểm tra fingerprint môi trường, báo cáo, `compare_runs` | P1 | 8 | 11-09 | L-10, M4-06 | M4 | SPEC §7.14; resume được trên Colab; từ chối so sánh run khác fingerprint trừ khi dùng `--allow-env-diff`; dự báo cho 500/1.000 câu | Todo |
| L-13 | Phân tích bake-off và đề xuất DEC-3 | P1 | 2 | 11-09 | M3-08 | — | Gửi đề xuất kèm bằng chứng cho L-07 | Todo |
| L-14 | Phân tích lỗi theo type, category, reason code, component phụ trách | INT | 4 | 11-10 | L-06 | — | Các nhóm lỗi lớn nhất có ví dụ và người phụ trách | Todo |
| L-15 | Kiểm tra determinism: hai lần chạy đầy đủ trên G4 | INT | 3 | 11-11 | L-12 | M4 | G4: submission giống hệt hoặc \|ΔPA\| ≤ 0.005 | Todo |
| L-16 | So sánh lần chạy container (M4-16) với G4 | INT | 3 | 11-13 | M4-16 | M4 | \|ΔPA\| ≤ 0.01 giữa hai môi trường, hoặc giải thích được khác biệt | Todo |
| L-17 | So sánh lần chạy container thứ hai cho G7 | INT | 3 | 11-15 | M4-17 | M4 | G7: submission giống hệt hoặc \|ΔPA\| ≤ 0.005 | Todo |
| L-18 | Vận hành harness nightly, diff với golden baseline, báo cáo buổi sáng | INT | 3 | Hằng ngày 11-09–11-15 | L-12 | — | Đăng báo cáo trước stand-up: PA, đáp án đổi so với đêm trước kèm khoảng commit, reason code mới | Todo |
| L-19 | `CODEOWNERS`, template merge request (mục SPEC, test, run record, tác động contract), bảng theo dõi bàn giao | COL | 1 | 11-07 | L-02 | — | Mọi đường dẫn package có người phụ trách và reviewer bắt buộc (kế hoạch §4.2) | Todo |
| L-20 | Determinism CI: chạy `run.main` hai lần trên fixture với `ReplayModelClient`; so sánh output từng byte | COL | 2 | 11-08 | L-05 | M4 | CI thất bại nếu có bất kỳ byte nào khác nhau giữa hai lần chạy (SPEC §14.5) | Todo |

---

## 2. M1 — Dữ liệu và ngữ nghĩa (`ingest/`, `catalog/`, `entities/`, `lexicon/`, `semantics/`)

| ID | Nhiệm vụ | Ph | Est | Due | Phụ thuộc | Rev | Hoàn tất khi | Trạng thái |
|---|---|---|---|---|---|---|---|---|
| M1-01 | Kiểm tra training split; báo cáo dữ liệu; bộ fixture v0 | P1 | 4 | 11-07 | — | L | Báo cáo liệt kê loại/kích thước file, cấu trúc sheet, định dạng số/ngày, chất lượng README; fixture dưới `tests/fixtures/businesses/` bao phủ mọi quy tắc SPEC §7.2 | Review |
| M1-02 | `fold()`, chuẩn hóa NFC/khoảng trắng, lexicon viết tắt v0 | P1 | 4 | 11-07 | L-04 | M2 | SPEC §7.6.1, chuẩn hóa §7.4; lexicon bao phủ viết tắt gặp trong câu hỏi training | Review |
| M1-03 | CSV reader: phát hiện encoding, nhận diện dialect | P1 | 3 | 11-07 | L-04 | M3 | SPEC §7.2.2; fixture cp1258 và UTF-8-SIG pass | Review |
| M1-04 | Excel reader (calamine, mọi sheet, fallback openpyxl) | P1 | 3 | 11-07 | L-04 | M3 | Phần đọc ở SPEC §7.2.3; bảo toàn kiểu ô gốc | Review |
| M1-05 | SQLite reader (stdlib, `mode=ro&immutable=1`) | P1 | 2 | 11-07 | L-04 | M4 | SPEC §7.2.4; đọc fixture WAL-mode trong thư mục read-only không phát sinh ghi; không DuckDB extension (SC-3) | Partial |
| M1-06 | Parse số: null token, tiền tệ, hậu tố, dạng ghép, biểu quyết quy ước theo cột, kiểu SQL chính xác | P1 | 5 | 11-07 | L-04 | M2 | SPEC §7.2.5; fixture `1.250.000`, `1,5`, `150k`, `1tr2`, `12,5%`; cột mơ hồ giữ VARCHAR kèm cảnh báo | Review |
| M1-07 | Parse ngày: định dạng, bằng chứng DMY/MDY, Excel serial, cột tháng | P1 | 4 | 11-08 | M1-06 | M2 | SPEC §7.2.6; fixture mơ hồ `01/02/2025` hoạt động đúng đặc tả | Review |
| M1-08 | Phát hiện block, header, dòng tổng, dòng ghi chú trong Excel | P1 | 5 | 11-08 | M1-04 | M3 | Quy tắc SPEC §7.2.3; fixture dòng tiêu đề, header gộp, hai block, tổng, ghi chú đều pass | Review |
| M1-09 | Identifier (SC-2) và materialization DuckDB | P1 | 3 | 11-08 | M1-02–M1-06 | M3 | SPEC §7.2.7, §7.2.10; tắt tự động cài/load extension; mở lại file ở read-only được | Review |
| M1-10 | Profiling, key, join, độ phủ ngày, render SchemaCard và ngân sách token | P1 | 5 | 11-08 | M1-09, M3-03 | M3 | SPEC §7.2.8–7.2.9; SchemaCard giống từng byte qua các lần setup; XLSX 300k dòng ≤ 60 giây | Partial |
| M1-11 | **Catalog fake cho thành viên khác**: builder `make_fake_catalog()` và 3 fixture catalog dựng sẵn (DuckDB + `BusinessCatalog`) | COL | 2 | **11-07** | L-04 | M3 | Công bố trong `tests/fixtures/catalogs/`; M2/M3/M4 có thể build và query catalog mà không cần mã ingestion thật (SPEC §14.4) | Review |
| M1-12 | Entity linker: index, fuzzy query, xếp hạng | P2 | 8 | 11-11 | M1-10, M1-02 | M3 | SPEC §7.6; thứ tự toàn phần; giá trị đúng như lưu trữ; PA held-out với switch bật/tắt | Partial |
| M1-13 | Semantic compiler và xác thực view (DEC-4) | P2 | 6 | 11-11 | M1-10, M3-02 | M2 | SPEC §7.3; vô hiệu hóa và log view lỗi; PA held-out có/không tính năng theo category | Partial |
| M1-14 | Sửa ingestion từ các lần chạy đầy đủ; bổ sung fixture còn thiếu | INT | 10 | Liên tục đến 11-13 | L-06 | M3 | Mọi nhóm cảnh báo ingestion gặp trong training có fixture; không setup failure trên training split | Review |

---

## 3. M2 — Quy tắc, thời gian và câu trả lời (`rules/`, `temporal/`, `decision/`, `formatting/`)

| ID | Nhiệm vụ | Ph | Est | Due | Phụ thuộc | Rev | Hoàn tất khi | Trạng thái |
|---|---|---|---|---|---|---|---|---|
| M2-01 | Kiểm tra `rulebook.md` và `calendar.csv`; bảng alias calendar; xác minh SPEC V6 | P1 | 2 | 11-07 | — | L | Ghi tài liệu tham số quy tắc có trong training rulebook (chỉ cho test, không làm code default); commit bảng alias | Todo |
| M2-02 | `LunarCalendar` từ `calendar.csv`, có validation | P1 | 3 | 11-07 | M2-01, L-04 | M1 | SPEC §7.1 bước 2; fixture khoảng trống/trùng/tháng nhuận; vượt bộ conformance test `LunarCalendar` | Todo |
| M2-03 | Phép toán kỳ thời gian: tuần theo `week_start`, tháng, quý, năm, dịch chuyển, clamping | P1 | 5 | 11-07 | L-04 | M1 | Unit test cho ranh giới năm, năm nhuận, cả hai kiểu bắt đầu tuần | Todo |
| M2-04 | `resolve_windows()` cho mọi loại `TimeExpr` P1; tỷ lệ bao phủ; provenance | P1 | 8 | **11-08 12:00** | M2-03 | M3 | Các dòng P1 ở SPEC §7.5; property test 10.000 ca ngẫu nhiên; `unsupported` → `E_TIME_UNSUPPORTED` | Todo |
| M2-05 | Trích xuất `TemporalParams` (`rules.temporal.v1`), xác thực span, fallback tổng quát | P1 | 4 | 11-09 | M3-02, M3-03, M2-04 | M3 | SPEC §7.1 bước 3; từ chối span diễn đạt lại; rulebook rỗng → mọi giá trị generic; kết quả trong `run.json.split` | Todo |
| M2-06 | Formatter: mọi type; serializer bảo toàn Decimal | P1 | 6 | 11-08 | L-04, L-11 | L | Golden test SPEC §7.10 pass; scorer L-10 dùng cùng golden test | Todo |
| M2-07 | Rule gate, kiểm tra catalog cho trường thiếu, feature cơ bản | P1 | 5 | 11-08 | L-04, M1-11 | L | Từng quy tắc 1–7 của SPEC §7.9 được kiểm thử với fake catalog và attempt theo kịch bản | Todo |
| M2-08 | Trích xuất `RuleProfile` (`rules.profile.v1`) có validation | P2 | 5 | 11-11 | M2-05 | M3 | SPEC §7.1 bước 4; liệt kê trường chưa giải quyết | Todo |
| M2-09 | Khoảng âm lịch: `lunar_holiday`, `lunar_date_range` | P2 | 4 | 11-11 | M2-02, M2-08 | M1 | Các dòng P2 ở SPEC §7.5; kiểm thử Tết trải qua hai năm dương lịch | Todo |
| M2-10 | Bộ test biến đổi rulebook (perturbation) | P2 | 3 | 11-11 | M2-05 | L | Đổi đầu tuần / tính bao hàm biên / khoảng lễ làm window thay đổi như mong đợi | Todo |
| M2-11 | Quy ước đặt tên cột table từ đáp án tham chiếu training | P2 | 2 | 11-10 | L-11 | L | `formatting/table_conventions.md`; báo cáo PA type table | Todo |
| M2-12 | Kiểm tra giá trị của gate và feature verifier P2 | P2 | 4 | 11-11 | M2-07, L-12 | L | G5: PA rule gate ≥ PA trả lời mọi câu trên doanh nghiệp held-out | Todo |
| M2-13 | Thử nghiệm calibrator | P3 | 6 | 11-12 | M2-12 | L | PA grouped CV so với rule gate; chỉ áp dụng qua L-07 | Todo |
| M2-14 | Sửa lỗi từ lần chạy đầy đủ (thời gian, quy tắc, quyết định, định dạng) | INT | 8 | Liên tục đến 11-13 | L-06 | L | Giảm hoặc giải thích từng nhóm lỗi được giao | Todo |

---

## 4. M3 — Reasoning Engine (`llm/client.py`, `prompts/`, `parse/`, `solver/`, `sandbox/`)

| ID | Nhiệm vụ | Ph | Est | Due | Phụ thuộc | Rev | Hoàn tất khi | Trạng thái |
|---|---|---|---|---|---|---|---|---|
| M3-01 | Colab G4: cài các phiên bản vLLM ứng viên; serve từng ứng viên với giới hạn tương đương 32 GB | P1 | 4 | 11-07 | M4-01 | M4 | Mỗi ứng viên: greedy output trên sm_120, bộ nhớ trong giới hạn, bật CUDA graph; đăng bảng kết quả (G1) | Todo |
| M3-02 | `HttpModelClient`: tham số tường minh, response JSON Schema, `enable_thinking`, request hash, timeout/retry, capture chính xác | P1 | 5 | **11-07** | L-04, M4-03 | M4 | SPEC §7.13.2; assert mọi trường request body (D1); capture chính xác từng byte; vượt conformance test `ModelClient` | Todo |
| M3-03 | Render prompt (Jinja2 StrictUndefined), hash template, ngân sách tokenizer | P1 | 3 | 11-07 | L-04 | M1 | SPEC §7.13.4–7.13.5; render hai lần giống từng byte | Todo |
| M3-04 | Question parser + `parse.frame.v1` | P1 | 5 | 11-08 | M3-02, M3-03, M1-02 | M2 | SPEC §7.4; frame hợp schema cho ≥ 98% câu hỏi training; không hợp lệ → `E_PARSE_INVALID` | Todo |
| M3-05 | Solver: context pack, `solve.sql.v1`, `repair.sql.v1`, vòng lặp attempt | P1 | 8 | 11-08 | M3-04, M1-11, M2-04 | M2 | SPEC §7.7.1, §7.7.4; phần 1–5 giống từng byte theo doanh nghiệp (D3); repair có giới hạn; tuân thủ soft deadline | Todo |
| M3-06 | `check_sql`, contract check, `to_typed_value` | P1 | 4 | 11-08 | L-04 | M2 | SPEC §7.7.3, §7.7.5; kiểm thử từng violation code | Todo |
| M3-07 | Sandbox: worker pool có thể hủy, DuckDB read-only, giới hạn, mã hóa giá trị có tag | P1 | 5 | 11-08 | L-04, M1-11 | M4 | Test SPEC §7.8; vượt conformance test `Executor` | Todo |
| M3-08 | Chạy bake-off model (L-13 phân tích) | INT | 6 | 11-09 | L-06 | L | Quy trình AP §8.2 cho 2–3 ứng viên; bảng PA, determinism, throughput | Todo |
| M3-09 | Cải thiện prompt và few-shot từ phân tích lỗi | P2 | 6 | 11-11 | L-14 | L | Mỗi thay đổi có run record; PA held-out không giảm | Todo |
| M3-10 | Builder kho few-shot (`training_code/data_generation/build_fewshot.py`) + lựa chọn có bảo vệ chống rò rỉ CV | P2 | 4 | 11-10 | M3-05 | L | SPEC §7.7.2; leakage test pass; kho được liệt kê trong `data_manifest.json` | Todo |
| M3-11 | Python fallback (`solve.python.v1`), import guard | P2 | 4 | 11-11 | M3-07 | M4 | P2 tại SPEC §7.7.4, quy tắc Python §7.8; switch mặc định tắt | Todo |
| M3-12 | Thử nghiệm đồng thuận nhiều chiến lược (multi-strategy) | P3 | 6 | 11-12 | M3-09, M2-12 | L | PA, runtime, determinism so với một chiến lược; chỉ áp dụng qua L-07 | Todo |
| M3-13 | **Fixture `ModelCall` ghi sẵn** cho integration test CPU (cập nhật khi đổi phiên bản template) | COL | 4 | **11-08 12:00** | M3-04, M3-05 | L | Fixture dưới `tests/fixtures/model_calls/`, metadata chứa phiên bản template; CI integration và determinism chạy trên CPU | Todo |

---

## 5. M4 — Nền tảng và tuân thủ (`run.py`, `config.py`, `runtime/`, `llm/replicas.py`, `llm/inprocess.py`, Docker, `tools/`, tài liệu tuân thủ)

| ID | Nhiệm vụ | Ph | Est | Due | Phụ thuộc | Rev | Hoàn tất khi | Trạng thái |
|---|---|---|---|---|---|---|---|---|
| M4-01 | Pull base image ứng viên trên E4; trích xuất lock `pip freeze` | P1 | 4 | 11-06 | — | L | Có lock cho từng base image ứng viên; ghi phiên bản vLLM/torch/CUDA | Todo |
| M4-02 | Môi trường Colab từ lock; bố cục Drive với snapshot dữ liệu/model có checksum; notebook bootstrap session | COL | 3 | **11-07** | M4-01 | L | Session G4 mới chạy được harness trong ≤ 20 phút; mọi thành viên dùng cùng SHA-256 snapshot (kế hoạch §5.3) | Todo |
| M4-03 | Replica manager: launch, health, warm-up, restart, capture log | P1 | 6 | 11-07 | M4-01 | M3 | SPEC §7.13.1; hoạt động với `replicas=1` trên G4; kiểm thử restart | Todo |
| M4-04 | Writer: thứ tự fsync log trước submission, từ chối trùng, đổi tên file có sẵn | P1 | 3 | 11-07 | L-04 | L | SPEC §7.11; vượt conformance test `SubmissionSink`; test crash giữa chừng | Todo |
| M4-05 | Orchestrator: plan/phân công, queue, worker, deadline, degrade mode, global stop, SIGTERM | P1 | 8 | 11-08 | L-04, M4-04 | M3 | SPEC §7.12; phân công giống nhau qua các lần chạy; global stop ghi abstain cho mọi ID chưa ghi | Todo |
| M4-06 | Vòng đời `run.py` và `config.py` (validation, default, hash, override `--dev`), có **stub pipeline** dùng được từ ngày 2 | P1 | 5 | 11-08 | L-04 | L | SPEC §2.1–2.3, §6.1; stub mode cho phép L-05 tích hợp từng component; exit code theo §2.1 | Todo |
| M4-07 | Tạo record: `LogRecord`, `BusinessLogRecord`, `RunRecord` | P1 | 4 | 11-08 | L-04 | L | Schema SPEC §8.3–8.5 hợp lệ; kiểm thử quy tắc `thinking`/`code`/`output` (SC-7) | Todo |
| M4-08 | Dự báo runtime trên G4 | P1 | 2 | 11-09 | L-06 | L | Báo cáo dự báo AP §7.8 cho 500 và 1.000 câu (G3) | Todo |
| M4-09 | Dockerfile, `predict.sh`, `.dockerignore`, build image đầu tiên | P1 | 5 | 11-10 | L-07 (DEC-3), M4-06 | L | ARCH §7.1; `linux/amd64`; bố cục DG §4; không loại `training_code/` | Todo |
| M4-10 | Smoke run 10 câu trên E5 bằng đúng lệnh chấm bài | INT | 3 | 11-10 | M4-09, L-03 | L | `--network none`, `/data:ro`, cả hai GPU; loopback serving hoạt động (SPEC V10) | Todo |
| M4-11 | Fault-injection test (kill replica, setup crash, hàng loạt SQL timeout, SIGTERM) | P2 | 4 | 11-11 | M4-05 | M3 | Mỗi lỗi cho kết quả ở ARCH §5.3; lần chạy hoàn tất với output hợp lệ | Todo |
| M4-12 | Runbook: build/export/upload, chạy E5, chạy private test | INT | 2 | 11-12 | M4-09 | L | Lead có thể thực hiện từng runbook mà không cần M4 | Todo |
| M4-13 | README (phương pháp, khai báo model với `tools/count_params.py`), `training_code/`, `data_manifest.json` | INT | 4 | 11-12 | L-07 (DEC-3), M3-10 | L | SPEC §13.1–13.2; đếm tham số từ safetensors đóng gói; tuyên bố không training trừ khi DEC-9 áp dụng LoRA | Todo |
| M4-14 | `tools/precheck.sh` (tự động hóa checklist DG §10) | INT | 3 | 11-12 | M4-07 | L | SPEC §13.3; thất bại nếu thiếu bất kỳ trường log hoặc dòng nào | Todo |
| M4-15 | Image release candidate RC1 | INT | 2 | 11-12 | M4-13, M4-14 | L | Build từ commit có tag; đo kích thước | Todo |
| M4-16 | Diễn tập đầy đủ trên E5: training split, đúng lệnh chấm bài | INT | 3 | 11-13 | M4-15, L-03 | L | G6 pass; precheck không lỗi | Todo |
| M4-17 | Nộp bản dự phòng: export, md5, upload, xác minh máy thứ hai | INT | 2 | 11-14 | M4-16 | L | Hoàn tất bước 1–9 của IMPLEMENTATION_PLAN §8.1 | Todo |
| M4-18 | Kiểm tra đóng gói bản ứng viên cuối (G8) và export cuối | INT | 3 | 11-16 12:00 | L-17 | L | Tar chưa nén ≤ 100 GB; xác minh md5; README hoàn chỉnh | Todo |

---

## 6. Bàn giao giữa các thành viên

Mỗi dòng là cam kết từ producer tới consumer. Bàn giao trễ được báo tại stand-up cùng ngày; consumer tiếp tục làm việc với fake hoặc test double ở cột cuối.

| # | Artifact | Producer | Consumer | Cần trước | Trong lúc chờ, consumer dùng |
|---|---|---|---|---|---|
| H1 | `contracts/` v1.0.0 + test double | L (L-04) | Tất cả | 11-07 12:00 | Branch nháp của `contracts/` |
| H2 | Quyết định định dạng V1–V5 | L (L-11) | M2, L | 11-07 10:00 | Mặc định SPEC §17 |
| H3 | Fake catalog | M1 (M1-11) | M2, M3, M4 | Cuối ngày 11-07 | `BusinessCatalog` viết tay trong test |
| H4 | `HttpModelClient` trên Colab | M3 (M3-02) | M2 (M2-05), M1 (M1-13) | Cuối ngày 11-07 | `ScriptedModelClient` |
| H5 | Replica manager trên Colab | M4 (M4-03) | M3 | Cuối ngày 11-07 | vLLM server khởi động thủ công |
| H6 | `resolve_windows()` P1 | M2 (M2-04) | M3 | 11-08 12:00 | Window literal trong solver test |
| H7 | Fixture `ModelCall` ghi sẵn | M3 (M3-13) | L, M2, M4 | 11-08 12:00 | `ScriptedModelClient` |
| H8 | `setup_business` thật trên fixture | M1 (M1-10) | M3, L | Cuối ngày 11-08 | Fake catalog (H3) |
| H9 | Formatter + rule gate | M2 (M2-06, M2-07) | M4, L | Cuối ngày 11-08 | Stub decision trong stub mode của `run.py` |
| H10 | Stub mode `run.main` + writer | M4 (M4-04, M4-06) | L | Cuối ngày 11-08 | Gọi pipeline trực tiếp trong test |
| H11 | Scorer | L (L-10) | M2, M3 | Cuối ngày 11-07 | Chỉ golden test từ Brief |
| H12 | Harness trên Colab | L (L-12) | Tất cả | 11-09 | Script tạm (không được đưa ra kết luận về độ chính xác) |

---

## 7. Sơ đồ phụ thuộc (critical path P1)

```
L-02 ─► L-04 ──┬─► M1-03..M1-06 ─► M1-09 ─► M1-10 ─────────────┐
   (11-07)     ├─► M2-03 ─► M2-04 ──────────────────────────────┤
               ├─► M3-02, M3-03 ─► M3-04 ─► M3-05 (+M3-06/07) ──┼─► L-05 ─► L-06 ─► M3-08/L-13 ─► L-07 (DEC-3) ─► M4-09 ─► M4-10
               ├─► L-10, M2-06, M2-07 ──────────────────────────┤                                                     │
               └─► M4-04 ─► M4-05, M4-06, M4-07 ────────────────┘                                                     ▼
L-03 (E5 host) ─────────────────────────────────────────────────────────────────────────────────► M4-16 ─► M4-17 ─► M4-18 ─► L-09
M4-01 ─► M3-01, M4-02, M4-03 (base-image validation, day 0–1)
M1-11 fake catalogs, M3-13 replay fixtures ─► unblock M2/M3/M4/L tests before real components exist
```

---

## 8. Tổng hợp khối lượng

| Phụ trách | P1 | P2 | P3 | INT | COL | Tổng | Quỹ giờ (xấp xỉ) |
|---|---|---|---|---|---|---|---|
| Lead | 29 | — | — | 26 | 7 | 62 | 75 (sau khoảng 15 giờ stand-up, review, quyết định) |
| M1 | 38 | 14 | — | 10 | 2 | 64 | 90 |
| M2 | 33 | 18 | 6 | 8 | — | 65 | 90 |
| M3 | 34 | 14 | 6 | 6 | 4 | 64 | 90 |
| M4 | 37 | 4 | — | 22 | 3 | 66 | 90 |

Thời gian review (khoảng 1 giờ/người/ngày) nằm trong thời gian dự phòng. Chỉ sử dụng giờ P3 nếu quyết định ngày 11-12 phê duyệt.

---

## 9. Ánh xạ ID v1.0 → v1.1

| v1.0 | v1.1 | v1.0 | v1.1 | v1.0 | v1.1 |
|---|---|---|---|---|---|
| A-01 | M1-01 | B-01 | M2-01 | D-01 | L-10 |
| A-02 | M1-03 | B-02 | M1-02 | D-02 | L-11 |
| A-03 | M1-04 | B-03 | M2-02 | D-03 | M2-06 |
| A-04 | M1-05 | B-04 | M2-03 | D-04 | M2-07 |
| A-05 | M1-06 | B-05 | M2-04 | D-05 | L-12 |
| A-06 | M1-07 | B-06 | M2-05 | D-06 | L-13 |
| A-07 | M1-08 | B-07 | M2-08 | D-07 | L-14 |
| A-08 | M1-09 | B-08 | M2-09 | D-08 | M2-11 |
| A-09 | M1-10 | B-09 | M1-13 | D-09 | L-15 |
| A-10 | M1-12 | B-10 | M2-10 | D-10 | M2-12 |
| A-11 | M1-14 | B-11 | M2-14 | D-11 | M2-13 |
| C-01…C-13 | M3-01…M3-13 | E-01…E-18 | M4-01…M4-18 | D-12, D-13, D-14 | L-16, L-17, L-18 |

Mới trong v1.1: L-19, L-20, M1-11.

---

## 10. Backlog (chưa lên lịch; chỉ làm nếu còn thời gian sau 11-12 và Lead phê duyệt)

| ID | Hạng mục | Lý do hoãn |
|---|---|---|
| X-01 | Thử nghiệm LoRA fine-tuning (DEC-9) | Ngoài critical path; cần đầy đủ bộ bằng chứng DG §8 |
| X-02 | Entity linking dựa trên embedding | Ngân sách tham số; lexical linking trước (AP §8.3) |
| X-03 | Giải bài ở thinking mode với ngân sách giới hạn (DEC-10) | Chi phí runtime và tái lập; chỉ dùng nếu bake-off cho thấy cải thiện |
| X-04 | Luồng serving TP=2 | Chỉ dự phòng (DEC-13) |

M1 implementation/evidence: see `M1_IMPLEMENTATION.md`. P2 accuracy gates remain deferred until M3; `Review` is not a claim of merge approval.
