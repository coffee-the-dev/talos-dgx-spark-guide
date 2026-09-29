# 1. Architecture and constraints

## Bottom line

A DGX Spark is a Talos worker with a GB10 GPU, 128 GB of unified memory and a ConnectX-7 NIC. GPUDirect RDMA does not exist on this platform. Design for host-memory RoCE plus NCCL.

## Topology

```text
          Kubernetes / management LAN (10 GbE, Realtek r8169)
     mgmt NIC                          mgmt NIC
  +-------------+                  +-------------+
  |   spark-0   |                  |   spark-1   |
  |  GB10 GPU   |                  |  GB10 GPU   |
  |  128 GB     |                  |  128 GB     |
  |  unified    |                  |  unified    |
  |  CX-7 ======+== QSFP DAC ======+====== CX-7  |
  +-------------+   direct, 200G   +-------------+
```

- The Sparks join an existing Talos cluster as workers only. They do not run etcd.
- Management and pod traffic use the onboard 10 GbE NIC.
- Spark-to-Spark model traffic uses the ConnectX-7 QSFP link, with static addresses, MTU 9000 and no default route.

## ConnectX-7 layout (one cable)

With one DAC in QSFP port 0, Linux shows two `Up` 200 Gb/s interfaces on each Spark. They are two PCIe functions on two PCIe roots that share the same physical port:

- `enp1s0f0np0` (PCIe `0000:01:00.0`, RDMA device `mlx5_0`)
- `enP2p1s0f0np0` (PCIe `0002:01:00.0`, RDMA device `mlx5_2`)

The `f1np1` functions are down. Give each `Up` function its own subnet (this guide uses `10.100.0.0/24` and `10.101.0.0/24`). Because both functions share one L2 link, you must fix ARP behavior (see [gotchas](10-talos-gotchas.md#two-nics-one-link-arp)).

## Confirmed platform constraints

- NVIDIA states that GPUDirect RDMA is not supported on GB10, because GPU memory is unified host memory.
- Do not use `nvidia-peermem`, DMA-BUF GPUDirect, GDRCopy or `nvidia-gdrdrv-device`.
- Do not use `nvidia-fabricmanager`. The Spark has no NVSwitch.
- `ib_write_bw --use_cuda_dmabuf` is expected to fail. It is not a fault signal.
- `nvidia-smi` shows `Memory-Usage: Not Supported`. Use node memory metrics instead.
- GB10 has no MIG. Time-slicing is the only GPU sharing option in the device plugin.

## Unified memory changes everything

- The model weights, KV cache, CUDA graphs, page cache, containers and the kernel share one 128 GB pool.
- Kubernetes memory requests do not protect the model. A `kubectl exec python3` in a tight pod has OOM-killed a running vLLM rank.
- Load strategy matters. Eager safetensors loading staged shards in anonymous memory and OOM-killed both ranks. Lazy (mmap) loading uses reclaimable page cache.
- Watch `MemAvailable` on the host, not container metrics. Healthy serving runs above 90% memory use, so raise node-memory alert thresholds for the Sparks (we use 98%).

## Workload plan

- One persistent TP=2 LLM: LeaderWorkerSet, one rank per Spark.
- Smaller GPU services (STT, TTS, embeddings): Deployments that share the GPU through time-slicing.
- Benchmarks and one-shot tests: Jobs or plain pods.
