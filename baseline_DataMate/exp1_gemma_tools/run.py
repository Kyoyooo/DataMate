"""Run DataMate on one dataset, writing submission.jsonl line by line.

One workflow: load shops → Gemma (thinking) reads the question and picks one tool → the rules (rules.py) compute → write answer + log.
python run.py --data /data --out /result/submission.jsonl --llm models/gemma-4-12B-it --tp 2
The --data folder must contain questions.jsonl and the shop folders (data/biz_xxx or biz_xxx), plus calendar.csv if any.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path


def find_layout(root):
    root = Path(root)
    qf = next((p for p in [root / "questions.jsonl", *root.rglob("questions.jsonl")] if p.exists()), None)
    if qf is None:
        sys.exit(f"không thấy questions.jsonl trong {root}")
    shops = next((d for d in [qf.parent / "data", root / "data", root] if d.is_dir() and any(d.glob("*/README.md"))), None)
    cal = next((p for p in [qf.parent / "calendar.csv", root / "calendar.csv", *root.rglob("calendar.csv")] if p.exists()), None)
    return qf, shops, cal


def _warm(args):
    from datamate.load import Shop
    folder, root = args
    try:
        Shop(folder, root)
        return folder.name, None
    except Exception as e:  # a broken shop does not stop the run; its questions will abstain
        return folder.name, f"{type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/data")
    ap.add_argument("--out", default="/result/submission.jsonl")
    ap.add_argument("--llm", required=True, help="thư mục model (vLLM)")
    ap.add_argument("--logs", help="thư mục log từng câu (mặc định <thư mục out>/logs)")
    ap.add_argument("--tp", type=int, default=1, help="tensor parallel (số GPU)")
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    ap.add_argument("--chunk", type=int, default=256, help="số câu mỗi lô LLM; ghi kết quả sau mỗi lô")
    a = ap.parse_args()
    t0 = time.time()
    qf, shops_dir, cal = find_layout(a.data)
    if cal:
        os.environ["DATAMATE_CALENDAR"] = str(cal)
    os.environ.setdefault("DATAMATE_CACHE", "/tmp/datamate_cache")
    qs = [json.loads(l) for l in qf.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"{len(qs)} câu, shop ở {shops_dir}, lịch {cal}", file=sys.stderr)

    # 1. load + cache every shop in parallel (reading Excel is the slowest part)
    need = sorted({q["business_id"] for q in qs})
    broken = {}
    with Pool(a.workers) as pool:
        for b, err in pool.imap_unordered(_warm, [(shops_dir / b, shops_dir) for b in need if (shops_dir / b).is_dir()]):
            if err:
                broken[b] = err
                print(f"[nạp lỗi] {b}: {err}", file=sys.stderr)
    print(f"nạp xong {len(need)} shop sau {time.time() - t0:.0f}s", file=sys.stderr)

    from datamate.checks import vet_unanswerable
    from datamate.llm import LLMRunner, answer_with_llm
    from datamate.load import Shop
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():  # rerun after an interruption: keep the lines already written
        done = {json.loads(l)["id"] for l in out.read_text(encoding="utf-8").splitlines() if l.strip()}
    logdir = Path(a.logs) if a.logs else out.parent / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    logf = (logdir / "log.jsonl").open("a", encoding="utf-8")

    def emit(f, q, res, ms, call=None, thinking=None):
        """submission: one line per question, written immediately. log (organizer format): id, answer, elapsed_ms, thinking, code, inputs, output."""
        if res.get("type") != "unanswerable":
            res.pop("reason", None)
        f.write(json.dumps({"id": q["id"], **res}, ensure_ascii=False, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())
        ans = {k: v for k, v in res.items() if k in ("type", "answer", "reason")}
        inputs = {"data_dir": str(shops_dir / q["business_id"]), "question": q["question"], "as_of_date": q["as_of_date"], "tool_call": call}
        logf.write(json.dumps({"id": q["id"], "answer": ans, "elapsed_ms": max(0, int(ms)), "thinking": thinking,
                               "code": f"datamate/tools.py::{call.get('tool')}" if call else None, "inputs": inputs,
                               "output": ans.get("answer")}, ensure_ascii=False, default=str) + "\n")
        logf.flush()

    todo = [q for q in sorted(qs, key=lambda q: q["business_id"]) if q["id"] not in done]
    with out.open("a", encoding="utf-8") as f:
        ok = []
        for q in todo:  # missing shop / load error: no data to compute from → abstain
            if q["business_id"] in broken or not (shops_dir / q["business_id"]).is_dir():
                emit(f, q, {"type": "abstain"}, 0)
            else:
                ok.append(q)
        # 2. load the model once
        runner = LLMRunner(a.llm, tp=a.tp, think=True)
        print(f"nạp model xong sau {time.time() - t0:.0f}s", file=sys.stderr)
        shops = {}
        for i in range(0, len(ok), a.chunk):  # large batches so vLLM runs in parallel; write after each batch
            group, tb = ok[i:i + a.chunk], time.time()
            for q in group:
                if q["business_id"] not in shops:
                    shops[q["business_id"]] = Shop(shops_dir / q["business_id"], shops_dir)
            items = [(shops[q["business_id"]], q["question"], dt.date.fromisoformat(q["as_of_date"])) for q in group]
            # 3. Gemma picks a tool → 4. the rules compute
            res, calls = answer_with_llm(runner, items)
            ms = (time.time() - tb) * 1000 / len(group)
            for q, (shop, _, _), r, c, txt in zip(group, items, res, calls, runner.texts):
                # 5. keep unanswerable only when the shop really lacks that information
                emit(f, q, vet_unanswerable(shop, dict(r)), ms, c, txt)
            print(f"LLM {i + len(group)}/{len(ok)} câu, {time.time() - t0:.0f}s", file=sys.stderr)
    print(f"xong sau {time.time() - t0:.0f}s → {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
