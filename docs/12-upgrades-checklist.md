# 12. Upgrades and acceptance checklist

## Talos upgrades

1. Confirm the Image Factory catalog has `nonfree-kmod-nvidia-lts` for the new Talos version.
2. Build `factory.talos.dev/metal-installer/<SCHEMATIC_ID>:<NEW_VERSION>`.
3. Stop the LLM group (both ranks restart anyway).
4. Upgrade one Spark. Run the acceptance checks below.
5. Upgrade the second Spark only after the first is clean.
6. Keep both Sparks on the same version.

```bash
talosctl -n <IP> upgrade --image factory.talos.dev/metal-installer/<SCHEMATIC_ID>:<NEW_VERSION>
```

If an upgrade controller manages the cluster, pin the Sparks to the tested version and make sure the controller uses the factory installer.

## GPU Operator upgrades

Keep `driver.enabled: false`. Compare toolkit and CDI defaults with the Talos integration test values. Rerun the CUDA smoke test.

## Acceptance checklist

- Node boots consistently with the nonfree driver and is `Ready`.
- `talosctl get extensions` shows the NVIDIA kmod and container toolkit.
- `dmesg` has no NVRM errors.
- ConnectX functions use `mlx5_core`, fabric links are `Up` at MTU 9000.
- `/dev/infiniband/rdma_cm` exists.
- Jumbo ping works on both fabric subnets, in both directions.
- Node advertises `nvidia.com/gpu` (4 with time-slicing) and `rdma/spark_roce`.
- CUDA vector-add passes.
- `ib_write_bw` host-memory test reaches about 97 Gb/s per function.
- Upgrade with `--reboot-mode powercycle`. A kexec reboot can leave the GPU uninitialized.
- `kubectl get node` shows `nvidia.com/gpu` above 0.
- `/proc/cmdline` has `pci=pcie_bus_safe`, and `lspci` shows MaxPayload 512 bytes on the ConnectX-7 functions.
- NCCL all-reduce with both roots reaches about 180 Gb/s or more at 256 MiB.
- The LLM group starts with one rank per Spark, and the NCCL log shows the IB/RoCE transport.
- A short matched-decode run is within 5% of your last baseline.
- Host `MemAvailable` after warm-up has headroom (we aim for 5 GiB or more on the leader).
- Versions recorded: Talos, schematic ID, driver, Operator, LWS, firmware, NCCL, image digests.

## Five rules

1. Install and upgrade with the Image Factory installer that matches your schematic.
2. Do not chase GPUDirect RDMA on GB10.
3. Time-slice replicas are tickets, not partitions. Unified memory is shared by everything.
4. One rank per Spark, fixed by node selector or required anti-affinity.
5. Judge capacity with host memory, latency and tokens per second, not with slot counts.
