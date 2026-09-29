# Spark model catalog sync

`catalog.yaml` pins models independently of serving deployments. `model-sync` runs
on each Spark and writes `/var/mnt/models/catalog-status.json`. It never deletes
model files. Catalog or script edits change the ConfigMap name and roll the
DaemonSet. Serving workloads do not need a restart.

## Memory policy

The PID 1 supervisor uses only the Python standard library. Each cycle starts a
new downloader process and waits for it to exit. Successful cycles wait six hours;
failed cycles retry after five minutes. SIGTERM stops the child or idle wait.
Download libraries are imported only by the child. Process exit releases native
allocations rather than retaining them through the six-hour idle interval.

Defaults:

- `HF_HUB_DISABLE_XET=1`, `HF_HUB_ENABLE_HF_TRANSFER=0`: use ordinary streaming HTTP.
- `MODEL_DOWNLOAD_WORKERS=1`: download one file at a time.
- Memory request: 128 MiB. Container memory limit: 512 MiB, including file cache.
- `SYNC_INTERVAL_SECONDS=21600`: normal interval; retry interval remains 300 seconds.

Hugging Face Hub 0.36.0 streams HTTP data in bounded chunks. This trades parallel
transfer throughput for predictable memory, without changing pinned revisions,
cache layout, resumable HTTP downloads, or atomic status publication. Increasing
workers or re-enabling native acceleration needs a fresh cold-download memory test
and potentially a higher limit. The Hub's regular HTTP implementation refuses
individual files above 50 GB; the current catalog's largest file is about 4.12 GB.
Model *total* size is not this limit. Future models with larger individual files
need a separately tested download configuration.

The operating system may retain downloaded data as reclaimable file cache. Do not
confuse this with anonymous downloader memory. Inspect `memory.stat` and process
RSS, not only container memory totals. Lowering a request alone does not release
resident memory.

## Verification

Run offline lifecycle and status tests:

```
python3 -m unittest discover -s k8s/models -p 'test_*.py' -v
kubectl kustomize k8s/models
```

For download acceptance, use an isolated disk-backed emptyDir and the exact source,
Python image, library version, environment, and memory limit. Run a pinned model
from an empty cache, check file sizes and weight hashes against Hub metadata, then
run a second cycle to check cached reuse. Measure downloader peak RSS, cgroup
anonymous/file memory separately, OOM events, and supervisor-only idle memory.
Never delete production weights to manufacture a cold cache.

`python sync.py --once` runs one cycle and returns success/failure. For isolated
tests, `MODEL_CATALOG_PATH` can select a test catalog; `HF_HOME` must point at the
test cache, not the live model directory. These overrides do not change production
defaults.
