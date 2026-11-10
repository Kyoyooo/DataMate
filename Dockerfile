# DataMate 2026 submission image (DG §4, §9; SPEC §4.1). Build with tools/build_image.sh.
# Base: reference image from the organizers' guide. BASE_IMAGE is overridable only for CPU
# smoke tests of this file; submissions are built from the default (docs/decisions/M4-01-base-image.md).
ARG BASE_IMAGE=vllm/vllm-openai:v0.10.1.1
FROM ${BASE_IMAGE}

# The base image's ENTRYPOINT starts the vLLM server; a plain `docker run` must start predict.sh.
ENTRYPOINT []

# Fixed environment (SPEC §2.4); predict.sh exports the same values again.
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PIP_NO_CACHE_DIR=1 NCCL_P2P_DISABLE=1 \
    PYTHONHASHSEED=0 PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
    VLLM_BATCH_INVARIANT=0 VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1 \
    PYTHONPATH=/code/src

WORKDIR /code

# 1. Dependencies: the lock was produced by `pip freeze` inside this base image (tools/gen_requirements_lock.sh).
#    It is used as constraints so project requirements cannot replace torch/vllm.
COPY requirements.lock /code/requirements.txt
COPY requirements.in /code/requirements.in
RUN pip install --no-cache-dir -c /code/requirements.txt -r /code/requirements.in

# 2. Weights first: they are large and rarely change, so this layer stays cached when code changes.
COPY models/ /code/models/

# 3. Training evidence (DG §8). Never excluded by .dockerignore.
COPY training_code/ /code/training_code/

# 4. Inference code, configuration, tools and documentation.
COPY src/ /code/src/
COPY config/run_config.json /code/config/run_config.json
COPY tools/ /code/tools/
COPY docs/runbooks/ /code/docs/runbooks/
COPY predict.sh /code/
COPY docs/SUBMISSION_README.md /code/README.md
ARG GIT_COMMIT=unknown
RUN printf '{"git_commit": "%s"}\n' "${GIT_COMMIT}" > /code/BUILD_INFO.json && chmod +x /code/predict.sh

CMD ["bash", "/code/predict.sh"]
