#!/usr/bin/env python3
"""Bake-off report, run on your own computer (no GPU).

  python tools/bakeoff_report.py --runs <bakeoff folder from Drive> [--verify] [--models-dir <dir with the model folders>]

Reads what BAKEOFF_G4.ipynb saved: per candidate PA, determinism between the two identical runs and throughput, and
the table of determinism experiments. ``--verify`` also checks each candidate's licence, release date (needs network and
``huggingface_hub``) and, with ``--models-dir``, the parameter count. Anything it cannot verify is printed as UNVERIFIED.
Nothing here chooses a model.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _hub_info(repo: str) -> dict | None:
    try:
        from huggingface_hub import HfApi

        api = HfApi()
        info = api.model_info(repo)
        first = min(c.created_at for c in api.list_repo_commits(repo)).date().isoformat()
        return {"license": info.card_data.license if info.card_data else None, "sha": info.sha,
                "first_commit_date": first}
    except Exception:  # offline, missing library, private repo
        return None


def report(runs: Path, verify: bool, models_dir: Path | None) -> dict:
    bake = _load("bakeoff")
    meta = json.loads((runs / "meta.json").read_text(encoding="utf-8"))
    answers = runs / "answers.jsonl"
    out: dict = {"commit": meta["commit"], "gpu": meta["gpu"], "compute_capability": meta["compute_capability"],
                 "target_hardware": meta["compute_capability"] == "12.0", "candidates": {}, "experiments": []}
    for name in meta["models"]:
        a, b = runs / "runs" / f"{name}-A1", runs / "runs" / f"{name}-A2"
        if not (a / "submission.jsonl").is_file() or not (b / "submission.jsonl").is_file():
            out["candidates"][name] = {"error": f"runs missing or failed (exit codes {meta['exit_codes'].get(name + '-A1')}, "
                                                f"{meta['exit_codes'].get(name + '-A2')})"}
            continue
        rec = {"run": bake.run_summary(a, answers), "determinism": bake.compare_determinism(a, b, answers)}
        if verify:
            repo = next((c for c in meta["candidates"] if c.split("/")[-1] == name), name)
            params = None
            if models_dir and (models_dir / name).is_dir():
                params = _load("count_params").count_dir(models_dir / name)["parameters"]
            rec["verification"] = bake.verify_candidate(
                {"name": name, "repo": repo, "revision": (_hub_info(repo) or {}).get("sha")}, _hub_info(repo), params)
        out["candidates"][name] = rec
    first = next(iter(meta["models"]), None)
    for v in meta["variants"]:
        a, b = (runs / "runs" / f"{first}-D-{v}-{i}" for i in (1, 2))
        if not (a / "submission.jsonl").is_file() or not (b / "submission.jsonl").is_file():
            out["experiments"].append({"variant": v, "error": "runs missing or failed"})
            continue
        d = bake.compare_determinism(a, b)
        out["experiments"].append({"variant": v, "identical_output_rate": d["identical_output_rate"],
                                   "answers_changed": d["answers_changed"],
                                   "submissions_identical": d["submissions_byte_identical"],
                                   "wall_s": bake.throughput(a)["wall_s"]})
    return out


def show(r: dict) -> None:
    print(f"commit {r['commit'][:10]} | GPU {r['gpu']} (cc {r['compute_capability']})"
          + ("" if r["target_hardware"] else " | NOT the competition GPU type: indicative only"))
    for name, c in r["candidates"].items():
        print(f"\n== {name}")
        if "error" in c:
            print("  ", c["error"])
            continue
        pa, t, d = c["run"].get("pa", {}), c["run"]["throughput"], c["determinism"]
        print(f"  PA {pa.get('pa', float('nan')):.4f} (n={pa.get('n')}, correct={pa.get('correct')}, wrong={pa.get('wrong')}, abstain={pa.get('abstain')})")
        print(f"  determinism: {d['answers_changed']} answers changed between the two runs, identical raw output rate "
              f"{d['identical_output_rate']}, dPA {d.get('delta_pa')}")
        print(f"  speed: {t['questions_per_min']:.1f} questions/min, p50 {t['elapsed_ms_p50']} ms, p95 {t['elapsed_ms_p95']} ms, "
              f"projected 500 questions on this GPU: {t['projected_500_questions_s']:.0f} s")
        if "verification" in c:
            v = c["verification"]
            print(f"  checks: revision {v['revision_fixed']}, license {v['license']} ({v.get('license_text')}), "
                  f"release date {v['release_date']} (first commit {v.get('first_commit_date')}), "
                  f"parameters {v.get('parameters')} -> {v['param_limit']}")
    print("\n== determinism experiments (first candidate, two runs each)")
    for e in r["experiments"]:
        print("  ", e["variant"], e.get("error") or
              f"identical output rate {e['identical_output_rate']}, answers changed {e['answers_changed']}, "
              f"same submission {e['submissions_identical']}, {e['wall_s']:.0f} s")
    print("\nNothing here chooses a model: the team lead decides. UNVERIFIED / FAIL items must be checked on the model card.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--runs", type=Path, required=True)
    p.add_argument("--verify", action="store_true")
    p.add_argument("--models-dir", type=Path)
    args = p.parse_args(argv)
    r = report(args.runs, args.verify, args.models_dir)
    (args.runs / "report.json").write_text(json.dumps(r, indent=2, default=str), encoding="utf-8")
    show(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
