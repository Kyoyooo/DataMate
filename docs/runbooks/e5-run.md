# Runbook — E5 host smoke, rehearsal and determinism runs (M4-10, M4-16, L-17)

E5 = a host with 2 × RTX 5090 (or other sm_120 GPUs), driver R570+, Docker with NVIDIA Container Toolkit. Use the **exact** organizer command (DG §10); only the paths change.

## 0. Host check
```bash
docker --version; nvidia-smi --query-gpu=index,name,driver_version --format=csv
docker run --rm --gpus all --entrypoint "" vllm/vllm-openai:v0.10.1.1 python3 -c '
import torch, vllm
print("torch", torch.__version__, "cuda", torch.version.cuda, "| vllm", vllm.__version__)
for i in range(torch.cuda.device_count()):
    print(i, torch.cuda.get_device_name(i), torch.cuda.get_device_capability(i))
print("p2p 0->1:", torch.cuda.can_device_access_peer(0, 1))'
```
Expect compute capability `(12, 0)`. Record the output.

## 1. Smoke (10 questions)
Make a 10-question split without answers: copy a training split's folder structure with the first 10 lines of `questions.jsonl` (the tool `tools/record_model_calls.py` shows how the subset is built; any training subset is fine). Then:
```bash
docker run --rm --gpus '"device=0,1"' --network none --shm-size=16g --entrypoint bash \
  -v /path/to/smoke_split:/data:ro -v /path/to/out_smoke:/result \
  zaic2026_datamate_<team>:final /code/predict.sh
tools/precheck.sh --data-dir /path/to/smoke_split --result-dir /path/to/out_smoke
```
Pass = exit 0, `precheck` all PASS, `out_smoke/logs/replica-0.log` and `replica-1.log` show the servers started with `--host 127.0.0.1`, no network error in any log (loopback serving under `--network none`, SPEC V10).

If the servers do not start: read `replica-<i>.log`; the SPEC §3 fallback (in-process engines) is **not implemented**; report to the lead.

## 2. Rehearsal (full training split, G6)
```bash
docker run --rm --gpus '"device=0,1"' --network none --shm-size=16g --entrypoint bash \
  -v /path/to/train:/data:ro -v /path/to/out_train1:/result \
  zaic2026_datamate_<team>:final /code/predict.sh
tools/precheck.sh --data-dir /path/to/train --result-dir /path/to/out_train1 --answers /path/to/train/answers.jsonl
```
Pass = finishes within the budget (`run.json` `timings.total_ms`; precheck C4 projects ≤ 50 % of 6 h), exit 0, every id written. Record PA, per-type PA (`python -m datamate.eval.score --pred … --answers …`), `run.json` and the environment block.

## 3. Determinism (G7): second run on the same input
Repeat §2 into `out_train2` with the same command, then
```bash
tools/precheck.sh --data-dir /path/to/train --result-dir /path/to/out_train1 --compare /path/to/out_train2 --answers /path/to/train/answers.jsonl
```
Target: identical `submission.jsonl`; accepted: |ΔPA| ≤ 0.005 (organizer bound 0.03). If they differ, list the changed ids from the C5 line, compute PA for both, and report to the lead (see the determinism investigation in the bake-off notebook).

## 4. Fault checks (optional, M4-11)
- `docker stop -t 30 <container>` during a run: the SIGTERM path must leave a complete `submission.jsonl` (unwritten ids `abstain` with `E_GLOBAL_STOP`).
- Kill one replica process inside the container (`docker exec <c> pkill -f 'port 8100'`): `run.json` events show `died` and one restart; the run still finishes.
