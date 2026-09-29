# 10. Talos gotchas

The short list. Each one cost us real time.

## The open NVIDIA driver does not boot on GB10

`nvidia-open-gpu-kernel-modules-lts` gives an RCU stall on CPU 0 before the Talos API starts. Use `nonfree-kmod-nvidia-lts`. See [image](02-talos-image.md).

## The installer image decides the driver, not the ISO

`.machine.install.image` must be the Image Factory installer for your schematic. The generic installer silently drops the NVIDIA extensions. This also applies to every upgrade.

## Upgrade controllers can move a Spark to the wrong version or image

A cluster-wide Talos upgrade plan (we use tuppr) targeted a version whose NVIDIA extension we had not tested. It cordoned one Spark, the upgrade job failed, and the node stayed cordoned for six hours. The LLM worker pod could not schedule, and the failure looked like a model problem.

Another Spark ended up on an older Talos version than its peer. On that version, containers saw the system disk at `/var/mnt/models` instead of the user volume.

Fixes:

- Pin each Spark to a tested version (tuppr reads the node annotation `tuppr.home-operations.com/version`).
- Make sure the upgrade plan uses the factory installer with the Spark schematic.
- Before you debug a failed model start, check `kubectl get nodes` for `SchedulingDisabled`.
- Keep both Sparks on the same Talos and driver version.

## Two NICs, one link: ARP

Both ConnectX functions that are `Up` share one physical QSFP link, so they are on the same L2 segment. Linux default ARP lets either NIC answer for both IPs. RoCE then sends to the wrong NIC's GID and fails with `IBV_WC_RETRY_EXC_ERR` on the second subnet. TCP ping still works, which makes this confusing.

```yaml
machine:
  sysctls:
    net.ipv4.conf.all.arp_ignore: "1"
    net.ipv4.conf.all.arp_announce: "2"
```

## Missing RDMA device nodes

The base kernel has the drivers, but Talos loads only what you list. Without `rdma_ucm` there is no `/dev/infiniband/rdma_cm`. Without `ib_umad`, `ibstat` and perftest diagnostics fail. List all seven modules (see [networking](05-networking-rdma.md)).

## Taints on joined nodes

A worker cannot change its own taints after it joins. Set `nodeTaints` in config for new installs, and use `kubectl taint` for existing nodes. Do not rename a joined node in its config; the new node object has no taint.

## EPHEMERAL size is set once

`VolumeConfig` `maxSize` for `EPHEMERAL` applies only at creation. To apply it later, `talosctl reset --system-labels-to-wipe EPHEMERAL`, one node at a time. After that reset, check the firmware boot order: one Spark booted PXE until we selected the NVMe.

## hostPath under /var/mnt needs a kubelet mount

Add a kubelet `extraMounts` bind for `/var/mnt` with `rshared`. Without it, pods see the directory but not the user volume.

## hostNetwork shares Talos ports

Port 50000 is `apid` on every node. Distributed runtimes that default to 50000 (for example some recipes' `MASTER_PORT`) fail with address-in-use.

## No shell on the host

Use `kubectl debug node/<name> --profile=sysadmin --image=alpine` for firmware versions, `/sys` inspection and `nvidia-smi` clock tests. Use `talosctl dmesg`, `talosctl get links`, `talosctl ls /dev/infiniband` for the rest.

## Everything that writes on the host must be a hostPath

Talos root is read-only. Persist JIT caches, compiled kernels and weight snapshots on a hostPath under `/var/lib/...` or the models volume, or every restart rebuilds them.

## Admin certificate lifetime

The default admin talosconfig certificate expires. Issue a new one from the machine CA with `talosctl gen key/csr/crt` and a chosen `--hours` value, then update your talosconfig.
