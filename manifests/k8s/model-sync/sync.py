"""Download catalog entries without retaining downloader memory between cycles."""
import json
import os
import signal
import subprocess
import sys
import time
import traceback

CATALOG = os.environ.get("MODEL_CATALOG_PATH", "/etc/models/catalog.yaml")
STATUS = os.path.join(os.environ["HF_HOME"], "catalog-status.json")
INTERVAL = int(os.environ.get("SYNC_INTERVAL_SECONDS", "21600"))
RETRY_INTERVAL = 300


def sync_once():
    # Import download libraries only in the short-lived child, never the supervisor.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_ENABLE_HF_TRANSFER", "0")
    import resource
    import yaml
    from huggingface_hub import constants, snapshot_download

    # huggingface_hub refuses plain-HTTP downloads over 50 GB unless hf_transfer/xet
    # is used. The Hub serves them fine (checked: 200 on a full GET of a 53.7 GB file),
    # and we stay on single-stream HTTP to bound memory, so lift the client-side cap.
    constants.MAX_HTTP_DOWNLOAD_SIZE = 1 << 42
    workers = int(os.environ.get("MODEL_DOWNLOAD_WORKERS", "1"))
    if workers < 1:
        raise ValueError("MODEL_DOWNLOAD_WORKERS must be positive")
    print(f"download settings: workers={workers} "
          f"xet_disabled={constants.HF_HUB_DISABLE_XET} "
          f"hf_transfer={constants.HF_HUB_ENABLE_HF_TRANSFER}", flush=True)
    with open(CATALOG) as f:
        entries = yaml.safe_load(f)["models"]
    status = {"node": os.environ.get("NODE_NAME"), "started": time.time(), "models": []}
    ok = True
    for entry in entries:
        repo, rev = entry["repo"], entry["revision"]
        record = {"repo": repo, "revision": rev}
        try:
            print(f"sync {repo}@{rev}", flush=True)
            record["path"] = snapshot_download(repo, revision=rev, max_workers=workers)
            record["state"] = "ready"
            print(f"ready {repo} -> {record['path']}", flush=True)
        except Exception as exc:  # Keep going; retry sooner after a failure.
            ok = False
            record["state"], record["error"] = "error", repr(exc)[:500]
            traceback.print_exc()
        status["models"].append(record)
    status["finished"] = time.time()
    tmp = STATUS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(status, f, indent=2)
    os.replace(tmp, STATUS)
    # Linux ru_maxrss is KiB. This measures process RSS, not filesystem cache.
    print(f"cycle finished: ok={ok} peak_rss_kib="
          f"{resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}", flush=True)
    return ok


def supervise():
    stopping = False
    child = None

    def terminate(signum, frame):
        # Python handlers can interrupt code holding a non-reentrant lock.
        # Only set a flag here; never call Event.set(), poll(), or terminate().
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        while not stopping:
            child = subprocess.Popen([sys.executable, "-u", os.path.abspath(__file__), "--once"])
            result = None
            while not stopping:
                try:
                    result = child.wait(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if stopping:
                break  # The finally block terminates, escalates, and reaps.
            child = None
            delay = INTERVAL if result == 0 else RETRY_INTERVAL
            print(f"downloader exited: code={result}; next sync in {delay}s", flush=True)
            deadline = time.monotonic() + delay
            while not stopping:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(1, remaining))
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    if sys.argv[1:] == ["--once"]:
        sys.exit(0 if sync_once() else 1)
    elif sys.argv[1:]:
        sys.exit("usage: sync.py [--once]")
    else:
        supervise()
