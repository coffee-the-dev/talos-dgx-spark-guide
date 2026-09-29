#!/usr/bin/env bash
# Switch the model served on the two DGX Sparks. No git push needed:
# LWS replicas are ignored by ArgoCD (app.yaml ignoreDifferences).
#   ./switch-model.sh            show what is running
#   ./switch-model.sh glm|qwen|mm   stop the other set, wait, start this one
# Works with macOS bash 3.2 (no associative arrays).
set -euo pipefail
NS=spark-llm
lws_for() {
  case "$1" in
    glm) echo spark-llm ;;
    qwen) echo spark-llm-qwen ;;
    mm) echo spark-llm-mm ;;
    *) return 1 ;;
  esac
}
status() {
  for m in glm qwen mm; do
    l=$(lws_for "$m")
    printf '%-5s %-15s replicas=%s\n' "$m" "$l" \
      "$(kubectl -n "$NS" get lws "$l" -o jsonpath='{.spec.replicas}')"
  done
  kubectl -n "$NS" get pods -l app=spark-llm -o wide
}
[ $# -eq 0 ] && { status; exit 0; }
want="$1"
lws_for "$want" >/dev/null || { echo "usage: $0 [glm|qwen|mm]" >&2; exit 2; }
for m in glm qwen mm; do
  [ "$m" = "$want" ] && continue
  kubectl -n "$NS" scale lws "$(lws_for "$m")" --replicas=0
done
echo "waiting for the other model's pods to exit (frees GPU memory and port 8888)..."
for m in glm qwen mm; do
  [ "$m" = "$want" ] && continue
  l=$(lws_for "$m")
  while kubectl -n "$NS" get pods -l "leaderworkerset.sigs.k8s.io/name=$l" -o name | grep -q .; do sleep 5; done
done
kubectl -n "$NS" scale lws "$(lws_for "$want")" --replicas=1
echo "started $want; first load takes ~6-12 min. Follow with:"
echo "  kubectl -n $NS logs -f $(lws_for "$want")-0 -c server"
echo "  curl -s https://llm.example.com/v1/models"
