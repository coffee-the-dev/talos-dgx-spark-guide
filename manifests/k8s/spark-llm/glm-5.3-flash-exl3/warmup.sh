#!/bin/bash
# Post-ready shape warmup + correctness canary. Runs inside the leader pod
# after /health, before the startup probe can pass. Non-zero exit only on a
# degenerate engine (canary rc 3) or a missing recipe file.
set -u
echo "[warmup] start $(date -u +%FT%TZ)"
for i in $(seq 1 180); do  # 15 min: non-instanttensor loads take ~6 min
  curl -sf http://127.0.0.1:8888/health >/dev/null && break
  sleep 5
done
curl -sf http://127.0.0.1:8888/health >/dev/null || { echo "[warmup] health never came up"; exit 1; }
[ -f /opt/glm53/boot-shape-warmup.sh ] || { echo "[warmup] script missing"; exit 1; }
rc=0
GLM53_WARMUP_MAX_CONCURRENCY="${MAX_NUM_SEQS:-8}" \
GLM53_WARMUP_DFLASH_K="${DFLASH_TOKENS:-7}" \
GLM53_WARMUP_CANARY="${GLM53_WARMUP_CANARY:-1}" \
  bash /opt/glm53/boot-shape-warmup.sh "http://127.0.0.1:${PORT:-8888}" "${SERVED_MODEL_NAME:-GLM-5.3-Flash-EXL3}" || rc=$?
echo "[warmup] boot-shape-warmup rc=$rc $(date -u +%FT%TZ)"
[ "$rc" = "3" ] && exit 3
exit 0
