#!/bin/bash
# Qwen3.8-Flash-Next entrypoint for spark-llm-qwen. $1 = leader | worker.
set -euo pipefail
ROLE="$1"
say() { echo "[qwen38-$ROLE] $*"; }
R=/recipe/r
[ -f "${MODEL_DIR}/config.json" ] || { say "FATAL: ${MODEL_DIR}/config.json missing"; exit 1; }
VLLM_PKG=$(python3 -c "import importlib.util,os;print(os.path.dirname(importlib.util.find_spec('vllm').origin))")

# Reduced-vocabulary MTP drafting (recipe step 4e, v0.30 variant).
if [ -n "${MTP_DRAFT_VOCAB:-}" ] && [ "${MTP_TOKENS:-0}" != "0" ]; then
    MTP_PY="$VLLM_PKG/models/qwen4_exp/nvidia/mtp.py"
    cp "$MTP_PY" "$R/files/mtp_v030_patched.py.orig"
    python3 "$R/files/patch_mtp_draft_vocab_v030.py"
    cp "$R/files/mtp_v030_patched.py" "$MTP_PY"
    export VLLM_MTP_DRAFT_VOCAB="$R/${MTP_DRAFT_VOCAB}"
    say "draft vocab: $(wc -l < "$VLLM_MTP_DRAFT_VOCAB") ids"
fi

# Vendored myllmbox patches (see mbx/README.md). MBX_PATCHES="03 11 18" etc; empty = stock vLLM.
if [ -n "${MBX_PATCHES:-}" ]; then
    mkdir -p /tmp/mbx/patches /tmp/mbx/overlays-v030
    cp /scripts/qsa_cache.py /tmp/mbx/overlays-v030/qsa_cache.py
    for n in ${MBX_PATCHES}; do
        f=$(ls /scripts/${n}-*.py); cp "$f" /tmp/mbx/patches/
        python3 "/tmp/mbx/patches/$(basename "$f")" || { say "FATAL: patch $n failed"; exit 1; }
    done
fi

# GB10 unified memory: drop this checkpoint's clean page-cache pages before load.
if [ "${EVICT_PAGE_CACHE:-true}" = "true" ]; then
    python3 "$R/files/evict_page_cache.py" "${MODEL_DIR}" || true
fi

DEFAULT_CC='{"mode":0,"cudagraph_mode":"FULL_DECODE_ONLY"}'
COMPILATION_CONFIG="${COMPILATION_CONFIG:-$DEFAULT_CC}"
ARGS=(
    --enable-prompt-tokens-details
    --served-model-name "${SERVED_MODEL_NAME}"
    --tensor-parallel-size "${TP}"
    --gpu-memory-utilization "${GPU_MEM_UTIL}"
    --max-num-seqs "${MAX_NUM_SEQS}"
    --max-num-batched-tokens "${MAX_NUM_BATCHED_TOKENS}"
    --max-model-len "${MAX_MODEL_LEN}"
    --kv-cache-dtype "${KV_CACHE_DTYPE}"
    --load-format safetensors
    --safetensors-load-strategy lazy
    --enable-chunked-prefill
    --reasoning-parser qwen3
    --enable-auto-tool-choice
    --tool-call-parser qwen3_coder
    --distributed-executor-backend mp
    --mm-encoder-tp-mode "${MM_ENCODER_TP_MODE}"
    --nnodes 2
    --master-addr "${HEAD_IP}"
    --master-port "${MASTER_PORT}"
    --compilation-config "${COMPILATION_CONFIG}"
)
[ -n "${MAMBA_SSM_CACHE_DTYPE:-}" ] && ARGS+=(--mamba-ssm-cache-dtype "${MAMBA_SSM_CACHE_DTYPE}")
[ -n "${MOE_BACKEND:-}" ] && ARGS+=(--moe-backend "${MOE_BACKEND}")
[ -n "${BLOCK_SIZE:-}" ] && ARGS+=(--block-size "${BLOCK_SIZE}")
[ -n "${ENGRAM_CONFIG:-}" ] && ARGS+=(--engram-config "${ENGRAM_CONFIG}")
[ -n "${KV_CACHE_MEMORY:-}" ] && ARGS+=(--kv-cache-memory "${KV_CACHE_MEMORY}")
[ -n "${GDN_PREFILL_BACKEND:-}" ] && ARGS+=(--gdn-prefill-backend "${GDN_PREFILL_BACKEND}")
[ "${ASYNC_SCHEDULING:-}" = "true" ] && ARGS+=(--async-scheduling)
if [ "${ENABLE_EXPERT_PARALLEL:-true}" = "true" ]; then
    ARGS+=(--enable-expert-parallel --all2all-backend allgather_reducescatter)
fi
if [ "${MTP_TOKENS:-0}" != "0" ]; then
    ARGS+=(--speculative-config "$(python3 -S -c 'import json,os
s={"method":"mtp","num_speculative_tokens":int(os.environ["MTP_TOKENS"])}
if os.environ.get("MTP_DRAFT_VOCAB"): s["use_local_argmax_reduction"]=True
if os.environ.get("MTP_DRAFT_SAMPLE"): s["draft_sample_method"]=os.environ["MTP_DRAFT_SAMPLE"]
if os.environ.get("MTP_REJECTION"): s["rejection_sample_method"]=os.environ["MTP_REJECTION"]
if os.environ.get("MTP_DISABLE_BLOCK_DROP")=="1": s["disable_eagle_block_drop"]=True
if os.environ.get("MTP_INDEX_SHARE")=="true": s["index_share_for_mtp_iteration"]=True
print(json.dumps(s,separators=(",",":")))')")
fi
if [ -n "${EXTRA_ARGS:-}" ]; then
    EXTRA=(${EXTRA_ARGS})
    ARGS+=("${EXTRA[@]}")
fi

case "$ROLE" in
  leader) ARGS+=(--node-rank 0 --host 0.0.0.0 --port "${PORT}") ;;
  worker) ARGS+=(--node-rank 1 --headless) ;;
  *) say "unknown role"; exit 1 ;;
esac
say "vllm serve ${MODEL_DIR} ${ARGS[*]}"
exec vllm serve "${MODEL_DIR}" "${ARGS[@]}"
