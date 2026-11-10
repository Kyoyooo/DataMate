"""Step 3 (needs GPU): the LLM reads the question → one JSON tool call → tools.execute.

Only build_messages / parse run on CPU; LLMRunner needs vLLM + GPU.
Model bake-off:  python -m datamate.llm --model /models/Qwen3-14B --data train --split holdout --out runs/llm_qwen14.jsonl
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from . import rules as R
from .fewshot import EXAMPLES
from .tools import call_schema, catalog_text, execute, ordered

SYSTEM = """Bạn là trợ lý phân tích dữ liệu bán hàng của cửa hàng nhỏ ở Việt Nam.
Nhiệm vụ: đọc câu hỏi tiếng Việt (có thể viết tắt, không dấu, gõ sai) và chọn ĐÚNG MỘT công cụ trong danh sách, điền tham số. Không tự tính toán.

Quy ước mốc thời gian (period):
- "tháng M/YYYY", "T M/YYYY", "th M/YYYY", "M-YYYY", "M/YYYY" → {"type":"month","month":M,"year":YYYY} (T3/2026 là THÁNG 3, không phải quý 3).
- "M/YY" với YY hai chữ số (5/25, 2/25, 7/25) → THÁNG M năm 20YY, không phải ngày. Ngày luôn có đủ dd/mm hoặc dd/mm/yyyy.
- "tháng M" không ghi năm → {"type":"month","month":M} (bỏ year, hệ thống tự suy năm). "th nay", "t nay" → this_month.
- "N ngày qua/gần nhất/gần đây" (kể cả "tính cả hôm nay") → {"type":"last_n_days","n":N}.
- "hôm nay", "bữa nay", "hnay" → today; "hôm qua", "bữa qua" → yesterday; "ngày dd/mm/yyyy" → {"type":"day","date":"YYYY-MM-DD"}.
- "tuần này" → this_week; "tuần trước/tuần rồi" → last_week; "tháng này", "từ đầu tháng đến nay" → this_month; "tháng trước" → last_month.
- "quý Q năm Y", "quý Q/YYYY" → {"type":"quarter","quarter":Q,"year":Y} (không phải tháng); "từ đầu năm (đến nay)", "từ 1/1 đến hết hôm nay" → ytd; "N ngày gần nhất" → last_n_days; "từ A đến hết B" → range.
- "Tết năm Y", "dịp Tết" → {"type":"tet","year":Y}.
So sánh % (revenue_change_pct): "so với tháng/kỳ trước", "tháng liền trước" → previous; "cùng kỳ tháng trước" (từ đầu tháng này đến hôm nay) → same_period_last_month; "cùng kỳ năm trước/năm ngoái" → same_period_last_year; "so với trước Tết" → before_tet; "Tết năm trước" → last_year_tet.
Tên mặt hàng, nhóm hàng, hoạt chất: chép đúng như trong danh sách nếu có; KHÔNG có trong danh sách (danh sách có thể bị rút gọn) thì vẫn chép nguyên tên trong câu hỏi, hệ thống tự khớp. Không vì thiếu tên trong danh sách mà trả unanswerable/abstain.
Câu chủ quan (chất lượng tốt nhất, khách trung thực, nhân viên tận tâm, khen...) → unanswerable, reason bắt đầu bằng "chủ quan". Câu hỏi kiến thức ngoài dữ liệu → unanswerable, reason "ngoài dữ liệu". Thông tin cửa hàng không ghi → unanswerable, reason nêu thông tin bị thiếu.
Chủ quan gồm cả: uy tín, đáng tin cậy, chất lượng tốt, ngon nhất, dễ thương, tận tâm.
Từ viết tắt / dễ nhầm:
- "đh", "dh", "đơn", "hđ" = ĐƠN HÀNG: "bao nhiêu đh" là SỐ ĐƠN (order_count), không phải doanh thu.
- "ca" không dấu đứng trước kỳ ("ca th8/2025", "ca tuan") = "cả" (cả tháng), không phải ca làm việc; ca làm việc chỉ khi có "ca sáng/ca chiều".
- "bán thiếu", "bán chịu", "ghi sổ", "cho nợ" = bán nợ → công cụ nợ (debt_*), "khách trả nợ" → debt_collected.
- Tiệm sửa xe: câu về thợ / phiếu dùng sx_* (tiền một thợ → sx_staff what=revenue).
Quyết định nhanh: chọn cách hiểu tự nhiên nhất rồi trả lời, không cân nhắc lặp lại.
Hỏi kèm lý do/nguyên nhân (huỷ vì giao trễ, trả hàng vì lỗi...) mà dữ liệu không ghi lý do → unanswerable, không đếm hết mọi đơn.
Không có công cụ phù hợp → abstain.
Chỉ trả về một đối tượng JSON.

Công cụ:
"""


def shop_context(shop, max_items=300):
    from .entity import products
    from .rules import groups, ingredients
    names = sorted({nm for _, (_, nm) in products(shop).items() if " + " not in str(nm)})[:max_items]  # drop topping-combo names to keep it short
    lines = [f"Cửa hàng {shop.id}. Dữ liệu từ {shop.data_start} đến {shop.data_end}.",
             "Bảng có: " + ", ".join(sorted(k for k in shop.t if k != "other")) + "."]
    from .industry import _mb_ready
    L = shop.t.get("lines")
    if L is not None and "vehicle" in L:
        lines.append("Ngành: tiệm sửa xe → câu về thợ, phiếu, lượt xe, dòng xe, hoa hồng, bảo hành dùng công cụ sx_*.")
    elif L is not None and "imei" in L:
        lines.append("Ngành: cửa hàng điện thoại → câu về máy, dòng máy, hãng, máy cũ, trả góp, nợ, bảo hành dùng công cụ dt_*.")
    elif L is not None and _mb_ready(shop):
        lines.append("Ngành: mẹ và bé → câu về bỉm/tã, size, sữa bột số, voucher, điểm, phí ship, thành viên dùng công cụ mb_*.")
    if g := groups(shop):
        lines.append("Nhóm hàng: " + "; ".join(map(str, g)) + ".")
    if i := ingredients(shop):
        lines.append("Hoạt chất: " + "; ".join(map(str, i)) + ".")
    lines.append("Mặt hàng: " + "; ".join(names) + ".")
    return "\n".join(lines)


def build_messages(shop, question, as_of):
    msgs = [{"role": "system", "content": SYSTEM + catalog_text()}]
    for _, q, call in EXAMPLES:
        msgs.append({"role": "user", "content": f"Câu hỏi: {q}"})
        msgs.append({"role": "assistant", "content": json.dumps(ordered(call), ensure_ascii=False)})
    msgs.append({"role": "user", "content": f"{shop_context(shop)}\nHôm nay: {as_of}\nCâu hỏi: {question}"})
    return msgs


def parse(text):
    import re
    m = list(re.finditer(r'\{\s*"tool"\s*:', text))  # thinking mode: take the last tool call, skip the draft before it
    try:
        call = json.loads(text[m[-1].start() if m else text.find("{"): text.rfind("}") + 1])
        return call if isinstance(call, dict) else {"tool": "abstain"}
    except json.JSONDecodeError:
        return {"tool": "abstain"}


class LLMRunner:
    """Offline vLLM, schema-constrained decoding, temperature 0, fixed seed (reproducible)."""

    def __init__(self, model, tp=1, max_len=None, gpu_util=None, think=False):
        max_len = max_len or int(os.environ.get("DATAMATE_MAXLEN", 16384))
        gpu_util = gpu_util or float(os.environ.get("DATAMATE_GPU_UTIL", 0.88))
        # the FlashInfer sampler must be compiled (needs g++); with temperature 0 the PyTorch sampler gives the same result
        os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")
        from vllm import LLM, SamplingParams
        try:  # newer vLLM (needed for Gemma 4, Blackwell)
            from vllm.sampling_params import StructuredOutputsParams
            guided = {"structured_outputs": StructuredOutputsParams(json=call_schema())}
        except ImportError:  # vLLM 0.10.x
            from vllm.sampling_params import GuidedDecodingParams
            guided = {"guided_decoding": GuidedDecodingParams(json=call_schema())}
        self.llm = LLM(model=model, tensor_parallel_size=tp, max_model_len=max_len, seed=0,
                       enable_prefix_caching=True, gpu_memory_utilization=gpu_util)
        self.think = think
        # with thinking, do not constrain to JSON (constraints block the draft); parse takes the last call
        self.sp = (SamplingParams(temperature=0, max_tokens=6144, seed=0) if think
                   else SamplingParams(temperature=0, max_tokens=400, seed=0, **guided))

    def calls(self, conversations):
        # templates that do not use enable_thinking ignore it, so pass it for every model
        outs = self.llm.chat(conversations, self.sp, use_tqdm=True, chat_template_kwargs={"enable_thinking": self.think})
        self.texts = [o.outputs[0].text for o in outs]  # raw text, including the thinking part: written to the log
        return [parse(t) for t in self.texts]


def answer_with_llm(runner, items):
    """items: [(shop, question, as_of_date)] → [result dict]. Batched so vLLM runs them in parallel."""
    convs = [build_messages(s, q, d) for s, q, d in items]
    calls = runner.calls(convs)
    return [execute(s, c, d) for (s, _, d), c in zip(items, calls)], calls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", default="train")
    ap.add_argument("--split", choices=["dev", "holdout", "all"], default="holdout")
    ap.add_argument("--out", required=True)
    ap.add_argument("--tp", type=int, default=1)
    ap.add_argument("--think", action="store_true")
    a = ap.parse_args()
    from .load import Shop
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from run import find_layout
    qf, shops_dir, cal = find_layout(a.data)
    if cal:
        os.environ["DATAMATE_CALENDAR"] = str(cal)
    qs = [json.loads(l) for l in qf.read_text(encoding="utf-8").splitlines() if l]
    if a.split != "all":
        keep = set(json.loads(Path("split.json").read_text())[a.split])
        qs = [q for q in qs if q["business_id"] in keep]
    shops = {b: Shop(shops_dir / b, shops_dir) for b in sorted({q["business_id"] for q in qs})}
    items = [(shops[q["business_id"]], q["question"], dt.date.fromisoformat(q["as_of_date"])) for q in qs]
    from .checks import vet_unanswerable
    runner = LLMRunner(a.model, tp=a.tp, think=a.think)
    res, calls = answer_with_llm(runner, items)
    # .vet: keep unanswerable only when the shop really lacks that information (checks.vet_unanswerable)
    with open(a.out, "w", encoding="utf-8") as f, open(a.out.replace(".jsonl", ".vet.jsonl"), "w", encoding="utf-8") as g:
        for q, (s, _, _), r, c in zip(qs, items, res, calls):
            r.pop("reason", None) if r.get("type") != "unanswerable" else None
            f.write(json.dumps({"id": q["id"], **r, "_call": c}, ensure_ascii=False, default=str) + "\n")
            g.write(json.dumps({"id": q["id"], **vet_unanswerable(s, dict(r))}, ensure_ascii=False, default=str) + "\n")
    print(f"ghi {len(qs)} dòng → {a.out}; chấm: python eval.py {a.out} --split {a.split if a.split != 'all' else ''}", file=sys.stderr)


if __name__ == "__main__":
    main()
