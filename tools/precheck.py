#!/usr/bin/env python3
"""Pre-submission checks (DG §10, SPEC §13.3, TASKS M4-14). Use via ``tools/precheck.sh``.

Result-directory checks (always):
  C1  submission.jsonl has exactly one valid line per question id of the split, no extras/duplicates
  C2  logs/questions.jsonl has a valid record per id with id, answer, elapsed_ms (int >= 0), thinking
      (null or list of str); ``answer`` equals the submission line; ``code`` present => ``output`` present
  C3  logs/run.json exists and its counts match
  C4  runtime projection: replica load + mean per-question time x 500 vs the 6 h limit
Optional:
  --compare DIR     second result dir of the same input: identical submissions or the differing ids
  --answers FILE    training reference answers: PA (never use test data)
  --image TAG       docker image: linux/amd64, required /code files, README without ``TO FILL``,
                    model dir non-empty; --measure-tar adds the exact uncompressed ``docker save`` size
Exit 0 = every check passed, 1 = at least one failed, 2 = usage error. One line per check.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

LIMIT_S = 6 * 3600
TAR_LIMIT = 100 * 10**9
REQUIRED_IMAGE_FILES = ["/code/predict.sh", "/code/README.md", "/code/requirements.txt",
                        "/code/config/run_config.json", "/code/src/datamate/run.py",
                        "/code/training_code/README.md", "/code/training_code/data_manifest.json"]


class Report:
    def __init__(self) -> None:
        self.failed = 0

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.failed += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} {name}{': ' + detail if detail else ''}")

    def info(self, name: str, detail: str) -> None:
        print(f"INFO {name}: {detail}")


def read_jsonl(path: Path) -> tuple[list[dict], list[int]]:
    from datamate.contracts.jsonio import loads_exact  # decimals stay exact (percent 16.67)

    rows, bad = [], []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            rows.append(loads_exact(line))
        except json.JSONDecodeError:
            bad.append(n)
    return rows, bad


def check_result(rep: Report, data_dir: Path, result_dir: Path) -> dict[str, dict]:
    from datamate.contracts import LogRecord, SubmissionRecord

    ids: list[str] = []
    seen: set[str] = set()
    for line in (data_dir / "questions.jsonl").read_text(encoding="utf-8-sig").splitlines():
        if line.strip():
            try:
                qid = json.loads(line).get("id")
            except (json.JSONDecodeError, AttributeError):
                continue
            if isinstance(qid, str) and qid and qid not in seen:
                seen.add(qid)
                ids.append(qid)
    sub_path = result_dir / "submission.jsonl"
    if not sub_path.is_file():
        rep.check("C1 submission.jsonl exists", False, str(sub_path))
        return {}
    rows, bad = read_jsonl(sub_path)
    problems = [f"line {n}: not JSON" for n in bad]
    by_id: dict[str, dict] = {}
    for n, row in enumerate(rows, 1):
        try:
            rec = SubmissionRecord.model_validate(row)
        except Exception as exc:  # noqa: BLE001 - report any validation failure
            problems.append(f"line {n}: {str(exc).splitlines()[0][:80]}")
            continue
        if rec.id in by_id:
            problems.append(f"duplicate id {rec.id}")
        by_id[rec.id] = row
    missing, extra = sorted(set(ids) - set(by_id)), sorted(set(by_id) - set(ids))
    if missing:
        problems.append(f"{len(missing)} missing ids, e.g. {missing[0]}")
    if extra:
        problems.append(f"{len(extra)} unknown ids, e.g. {extra[0]}")
    rep.check("C1 submission.jsonl: one valid line per question id", not problems,
              "; ".join(problems[:3]) or f"{len(ids)} questions")

    log_path = result_dir / "logs" / "questions.jsonl"
    problems = []
    logs: dict[str, dict] = {}
    if not log_path.is_file():
        problems.append("logs/questions.jsonl missing")
    else:
        lrows, bad = read_jsonl(log_path)
        problems += [f"line {n}: not JSON" for n in bad]
        for n, row in enumerate(lrows, 1):
            for key in ("id", "answer", "elapsed_ms", "thinking"):
                if key not in row:
                    problems.append(f"line {n}: missing {key}")
            ms = row.get("elapsed_ms")
            if not isinstance(ms, int) or isinstance(ms, bool) or ms < 0:
                problems.append(f"line {n}: elapsed_ms must be an int >= 0")
            th = row.get("thinking")
            if th is not None and not (isinstance(th, list) and all(isinstance(x, str) for x in th)):
                problems.append(f"line {n}: thinking must be null or a list of strings")
            if row.get("code") is not None and "output" not in row:
                problems.append(f"line {n}: code without output")
            try:
                LogRecord.model_validate(row)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"line {n}: {str(exc).splitlines()[0][:80]}")
            qid = row.get("id")
            if qid in logs:
                problems.append(f"duplicate log for {qid}")
            logs[qid] = row
            sub = by_id.get(qid)
            if sub is not None and row.get("answer") != {k: v for k, v in sub.items() if k != "id"}:
                problems.append(f"{qid}: log answer differs from submission")
        missing = sorted(set(ids) - set(logs))
        if missing:
            problems.append(f"{len(missing)} ids without a log record, e.g. {missing[0]}")
    rep.check("C2 logs/questions.jsonl: required fields, one record per id", not problems,
              "; ".join(problems[:3]) or f"{len(logs)} records")

    run_path = result_dir / "logs" / "run.json"
    try:
        run = json.loads(run_path.read_text(encoding="utf-8"))
        counts = run["counts"]
        ok = counts.get("written") == counts.get("questions") == len(ids)
        rep.check("C3 logs/run.json counts match", ok, f"questions={counts.get('questions')} "
                  f"written={counts.get('written')} split={len(ids)}")
        project(rep, run, len(ids))
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        rep.check("C3 logs/run.json readable with counts", False, f"{type(exc).__name__}: {exc}")
    return by_id


def project(rep: Report, run: dict, n: int) -> None:
    t = run.get("timings") or {}
    load = max([x for x in (t.get("replica_load_ms") or []) if x is not None], default=None)
    total = t.get("total_ms") or run.get("total_ms")
    if load is None or not total or not n:
        rep.info("C4 runtime projection", "not enough timing data in run.json (no replicas?)")
        return
    per_q = (total - load) / n / 1000
    est = load / 1000 + per_q * 500
    rep.check("C4 projected private-test time <= 50% of 6 h", est <= LIMIT_S / 2,
              f"load {load / 1000:.0f}s + {per_q:.2f}s/question x 500 = {est:.0f}s of {LIMIT_S}s "
              "(per-question time here is wall time of this run, with this run's concurrency)")


def compare(rep: Report, a: Path, b: Path) -> None:
    ra = (a / "submission.jsonl").read_bytes()
    rb = (b / "submission.jsonl").read_bytes()
    if ra == rb:
        rep.check("C5 two runs: identical submission.jsonl", True, "byte-identical")
        return
    la = {json.loads(x)["id"]: x for x in ra.decode().splitlines()}
    lb = {json.loads(x)["id"]: x for x in rb.decode().splitlines()}
    diff = sorted(i for i in set(la) | set(lb) if la.get(i) != lb.get(i))
    rep.check("C5 two runs: identical submission.jsonl", False,
              f"{len(diff)} ids differ, e.g. {diff[:3]} (compute PA of both with --answers; "
              "bound is |dPA| <= 0.03, target 0.005)")


def pa(rep: Report, result_dir: Path, answers: Path) -> None:
    from datamate.eval.score import score_files

    r = score_files(result_dir / "submission.jsonl", answers)
    rep.info("PA", f"{r['pa']:.4f} on {answers}" if "pa" in r else str(r)[:200])


def image(rep: Report, tag: str, measure_tar: bool) -> None:
    def docker(*a: str, **kw):
        return subprocess.run(["docker", *a], capture_output=True, text=True, **kw)

    p = docker("image", "inspect", "-f", "{{.Os}}/{{.Architecture}} {{.Size}}", tag)
    if p.returncode != 0:
        rep.check("I1 image exists", False, p.stderr.strip()[:100])
        return
    platform, size = p.stdout.split()
    rep.check("I1 image platform is linux/amd64", platform == "linux/amd64", platform)
    rep.info("I1 image size (docker image inspect, not the tar)", f"{int(size) / 1e9:.1f} GB")
    missing = [f for f in REQUIRED_IMAGE_FILES
               if docker("run", "--rm", "--network", "none", "--entrypoint", "", tag,
                         "test", "-f", f).returncode != 0]
    rep.check("I2 required /code files present", not missing, ", ".join(missing))
    m = docker("run", "--rm", "--network", "none", "--entrypoint", "", tag, "sh", "-c",
               "ls -A /code/models | head -1")
    rep.check("I3 /code/models is not empty", bool(m.stdout.strip()))
    r = docker("run", "--rm", "--network", "none", "--entrypoint", "", tag, "cat", "/code/README.md")
    rep.check("I4 /code/README.md has no unfilled `TO FILL` fields",
              r.returncode == 0 and "TO FILL" not in r.stdout)
    if measure_tar:
        save = subprocess.Popen(["docker", "save", tag], stdout=subprocess.PIPE)
        total = 0
        assert save.stdout is not None
        for chunk in iter(lambda: save.stdout.read(1 << 24), b""):
            total += len(chunk)
        save.wait()
        rep.check("I5 uncompressed docker save tar <= 100 GB", save.returncode == 0 and total <= TAR_LIMIT,
                  f"{total} bytes")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--data-dir", type=Path, help="split directory with questions.jsonl")
    p.add_argument("--result-dir", type=Path)
    p.add_argument("--compare", type=Path, help="second result dir for the same input")
    p.add_argument("--answers", type=Path, help="training answers.jsonl (never test data)")
    p.add_argument("--image", help="docker image tag to inspect")
    p.add_argument("--measure-tar", action="store_true", help="measure `docker save` size (slow)")
    args = p.parse_args(argv)
    if not args.result_dir and not args.image:
        p.error("give --result-dir and --data-dir, and/or --image")
    if args.result_dir and not args.data_dir:
        p.error("--result-dir needs --data-dir")
    rep = Report()
    if args.result_dir:
        check_result(rep, args.data_dir, args.result_dir)
        if args.compare:
            compare(rep, args.result_dir, args.compare)
        if args.answers:
            pa(rep, args.result_dir, args.answers)
    if args.image:
        image(rep, args.image, args.measure_tar)
    print("RESULT: " + ("all checks passed" if not rep.failed else f"{rep.failed} check(s) FAILED"))
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
