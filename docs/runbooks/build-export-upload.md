# Runbook — build, export, checksum, upload (M4-12; IMPLEMENTATION_PLAN §8.1, DG §9, §11)

Run on the **build host** (Docker 24+ with BuildKit, network for the base image pull, ≥ 150 GB free: the DG sample needed ~57 GB for the image plus ~50 GB temporarily during export). Replace `<team>` with the lowercase team identifier.

## 0. Preconditions (stop if any is false)
- DEC-3 is decided and recorded: model name, revision, base image. The lead has set `config/run_config.json` (`model.path` = `/code/models/<dir>`, `model.revision`, serving values) **in a merged PR**, and filled every `TO FILL` in `docs/SUBMISSION_README.md`.
- You are on the tagged commit that will be frozen: `git status` clean, `git rev-parse HEAD` noted.

## 1. Lock (once per base image)
```bash
tools/gen_requirements_lock.sh vllm/vllm-openai:v0.10.1.1
```
Commit `requirements.lock`, `requirements.lock.base`, `requirements.lock.meta.json`.

## 2. Build
```bash
tools/build_image.sh <team> /path/to/<model_dir>
```
The script counts parameters (must print `OK`; the total over **all** shipped models must be ≤ 15 B), stages the model under `models/`, stages `train/` into `training_code/data/train/`, regenerates `training_code/data_manifest.json`, builds `zaic2026_datamate_<team>:final` for `linux/amd64`, prints platform and size, and lists `/code`. Do not change anything after this point without rebuilding.

## 3. Checks
```bash
tools/precheck.sh --image zaic2026_datamate_<team>:final --measure-tar
```
Expect `PASS` for I1–I5 (platform, required files, non-empty models, README without `TO FILL`, uncompressed tar ≤ 100 GB). Then run `docs/runbooks/e5-run.md` (smoke, rehearsal, two runs) before exporting.

## 4. Export and checksum (DG §11)
```bash
set -o pipefail
docker save zaic2026_datamate_<team>:final | pigz -p 8 > zaic2026_datamate_<team>.tar.gz   # or: | gzip >
pigz -dc zaic2026_datamate_<team>.tar.gz | wc -c        # uncompressed bytes; must be <= 100000000000
md5sum zaic2026_datamate_<team>.tar.gz > zaic2026_datamate_<team>.tar.gz.md5
```
Never rename the archive after creating the `.md5`.

## 5. Upload and verify on a second machine
Upload the `.tar.gz` to a public Google Drive link. On another machine: download from that link, then
```bash
md5sum -c zaic2026_datamate_<team>.tar.gz.md5     # must print OK
```
Optionally `docker load` it and re-run the E5 smoke command.

## 6. Record and submit
Record link, md5 line, uncompressed size in bytes, git commit, image id in `docs/M3_M4_PROGRESS.md`; the lead submits through the official Solution Submission form (safety submission by 2026-11-14, final before 2026-11-16 23:59 GMT+7; at most 2 submissions, only the last is evaluated).
