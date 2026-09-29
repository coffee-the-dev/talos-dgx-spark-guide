# 5. ConnectX-7, RoCE and the RDMA device plugin

## Bottom line

Talos's inbox `mlx5` driver is enough. You do not need the NVIDIA Network Operator. Load the right modules, fix ARP, expose `/dev/infiniband` with the RDMA shared device plugin, then validate in layers.

## Kernel modules

`ib_core ib_uverbs rdma_cm rdma_ucm ib_umad mlx5_core mlx5_ib`. The first attempt omitted `rdma_ucm` and `ib_umad`. Without `rdma_ucm` there is no `/dev/infiniband/rdma_cm`, and both the device plugin and NCCL's RoCE path fail.

## RDMA shared device plugin

[`manifests/k8s/rdma-shared-device-plugin/`](../manifests/k8s/rdma-shared-device-plugin/) exposes `rdma/spark_roce` (1000 per node):

```json
{
  "resourceName": "spark_roce",
  "rdmaHcaMax": 1000,
  "selectors": {"vendors": ["15b3"], "drivers": ["mlx5_core"], "linkTypes": ["ether"]}
}
```

Select by vendor and driver, not `ifNames`. The DaemonSet needs the `nvidia.com/gpu` toleration and a pinned multi-arch image digest.

Pods that use RDMA request `rdma/spark_roce: 1`, add `IPC_LOCK`, and (for NCCL between nodes) use `hostNetwork: true`.

## Validation layers

Each layer isolates a different fault.

### Layer 1 - link

```bash
talosctl -n <NODE_IP> get links enp1s0f0np0 -o yaml   # operationalState up, mtu 9000
```

Map RDMA devices to interfaces from any pod with `/sys`:

```text
mlx5_0  enp1s0f0np0    ACTIVE
mlx5_1  enp1s0f1np1    DOWN
mlx5_2  enP2p1s0f0np0  ACTIVE
mlx5_3  enP2p1s0f1np1  DOWN
```

### Layer 2 - jumbo ping

From a hostNetwork debug pod on spark-0:

```bash
ping -M do -s 8972 10.100.0.11
ping -M do -s 8972 10.101.0.11
```

### Layer 3 - host-memory RoCE

Two hostNetwork pods with `mellanox/cuda-perftest`, one per Spark, `rdma/spark_roce: 1`, `IPC_LOCK`.

```bash
# server (spark-0)
ib_write_bw -d mlx5_0 -a -F --report_gbits -q 1
# client (spark-1)
ib_write_bw -d mlx5_0 -a -F --report_gbits -q 1 10.100.0.10
```

Measured:

- 97.5 Gb/s per ConnectX function
- about 182 Gb/s with both functions in parallel
- 1.5 us latency

Do not add `--use_cuda --use_cuda_dmabuf`. It is unsupported on GB10.

### Layer 4 - NCCL

We did not keep a standalone `nccl-tests` result. The live TP=2 model proves the path: the RDMA counters on `mlx5_0` showed about 355 MB moved during one 149-token request. The GLM NVFP4 recipe's built-in fabric check reports all-reduce bus bandwidth (see below).

## NCCL settings that matter

From the working serving configs:

```bash
NCCL_IB_DISABLE=0
NCCL_IB_HCA=mlx5_0            # or leave unset and let the recipe map both roots
NCCL_IB_GID_INDEX=3           # RoCE v2, IPv4
NCCL_SOCKET_IFNAME=enp1s0f0np0
GLOO_SOCKET_IFNAME=enp1s0f0np0
NCCL_MAX_NCHANNELS=4          # measured best, see below
NCCL_NVLS_ENABLE=0
NCCL_CUMEM_ENABLE=0
```

Never point `NCCL_SOCKET_IFNAME` at the management NIC. NCCL will fall back to TCP over 10 GbE and everything still "works", only much slower. Always confirm the transport in the log.

Channel count, all-reduce bus bandwidth from the recipe fabric check:

- 4 channels: 162 Gb/s (best)
- 8 channels: 151 Gb/s
- 16 channels: 126 Gb/s

About 190 Gb/s is the expected figure for this link. A reseat of the DAC did not change our number. A full power drain (unplugged) is the remaining untested fix.

## The ARP trap

See [gotchas](10-talos-gotchas.md#two-nics-one-link-arp). Short form: both ConnectX functions share one L2 link, so set `arp_ignore=1` and `arp_announce=2`, or RoCE on the second subnet fails with `IBV_WC_RETRY_EXC_ERR`.
