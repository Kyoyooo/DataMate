"""Local scorer for DataMate following the organizer's matching rules (CLAUDE.md, rulebook §9).

Usage:
  python eval.py submission.jsonl                   # score all of train
  python eval.py submission.jsonl --split holdout   # holdout shops only (split.json)
  python eval.py submission.jsonl --show 20         # print 20 wrong answers
  python eval.py --selftest
"""
import argparse, json, re, unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
EPS = 1e-6  # only ignore floating-point error


def norm(s):
    s = unicodedata.normalize("NFC", str(s)).lower()
    s = re.sub(r"[^\w\s]|_", " ", s)  # \w keeps accented letters; '_' is not a letter/digit
    return " ".join(s.split())


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def num_eq(p, g):
    return is_num(p) and abs(p - g) <= EPS


def pct_eq(p, g):
    return is_num(p) and abs(round(p, 2) - round(g, 2)) <= EPS


def str_eq(p, g, alias=()):
    return isinstance(p, str) and norm(p) in {norm(x) for x in [g, *alias]}


def cell_eq(p, g, alias=()):
    return str_eq(p, g, alias) if isinstance(g, str) else num_eq(p, g)


def table_eq(p, g, alias):
    if not (isinstance(p, dict) and isinstance(p.get("columns"), list) and isinstance(p.get("rows"), list)):
        return False
    gcols, pcols = [norm(c) for c in g["columns"]], [norm(c) for c in p["columns"]]
    if len(pcols) != len(gcols) or len(p["rows"]) != len(g["rows"]):
        return False
    # each column: match by name, otherwise by position
    idx = [pcols.index(c) if c in pcols else i for i, c in enumerate(gcols)]
    if sorted(idx) != list(range(len(gcols))):
        return False
    rows = [r for r in p["rows"] if isinstance(r, list) and len(r) == len(gcols)]
    if len(rows) != len(g["rows"]):
        return False
    used = [False] * len(rows)
    for gi, grow in enumerate(g["rows"]):  # rows compared as a set
        ral = alias[gi] if gi < len(alias) else []
        for pi, prow in enumerate(rows):
            if not used[pi] and all(cell_eq(prow[idx[c]], grow[c], ral if c == 0 else ()) for c in range(len(gcols))):
                used[pi] = True
                break
        else:
            return False
    return True


def score(pred, gold):
    """+1 correct, 0 abstain/missing, -1 wrong."""
    if pred is None or pred.get("type") in (None, "abstain"):
        return 0
    t, g, al = gold["type"], gold["answer"], gold.get("alias") or []
    if pred["type"] != t:
        return -1
    if t == "unanswerable":
        return 1
    if "answer" not in pred:
        return -1
    p = pred["answer"]
    ok = {
        "number": lambda: num_eq(p, g),
        "percent": lambda: pct_eq(p, g),
        "string": lambda: str_eq(p, g, al),
        "date": lambda: isinstance(p, str) and p == g,
        "boolean": lambda: isinstance(p, bool) and p == g,
        "list": lambda: isinstance(p, list) and len(p) == len(g)
        and all(cell_eq(pe, ge, al[i] if i < len(al) else ()) for i, (pe, ge) in enumerate(zip(p, g))),
        "table": lambda: table_eq(p, g, al),
    }[t]()
    return 1 if ok else -1


def load(path):
    return {r["id"]: r for r in map(json.loads, Path(path).read_text(encoding="utf-8").splitlines()) if r}


def read_submission(path):
    out = {}
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue  # broken lines count as missing
        if isinstance(r, dict) and "id" in r:
            out[r["id"]] = r
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("submission", nargs="?")
    ap.add_argument("--gold", default=ROOT / "train/answers.jsonl")
    ap.add_argument("--questions", default=ROOT / "train/questions.jsonl")
    ap.add_argument("--split", choices=["dev", "holdout"])
    ap.add_argument("--show", type=int, default=0, help="in N câu sai")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--only", help="chỉ chấm các câu có trong file questions.jsonl này (vd mẫu train)")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.submission:
        ap.error("cần đường dẫn submission")

    gold, qs, sub = load(a.gold), load(a.questions), read_submission(a.submission)
    if a.split:
        shops = set(json.loads((ROOT / "split.json").read_text())[a.split])
        gold = {i: g for i, g in gold.items() if qs[i]["business_id"] in shops}
    if a.only:
        keep = set(load(a.only))
        gold = {i: g for i, g in gold.items() if i in keep}

    by_type, by_biz, wrong = defaultdict(Counter), defaultdict(Counter), []
    total = 0
    for i, g in gold.items():
        s = score(sub.get(i), g)
        total += s
        k = {1: "đúng", 0: "bỏ", -1: "sai"}[s]
        by_type[g["type"]][k] += 1
        by_biz[qs[i]["business_id"]][k] += 1
        if s < 0:
            wrong.append(i)

    n = len(gold)
    def row(name, c):
        m = sum(c.values())
        return f"{name:<14}{m:>6}{c['đúng']:>7}{c['sai']:>6}{c['bỏ']:>6}{(c['đúng'] - c['sai']) / m:>8.3f}"
    hdr = f"{'':<14}{'N':>6}{'đúng':>7}{'sai':>6}{'bỏ':>6}{'PA':>8}"
    print(f"PA = {total / n:.4f}  (N={n}{', split=' + a.split if a.split else ''})\n")
    print(hdr)
    for t in sorted(by_type, key=lambda t: -sum(by_type[t].values())):
        print(row(t, by_type[t]))
    print("\n" + hdr)
    for b in sorted(by_biz):
        print(row(b, by_biz[b]))
    for i in wrong[: a.show]:
        print(f"\n[{i}] {qs[i]['business_id']} {qs[i]['as_of_date']} | {qs[i]['question']}")
        print("  gold:", json.dumps({k: gold[i][k] for k in ("type", "answer")}, ensure_ascii=False))
        print("  pred:", json.dumps(sub.get(i), ensure_ascii=False))


def selftest():
    g = lambda t, ans, al=(): {"type": t, "answer": ans, "alias": list(al)}
    cases = [
        ({"type": "number", "answer": 48250000}, g("number", 48250000), 1),
        ({"type": "number", "answer": "48250000"}, g("number", 48250000), -1),
        ({"type": "number", "answer": True}, g("number", 1), -1),
        ({"type": "percent", "answer": -12.449}, g("percent", -12.45), 1),
        ({"type": "percent", "answer": 12.45}, g("percent", -12.45), -1),
        ({"type": "string", "answer": "XI MĂNG hà tiên PCB40, bao 50kg"}, g("string", "Xi măng Hà Tiên PCB40 bao 50kg"), 1),
        ({"type": "string", "answer": "xi mang ha tien pcb40 bao 50kg"}, g("string", "Xi măng Hà Tiên PCB40 bao 50kg"), -1),
        ({"type": "string", "answer": "sp0001"}, g("string", "Xi măng", ["SP0001"]), 1),
        ({"type": "list", "answer": ["SP0003", "b"]}, g("list", ["a", "b"], [["SP0003"], []]), 1),
        ({"type": "list", "answer": ["b", "a"]}, g("list", ["a", "b"]), -1),
        ({"type": "date", "answer": "2025-09"}, g("date", "2025-09"), 1),
        ({"type": "boolean", "answer": 1}, g("boolean", True), -1),
        ({"type": "unanswerable"}, g("unanswerable", None), 1),
        ({"type": "number", "answer": 0}, g("unanswerable", None), -1),
        ({"type": "abstain"}, g("number", 5), 0),
        (None, g("number", 5), 0),
        ({"type": "table", "answer": {"columns": ["so_tien_no", "khach_hang"], "rows": [[200, "B"], [100, "kh01"]]}},
         g("table", {"columns": ["khach_hang", "so_tien_no"], "rows": [["A", 100], ["B", 200]]}, [["KH01"], []]), 1),
        ({"type": "table", "answer": {"columns": ["x", "y"], "rows": [["A", 100], ["B", 201]]}},
         g("table", {"columns": ["khach_hang", "so_tien_no"], "rows": [["A", 100], ["B", 200]]}), -1),
    ]
    for k, (p, gd, want) in enumerate(cases):
        assert score(p, gd) == want, (k, p, gd, score(p, gd))
    print(f"selftest ok ({len(cases)} cases)")


if __name__ == "__main__":
    main()
