# 11. Troubleshooting

## Node hangs at boot after NVIDIA module load

Open driver on GB10. Boot the nonfree ISO, set the nonfree installer, reinstall.

## No `nvidia.com/gpu` on the node

```bash
talosctl -n <IP> get extensions
talosctl -n <IP> dmesg | grep -Ei 'nvidia|NVRM'
kubectl -n gpu-operator get pods -o wide
```

Check the host driver first. Then check that the Operator has `driver.enabled: false`.

## No `rdma/spark_roce`

- `talosctl -n <IP> ls /dev/infiniband` - missing `rdma_cm` means `rdma_ucm` is not loaded.
- Plugin logs: `kubectl -n kube-system logs ds/rdma-shared-device-plugin`.
- Select by vendor `15b3` and driver `mlx5_core`, not interface names.

## RoCE works on one subnet, fails on the other

ARP. Set `arp_ignore=1`, `arp_announce=2`. See [gotchas](10-talos-gotchas.md#two-nics-one-link-arp).

## `ib_write_bw` is fine, NCCL is slow

Read `NCCL_DEBUG=INFO`. Confirm `NET/IB` and the right HCA. If you see `NET/Socket`, NCCL fell back to TCP; check `NCCL_SOCKET_IFNAME`, `NCCL_IB_HCA`, `rdma/spark_roce` and `hostNetwork`.

## Worker pod stays Pending

- Is the node cordoned by an upgrade job?
- Are the tolerations there?
- Is a time-slicing ticket free? With 4 tickets and other GPU pods, it can be full.

## Model load OOM-kills both ranks

- Use lazy / mmap safetensors loading.
- Drop the page cache of other models before load, or evict it with the recipe's helper.
- Reduce CUDA graph capture sizes; each size costs GPU (host) memory.
- Check what else runs on the node. Unified memory means other pods count.

## A debug exec kills the server

Do not start Python or other large tools inside a serving pod when `MemAvailable` is low. Read `/proc/meminfo` with `grep` instead.

## Boot hangs at kernel build

A pod killed during a torch extension JIT build leaves lock files in the persisted cache. The next boot waits on them forever. Delete stale `lock` files in the torch extensions cache directory, then restart.

## Startup probe kills a slow first boot

First boots compile kernels and write weight snapshots. Give the startup probe 60-90 minutes on a new recipe. Tighten it after the caches are warm.

## TTFT is much worse through the ingress

nginx buffering. See [serving](07-lws-serving.md#streaming-through-an-ingress).

## Benchmark numbers look too good

Prefix cache. Use a unique seed per benchmark cell.

## Client silently uses another model

Some clients fall back to a default provider on HTTP errors. Example: a model that rejects `reasoning_effort: high` with HTTP 400 caused one agent client to fall back to its default cloud provider without an error. Check the server logs, not only the client's output.
