# Hướng dẫn nộp Docker

**Zalo AI Challenge 2026 – DataMate**

> **Nguồn:** `zac2026_DataMate_docker_guideline_final.pdf` (10 trang).  
> **Ghi chú chuyển đổi:** Bản Markdown này chép lại trung thực, dễ đọc nội dung hướng dẫn được cung cấp. Cấu trúc mục, yêu cầu, bảng, ví dụ, Dockerfile, lệnh shell và chú thích hình đều được giữ lại. Ảnh chụp terminal được thể hiện bằng chú thích cùng các lệnh/output liên quan nhìn thấy trong ảnh; PDF vẫn là nguồn có thẩm quyền đối với ảnh gốc. Không bổ sung diễn giải biên tập hoặc quy định thi đấu khác.

## Mục lục

1. [Tổng quan](#1-overview)
2. [Máy chấm bài](#2-test-machine)
3. [Input và output](#3-input-and-output)
   - [3.1. /data](#31-data)
   - [3.2. /result/submission.jsonl](#32-resultsubmissionjsonl)
   - [3.3. /result/logs/](#33-resultlogs)
4. [Bố cục thư mục trong image](#4-folder-layout-in-the-image)
5. [Quy định về predict.sh](#5-predictsh-rules)
6. [Khả năng tái lập](#6-reproducibility)
7. [Thời gian chạy](#7-run-time)
8. [README và mã training](#8-readme-and-training-code)
9. [Build image](#9-build-the-image)
10. [Kiểm tra trước khi nộp](#10-check-before-you-submit)
11. [Nộp image](#11-submit-the-image)

---

<a id="1-overview"></a>
## 1. Tổng quan

*Trang nguồn: 2.*

Nộp một Docker image chứa toàn bộ giải pháp inference, mã/dữ liệu training và các artifact phục vụ xác minh. Inference phải hoạt động offline. Chỉ base checkpoint mã nguồn mở, chỉ dùng cho training, mới được phép cung cấp qua liên kết công khai.

Nộp và đóng băng image trước khi công bố private test. Sau đó chạy image và upload `submission.jsonl` để lên bảng xếp hạng tạm thời. Lần chạy lại của ban tổ chức quyết định điểm và thứ hạng cuối cùng (Quy tắc 8).

Image phải chứa:

| Hạng mục | Ghi chú |
|---|---|
| Mã inference | Mã và dependency để đọc `/data`, ghi `/result`, hoàn toàn offline. |
| Mã training | Mã nguồn training/fine-tuning, config, dependency, log và hướng dẫn chạy (mục 8). |
| Pipeline dữ liệu training | Mã sinh/tiền xử lý, dữ liệu training/validation, log, checkpoint xác minh và manifest gồm đường dẫn local cùng checksum (mục 8). |
| Trọng số model | Mọi weight, tokenizer và config cần cho inference, gồm cả base model và adapter nếu sử dụng. |
| `predict.sh` | Entry point: `/data` → `/result/submission.jsonl` và `/result/logs/`. |
| `README.md` | Phương pháp, khai báo model và hướng dẫn chạy (mục 8). |

<a id="2-test-machine"></a>
## 2. Máy chấm bài

*Trang nguồn: 2–3.*

| Hạng mục | Giá trị |
|---|---|
| GPU | 2 × NVIDIA RTX 5090, mỗi GPU 32 GB VRAM (tổng 64 GB) |
| RAM | 512 GB |
| CUDA | CUDA ≥12.8; bản build PyTorch/vLLM tương thích, hỗ trợ Blackwell. |
| Base image | Khuyến nghị: `vllm/vllm-openai:v0.10.1.1` (đã kiểm thử với PyTorch 2.7.1+cu128 và vLLM 0.10.1.1). Phương án khác phải hỗ trợ RTX 5090 / compute capability 12.0. |
| Mạng | Tắt trong inference: không API hoặc download. |
| `/data` | Read-only. Ghi file tạm ở nơi khác, ví dụ `/tmp`. |
| Giới hạn thời gian | 6 giờ cho toàn bộ private test, bao gồm tải model (Quy tắc 7). |
| Model | Tổng mọi model inference: ≤15B tham số, gồm tất cả tham số MoE, kể cả khi được tải riêng. Bao gồm language model, embedding, reranking và classification model. Cho phép quantization (Quy tắc 2). |
| Kích thước image tối đa | 100 GB đối với file `.tar` chưa nén từ `docker save`, tính cả mọi layer của image. |

<a id="3-input-and-output"></a>
## 3. Input và output

*Trang nguồn: 3.*

### 3.1. /data

Mỗi test split chứa các file doanh nghiệp, câu hỏi và rulebook/calendar dùng chung như dưới đây.

```text
/data/
├── data/<business_id>/
│   ├── *.csv | *.xlsx | *.sqlite
│   └── README.md
├── rulebook.md              # split-specific rules and vocabulary
├── calendar.csv             # shared solar–lunar calendar
└── questions.jsonl          # id, business_id, question, as_of_date
```

### 3.2. /result/submission.jsonl

Mỗi dòng là một JSON object: `id`, `type` và `answer` đối với các kiểu giá trị (`number`, `percent`, `string`, `date`, `boolean`, `list`, `table`). `unanswerable` có thể kèm `reason`; `abstain` không cần answer. Câu hỏi bị thiếu được tính là abstain.

Ghi đáp án ngay khi có. Nếu lần chạy dừng sớm hoặc vượt 6 giờ, chỉ đáp án đã lưu được chấm; phần còn lại tính là abstain.

### 3.3. /result/logs/

Ghi một log record cho mỗi câu hỏi dưới `/result/logs/`. Chấp nhận mọi định dạng. Các trường bắt buộc:

- **`id`:** ID câu hỏi.
- **`answer`:** đáp án cuối cùng.
- **`elapsed_ms`:** số nguyên không âm biểu thị thời gian thực (wall-clock) tính bằng mili giây từ khi bắt đầu câu hỏi đến đáp án cuối cùng, gồm đọc dữ liệu, reasoning và thực thi mã. Khi batching, đo từ lúc câu hỏi vào batch. Thời gian tải model dùng chung được tính riêng nhưng vẫn thuộc giới hạn 6 giờ.
- **`thinking`:** reasoning của model cho câu hỏi này, ghi đúng như đã sinh (ví dụ văn bản trong `<think>…</think>` hoặc `reasoning_content` của vLLM). Không tóm tắt hoặc cắt ngắn. Nếu gọi model nhiều lần cho câu hỏi, ghi một list chuỗi theo thứ tự call. Dùng `null` nếu không sinh reasoning (ví dụ tắt thinking mode hoặc không gọi model).

Đối với câu hỏi được giải bằng mã, ghi thêm:

- **`code`:** mã thực tế được sinh và đã thực thi. Với Python định nghĩa sẵn, ghi file/hàm nguồn cùng input thực tế. Mã được sinh có thể gọi helper function đã đóng gói; hãy log lời gọi thực tế.
- **`output`:** giá trị trả về đã tính hoặc output thực thi. Không bắt buộc in ra stdout.

Nếu không thực thi mã, có thể bỏ `code` và `output` hoặc đặt null. Sinh mã là tùy chọn; log phải phản ánh phép tính thực tế.

*Trang nguồn: 4 — Dưới đây là hai cách ghi log thay thế cho cùng một câu hỏi, được trình bày giãn dòng để dễ đọc. Trong file thực tế, ghi một record trên một dòng cho mỗi câu hỏi.*

**Ví dụ 1. Mã do model sinh gọi một helper đã đóng gói.**

```json
{
  "id": "q_01234",
  "answer": {
    "type": "number",
    "answer": 48250000
  },
  "elapsed_ms": 8421,
  "thinking": "The question asks for biz_017 revenue month-to-date as of 2026-08-27, so the range is 2026-08-01 to 2026-08-27. sales.csv has date and amount columns; call compute_revenue over that range.",
  "code": "from src.metrics import compute_revenue\nresult = compute_revenue('/data/data/biz_017', start='2026-08-01', end='2026-08-27')",
  "output": 48250000
}
```

**Ví dụ 2. Gọi hàm đã đóng gói.**

```json
{
  "id": "q_0123",
  "answer": {
    "type": "number",
    "answer": 48250000
  },
  "elapsed_ms": 125,
  "thinking": null,
  "code": "src/metrics.py::compute_revenue",
  "inputs": {
    "data_dir": "/data/data/biz_017",
    "start": "2026-08-01",
    "end": "2026-08-27"
  },
  "output": 48250000
}
```

Trong Ví dụ 2, `inputs` là trường bổ trợ chứa đối số thực tế; `thinking` là null vì không sinh reasoning từ model. File/hàm nguồn được tham chiếu phải nằm trong Docker image; `output` có thể là giá trị trả về mà không cần stdout.

<a id="4-folder-layout-in-the-image"></a>
## 4. Bố cục thư mục trong image

*Trang nguồn: 4–5.*

Bố cục nội bộ được đề xuất như sau. `/code/predict.sh` và các đường dẫn input/output tại mục 3 là cố định. Ghi lại vị trí các thư mục khác trong `/code/README.md`.

```text
/code/
├── predict.sh                     # entry point
├── README.md
├── requirements.txt
├── src/                           # inference code
├── models/                        # model weights
└── training_code/
    ├── README.md
    ├── requirements.txt           # pinned training dependencies
    ├── train.sh                   # training entry point, if trained
    ├── configs/                   # training and generation settings
    ├── src/                       # training source code, if trained
    ├── data_generation/           # generation and preprocessing scripts
    ├── data/                      # train/validation data
    ├── logs/                      # training logs
    ├── checkpoints/               # verification checkpoints, if needed
    └── data_manifest.json         # local paths, SHA-256; base model public URLs
```

Đóng gói toàn bộ dữ liệu training, mã, dependency và bằng chứng xác minh. Chỉ base checkpoint mã nguồn mở chỉ dùng cho training mới được dẫn bằng link (mục 8). Loại bỏ file dư thừa; chỉ giữ optimizer state nếu cần để xác minh.

Đối với inference, phải có cả base model và adapter, hoặc một checkpoint đã merge. Link công khai của base model không thay thế được weight inference bắt buộc.

<a id="5-predictsh-rules"></a>
## 5. Quy định về predict.sh

*Trang nguồn: 5.*

1. Chạy `bash /code/predict.sh` không có đối số.
2. Đọc `/data`; ghi `submission.jsonl` và log từng câu hỏi dưới `/result`. Tạo các thư mục output còn thiếu.
3. Đặt giá trị mặc định cố định cho model, seed, temperature, batch size và các thiết lập khác. Ban tổ chức sẽ không sửa chúng.
4. Không can thiệp thủ công, hard-code đáp án hoặc viết logic dựa vào ID câu hỏi/doanh nghiệp.
5. Agent có thể sinh và thực thi mã bên trong container (tùy chọn; Quy tắc 5).

<a id="6-reproducibility"></a>
## 6. Khả năng tái lập

*Trang nguồn: 5.*

Yêu cầu tái lập là `|PA(uploaded) − PA(re-run)| ≤ 0.03`. Dùng seed cố định hoặc greedy decoding. Điểm của lần chạy lại là điểm cuối cùng (Quy tắc 8).

| Trường hợp | Cách xử lý |
|---|---|
| `|PA(uploaded) − PA(re-run)| ≤ 0.03` | Điểm chạy lại là điểm cuối cùng của đội. |
| Chênh lệch > 0.03 | Ban tổ chức xem log, có thể chạy lại image hoặc yêu cầu đội cung cấp thêm thông tin. |
| Không giải thích được chênh lệch | Bài dự thi bị loại. |

GPU batching có thể làm output thay đổi giữa các lần chạy, kể cả với greedy decoding. Trước khi nộp, chạy image hai lần với cùng input và so sánh hai file `submission.jsonl`, hoặc tính PA trên training set (có `answers.jsonl`). Quy tắc 8 so sánh PA private test mà đội upload với PA của lần chạy lại do ban tổ chức thực hiện.

<a id="7-run-time"></a>
## 7. Thời gian chạy

*Trang nguồn: 5.*

- Xử lý toàn bộ private test trong 6 giờ wall-clock trên máy tham chiếu, bao gồm tải và khởi tạo.
- Chỉ để tham khảo: khởi tạo Qwen3-14B mất khoảng 2 phút (128,155 ms), gồm compilation và CUDA graph.
- Khi hết thời gian, ban tổ chức dừng container; đáp án chưa lưu được tính là abstain.
- Tiêu chí phân hạng khi bằng điểm: tổng thời gian inference thấp hơn trong lần chạy lại của ban tổ chức, sau đó là thời điểm nộp sớm hơn.

<a id="8-readme-and-training-code"></a>
## 8. README và mã training

*Trang nguồn: 6.*

`/code/README.md` phải gồm:

- **Phương pháp:** cách đọc dữ liệu, sinh/thực thi mã và chọn đáp án.
- **Model:** tên, nguồn công khai, revision cố định, ngày phát hành gốc, license và số tham số. Weight gốc phải được phát hành trước ngày 26 tháng 10 năm 2026, với license cho phép sử dụng. Được phép fine-tuning; áp dụng tổng 15B ở mục 2.
- **Dữ liệu:** nguồn/phiên bản, phương pháp sinh/tiền xử lý và số mẫu train/validation.
- **Được phép:** dữ liệu training được cung cấp, dữ liệu tự sinh và dataset/model công khai. Tuyệt đối không train trên dữ liệu public/private test hoặc thu thập đáp án test (Quy tắc 6).

`/code/training_code/` phải hỗ trợ xác minh và tái lập. Bao gồm:

- **Mã/môi trường:** mã nguồn training và sinh/tiền xử lý dữ liệu, config, prompt/template, dependency đã pin phiên bản và seed. Cài dependency hoặc đóng gói môi trường offline.
- **Dữ liệu/bằng chứng:** toàn bộ dữ liệu train/validation, log, run config và checkpoint xác minh trong image. Lưu prompt/response đối với dữ liệu sinh qua API hoặc không thể tái lập.
- **README:** lệnh chuẩn bị/training/export chính xác, phần cứng, runtime, model/thiết lập sinh dữ liệu, checkpoint/adapter cuối cùng và mọi bước không tất định.
- **`data_manifest.json`:** đường dẫn local, nguồn/phiên bản, kích thước file, checksum SHA-256 và số lượng/split của dataset.

Với base checkpoint mã nguồn mở chỉ dùng cho training được lược khỏi image, cung cấp URL công khai, revision cố định, license, file cần thiết và checksum SHA-256. Mọi asset inference phải nằm trong image.

Ban tổ chức có thể tái lập quá trình chuẩn bị/training riêng, không tính vào giới hạn 6 giờ inference. Nêu rõ nếu không thực hiện training hoặc sinh dữ liệu.

<a id="9-build-the-image"></a>
## 9. Build image

*Trang nguồn: 6–8.*

Build cho `linux/amd64` cùng mọi asset inference/training cần thiết. Đảm bảo `.dockerignore` không loại bỏ dữ liệu training. Chỉ loại file không dùng và build cache.

Stack mẫu: Docker 24.0.5 với BuildKit.

1. Cài Docker/BuildKit và NVIDIA Container Toolkit. RTX 5090 cần driver tương thích từ R570 trở lên; làm theo hướng dẫn chính thức dưới đây.

   - Docker: https://docs.docker.com/engine/install/
   - NVIDIA Container Toolkit: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html

2. Pull base image:

   ```bash
   docker pull vllm/vllm-openai:v0.10.1.1
   ```

**Hình 1 (trang 7).** Môi trường mẫu: host kiểm thử bốn GPU; chấm bài dùng hai GPU. Ảnh terminal minh họa kiểm tra phiên bản Docker, truy vấn thiết bị GPU và kiểm tra CUDA capability từ container vLLM tham chiếu. Mẫu báo bốn GPU NVIDIA GeForce RTX 5090 với compute capability `(12, 0)` và `p2p 0->1: False`. Các lệnh liên quan:

```bash
docker --version
nvidia-smi --query-gpu=index,name,driver_version --format=csv
docker run --rm --gpus all --entrypoint "" vllm/vllm-openai:v0.10.1.1 python3 -c '
import torch, vllm
print("torch", torch.__version__, "cuda", torch.version.cuda, "| vllm", vllm.__version__)
for i in range(torch.cuda.device_count()):
    print(i, torch.cuda.get_device_name(i), torch.cuda.get_device_capability(i))
print("p2p 0->1:", torch.cuda.can_device_access_peer(0, 1))
'
```

3. Sao chép mã, weight inference, dữ liệu training và tài liệu xác minh vào `/code`. Bao gồm dependency và artifact manifest.
4. Cài thư viện trong Dockerfile. Với stack hai GPU được khuyến nghị:
   - Đặt lại `ENTRYPOINT []` để `docker run` thông thường khởi động `predict.sh`, thay vì vLLM server. Lệnh chấm bài cũng đặt `--entrypoint bash` (mục 10).
   - Mẫu đã xử lý lỗi treo khi khởi tạo hai GPU bằng cách nâng NCCL 2.26.2 lên `nvidia-nccl-cu12==2.27.7`. Xác minh workaround này với stack của đội.
   - Cặp GPU đã thử không có truy cập P2P; mẫu đặt `NCCL_P2P_DISABLE=1`. vLLM tắt custom all-reduce khi không có P2P.
   - Đặt `HF_HUB_OFFLINE=1` và `TRANSFORMERS_OFFLINE=1`; tải model local đã đóng gói.
5. Build và kiểm tra image. Dùng `zaic2026_datamate_<team_name>:final`, thay `<team_name>` bằng định danh đội viết thường.

```bash
docker build --platform linux/amd64 \
  -t zaic2026_datamate_<team_name>:final .
docker image inspect \
  -f '{{.Os}}/{{.Architecture}} {{.Size}}' \
  zaic2026_datamate_<team_name>:final
docker run --rm --network none --entrypoint "" \
  zaic2026_datamate_<team_name>:final find /code -maxdepth 2
```

**Hình 2 (trang 7).** Build image mẫu với weight Qwen3-14B. Mẫu dùng Dockerfile hai stage (`--target submit`); với Dockerfile tham chiếu một stage bên dưới, bỏ `--target`. Ảnh terminal cho thấy build từ `vllm/vllm-openai:v0.10.1.1` và kích thước image ví dụ là **50.5 GB** trong `docker images` (ví dụ export bên dưới báo 50.6 GB cho `.tar`).

**Hình 3 (trang 8).** Kiểm tra platform, kích thước và bố cục thư mục image. Output `docker image inspect` trong ví dụ là `linux/amd64`; image trong hình chứa `README.md`, `models/Qwen3-14B`, `predict.sh`, `requirements.txt`, `src/predict.py` và các artifact `training_code`. Ảnh hiển thị `28G /code/models/Qwen3-14B` (kích thước thư mục model mang tính minh họa).

Dockerfile tham chiếu với workaround NCCL của mẫu. Tách các bước `COPY` để giữ weight trong cache khi mã nguồn thay đổi.

```dockerfile
FROM vllm/vllm-openai:v0.10.1.1
ENTRYPOINT []
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
    PIP_NO_CACHE_DIR=1 NCCL_P2P_DISABLE=1
WORKDIR /code
COPY requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir -r /code/requirements.txt
RUN pip install --no-cache-dir --no-deps nvidia-nccl-cu12==2.27.7
COPY models/ /code/models/
COPY training_code/ /code/training_code/
COPY predict.sh README.md /code/
COPY src/ /code/src/
RUN chmod +x /code/predict.sh
CMD ["bash", "/code/predict.sh"]
```

Cài dependency training hoặc đóng gói môi trường training offline dưới `training_code/`. Kiểm thử image hoàn chỉnh bằng lệnh ở mục 10.

Dự trù ổ đĩa: mẫu dùng khoảng 57 GB cho image/build cache và thêm 50 GB tạm thời khi export trên Docker 24. Nhu cầu thực tế khác nhau; cần dành thêm chỗ cho dữ liệu training và file archive.

<a id="10-check-before-you-submit"></a>
## 10. Kiểm tra trước khi nộp

*Trang nguồn: 8–9.*

Kiểm thử bằng lệnh chấm bài: hai GPU, không mạng, input read-only và 16 GiB shared memory.

Ban tổ chức không cung cấp privileged mode, Docker socket, credential của host hoặc service của host.

```bash
docker run --rm --gpus '"device=0,1"' --network none --shm-size=16g \
  --entrypoint bash \
  -v /path/to/public_test:/data:ro \
  -v /path/to/output:/result \
  zaic2026_datamate_<team_name>:final /code/predict.sh
```

Mẫu vượt dung lượng `/dev/shm` mặc định 64 MiB khi NCCL cấp phát. `--shm-size=16g` giải quyết vấn đề dung lượng mà không cần host IPC. Lệnh chấm bài đặt `--entrypoint bash`, nên không dùng `ENTRYPOINT` riêng của image.

**Hình 4 (trang 9).** Ví dụ lỗi cấp phát NCCL với shared memory mặc định 64 MiB. Đặt `NCCL_SHM_DISABLE=1` không giải quyết được; dùng `--shm-size`. `--limit 10` chỉ là tùy chọn của mẫu; ban tổ chức chạy `predict.sh` không có đối số. Lỗi trong hình báo `torch.distributed.DistBackendError` / lỗi NCCL khi tạo shared memory segment và `No space left on device (28)`.

**Hình 5 (trang 9).** Smoke test mười câu hỏi hoàn tất với `--shm-size=16g`. `--limit 10` chỉ dành cho mẫu; ban tổ chức chạy `predict.sh` không có đối số. Kết quả này chưa chứng minh độ chính xác, determinism hoặc runtime trên toàn bộ test. Ví dụ cho thấy lần chạy 10 câu thành công, bước tải model và phần đầu output `submission.jsonl` hợp lệ. Lệnh ví dụ trong ảnh:

```bash
# Illustration shown in Figure 5; --limit 10 is NOT an organizer invocation.
docker run --rm --gpus '"device=2,3"' --network none --shm-size=16g -e GPU_MEM_UTIL=0.80 \
  -v "$PWD/data/public_test:/data:ro" -v "$PWD/out/submit_10:/result" \
  datamate_qwen14b:v1 bash /code/predict.sh --limit 10
```

Kiểm tra các điều sau:

- Chạy đến cuối không lỗi và không có mạng.
- `submission.jsonl` bao phủ mọi câu hỏi theo định dạng đã công bố.
- Mỗi câu hỏi có log record gồm `id`, `answer`, `elapsed_ms` và `thinking` (null nếu không sinh reasoning).
- Thời gian private test ước tính nằm trong 6 giờ: tải model + (thời gian trung bình mỗi câu hỏi khi chạy public hoặc training × 500).
- Hai lần chạy cho cùng đáp án, hoặc PA trên training set chênh không quá 0.03 (mục 6).
- Inference hoạt động offline; toàn bộ dữ liệu training, mã và bằng chứng xác minh đã được đóng gói.
- Export một image/tag `linux/amd64`; kích thước `.tar` chưa nén tối đa 100 GB (mục 2).

<a id="11-submit-the-image"></a>
## 11. Nộp image

*Trang nguồn: 9–10.*

1. Chỉ export image/tag `linux/amd64` cuối cùng và nén để upload. Chạy bằng Bash và thay `<team_name>` bằng định danh đội viết thường. Chạy `set -o pipefail` trước: nếu không, `docker save` thất bại vẫn để lại một file `.tar.gz` nhỏ và lệnh báo thành công. Sau đó đo kích thước `.tar` chưa nén từ archive:

   ```bash
   set -o pipefail
   docker save zaic2026_datamate_<team_name>:final | gzip > \
     zaic2026_datamate_<team_name>.tar.gz
   # uncompressed .tar size in bytes:
   gzip -dc zaic2026_datamate_<team_name>.tar.gz | wc -c
   ```

   Weight model khó nén: image mẫu giảm từ **50.6 GB** ở dạng `.tar` xuống **34.4 GB** ở dạng `.tar.gz`. `pigz -p 8` (và `pigz -dc`) nhanh hơn nhiều so với `gzip`, đồng thời tạo `.tar.gz` tiêu chuẩn.

2. Trên máy build, trước khi upload, ghi checksum MD5 của `.tar.gz` vào file (trên macOS, dùng `md5 -r` thay cho `md5sum`):

   ```bash
   md5sum zaic2026_datamate_<team_name>.tar.gz > zaic2026_datamate_<team_name>.tar.gz.md5
   ```

**Hình 6 (trang 10).** Trên máy build: kích thước `.tar` chưa nén và file MD5 gửi kèm upload. Trên máy đã tải archive: `md5sum -c` so sánh bản sao đó với MD5 từ máy build. Mẫu minh họa xác minh checksum thành công với `OK`.

3. Upload `.tar.gz`, gửi link cùng file `.md5` (hoặc một dòng nội dung của file) và kích thước `.tar` chưa nén tính bằng byte cho ban tổ chức. Ban tổ chức kiểm tra bản sao bằng `md5sum -c zaic2026_datamate_<team_name>.tar.gz.md5`: `OK` nghĩa là archive nhận được nguyên vẹn, `FAILED` nghĩa là phải upload lại.
4. Không đổi tên archive sau khi tạo file `.md5`. Trước khi gửi, tải archive từ link của đội trên một máy khác rồi chạy cùng phép kiểm tra để chắc chắn link hoạt động và file nguyên vẹn.
5. Artifact manifest phải nằm trong image; mọi tham chiếu model bên ngoài chỉ được dành cho base checkpoint mã nguồn mở đủ điều kiện và chỉ dùng cho training.

Sau hạn nộp giải pháp, không được thay đổi image, mã, config, model, dữ liệu training, artifact sinh dữ liệu hoặc revision và checksum của base checkpoint công khai đã khai báo.

---

*Kết thúc Hướng dẫn nộp Docker gồm 10 trang.*
