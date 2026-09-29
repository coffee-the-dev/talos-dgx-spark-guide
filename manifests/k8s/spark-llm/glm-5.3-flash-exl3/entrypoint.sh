#!/bin/bash
# Model entrypoint for spark-llm. $1 = leader | worker.
# Overlay the recipe's pinned runtime patches, then run the rank script.
set -euo pipefail
cp -a /recipe/opt/glm53/. /opt/glm53/

# Cooperative MoE (recipe docs/cooperative-moe-quickstart.md steps 4-5).
# .so = Mia's release asset cooperative-moe-geo1 (digest pinned below and in
# prepare_profile.py). prepare_profile.py refuses any .so / runtime.py /
# stock exl3.py drift. head.sh/worker.sh install /opt/glm53/exl3.py into
# site-packages via patch_dense_fp8.py. Fail closed on any check or GPU gate.
if [ "${GLM53_COOPERATIVE_MOE:-0}" = "1" ]; then
  SO_SHA=aa3fe5e9387c7e0d42d685fb2ca8a5fb959ad956600236baac078a9076c17a1c
  SO_URL=https://github.com/MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks/releases/download/cooperative-moe-geo1/cooperative_moe.so
  CACHE=/root/.cache/vllm/cooperative_moe
  D=/opt/glm53-coop
  SRC=/recipe/coop
  mkdir -p "$CACHE" "$D"
  if ! echo "$SO_SHA  $CACHE/cooperative_moe.so" | sha256sum -c --quiet - 2>/dev/null; then
    python3 -c "import sys,urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" \
      "$SO_URL" "$CACHE/cooperative_moe.so.tmp"
    echo "$SO_SHA  $CACHE/cooperative_moe.so.tmp" | sha256sum -c -
    mv "$CACHE/cooperative_moe.so.tmp" "$CACHE/cooperative_moe.so"
  fi
  install -m 644 "$CACHE/cooperative_moe.so" "$SRC/src/runtime.py" "$D/"
  python3 "$SRC/src/prepare_profile.py" --stock /opt/glm53/exl3.py \
    --artifacts "$D" --runtime-directory "$D" --output "$D/exl3-cooperative.py"
  install -m 644 "$D/exl3-cooperative.py" /opt/glm53/exl3.py
  install -m 644 "$D/exl3-cooperative.py" \
    /usr/local/lib/python3.12/dist-packages/vllm/model_executor/layers/quantization/exl3.py
  install -m 644 "$SRC/src/test_cuda_integration.py" "$SRC/test_exl3_overlay.py" /opt/glm53/
  echo "[coop] overlay selected: $(sha256sum /opt/glm53/exl3.py | cut -c1-16) geometry=${GLM53_COOP_GEOMETRY:-default}"
  if [ "${GLM53_COOP_GATE:-1}" = "1" ]; then
    echo "[coop] running GPU gate (no checkpoint load)"
    set +e
    env GLM53_COOP_MAINTENANCE_TEST=1 MAX_JOBS=2 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
      python3 /opt/glm53/test_cuda_integration.py > /tmp/coop-gate.log 2>&1
    rc=$?
    set -e
    tail -n 40 /tmp/coop-gate.log
    [ "$rc" = "0" ] || { echo "[coop] GPU gate FAILED rc=$rc"; exit 1; }
    echo "[coop] GPU gate passed"
  fi
fi

case "$1" in
  leader) exec bash /scripts/head.sh ;;
  worker) exec bash /scripts/worker.sh ;;
  *) echo "unknown role: $1" >&2; exit 1 ;;
esac
