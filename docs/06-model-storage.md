# 6. Model storage and sync

## Bottom line

Keep model weights out of the serving deployment. A catalog of pinned Hugging Face revisions syncs to the `models` user volume on each Spark. Serving pods mount it read-only with `hostPath`. The sync never deletes.

## Layout

```text
/var/mnt/models/
  hub/models--<org>--<name>/snapshots/<revision>/   Hugging Face cache layout
  catalog-status.json                                per-model state: ready | downloading | error
```

Every catalog entry pins a commit SHA, so deployments mount a fixed path.

## Manifests

[`manifests/k8s/model-sync/`](../manifests/k8s/model-sync/):

- `catalog.yaml` - list of `{repo, revision, notes}`.
- `daemonset.yaml` - one downloader per Spark (`node.kubernetes.io/instance-type: dgx-spark`).
- `sync.py` - stdlib-only supervisor. It starts a fresh downloader child per cycle, so native allocations are freed between cycles.
- `test_sync.py` - offline unit tests.

## Memory lessons

- The first version held hundreds of MB of RSS between syncs on a node where every GB counts. The child-process design fixed it.
- `HF_HUB_DISABLE_XET=1`, `HF_HUB_ENABLE_HF_TRANSFER=0`, one worker: slower, but bounded memory.
- `huggingface_hub`'s plain HTTP path refused a single 53.7 GB file (a 50 GB per-file cap). Check the largest file, not only total model size, before you add a model.

## Gate serving on the catalog

Each LWS has an init container that waits until its model is `ready` in `catalog-status.json`:

```sh
until grep -A3 "\"repo\": \"$CATALOG_REPO\"" /models/catalog-status.json 2>/dev/null \
  | grep -q "\"state\": \"ready\""; do sleep 60; done
```

This stops a half-downloaded model from crash-looping both ranks.

## Caches worth persisting

A `hostPath` cache directory per node (for example `/var/lib/spark-llm-cache`) holds:

- vLLM compile cache, Triton cache, TileLang cache
- NVIDIA JIT `ComputeCache` (`/root/.nv/ComputeCache`)
- torch extension builds
- processed-weight snapshots (one recipe writes about 48 GB per node on first boot)

Persisting these cut cold start by minutes. See the stale-lock gotcha in [troubleshooting](11-troubleshooting.md#boot-hangs-at-kernel-build).
