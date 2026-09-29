# 3. Install and join

## Bottom line

Boot the ISO, discover the disk and NICs in maintenance mode, apply a normal worker config plus the Spark patch plus a per-node fabric patch. Do not bootstrap etcd.

## 1. Prepare the hardware

1. Update firmware under DGX OS first (optional, but easy while DGX OS is there).
2. Disable Secure Boot, unless you run a signed Talos flow.
3. Connect the onboard 10 GbE port to the LAN. Connect the QSFP DAC between the two Sparks (port 0 on both).
4. Write the ISO to USB and boot it. Wait for maintenance mode. Note the DHCP address.

```bash
export MAINT_IP=<address shown on the console>
```

## 2. Discover the disk

```bash
talosctl -n "$MAINT_IP" --insecure get disks
```

The internal NVMe is `/dev/nvme0n1` (4 TB). USB media shows as `/dev/sda`. Install overwrites the selected disk.

## 3. Discover the NICs

```bash
talosctl -n "$MAINT_IP" --insecure get links
talosctl -n "$MAINT_IP" --insecure get links enp1s0f0np0 -o yaml
```

Record for each ConnectX function: name, `permanentAddr`, `busPath`, link state. Expected on a stock Spark:

- `enP7s7` - Realtek r8169, management
- `enp1s0f0np0`, `enp1s0f1np1`, `enP2p1s0f0np0`, `enP2p1s0f1np1` - ConnectX-7 (`mlx5_core`)

Pin the management NIC by `driver: r8169`. Pin fabric NICs by `permanentAddr`. Do not use interface names or `hardwareAddr` as selectors.

## 4. Build the config

Start from your cluster's normal `worker.yaml` (from `talosctl gen config` or your secrets bundle). Then layer two patches:

- [`worker-dgx-spark.patch.yaml`](../manifests/talos/worker-dgx-spark.patch.yaml) - installer, kernel modules, sysctls, labels, taint, storage layout.
- [`patches/spark-0-fabric.yaml`](../manifests/talos/patches/spark-0-fabric.yaml) - per-node ConnectX addresses.

Fabric patch example:

```yaml
machine:
  network:
    interfaces:
      - deviceSelector:
          permanentAddr: "<SPARK0_CX7_PORT_A_MAC>"   # enp1s0f0np0
        addresses: [10.100.0.10/24]
        mtu: 9000
      - deviceSelector:
          permanentAddr: "<SPARK0_CX7_PORT_B_MAC>"   # enP2p1s0f0np0
        addresses: [10.101.0.10/24]
        mtu: 9000
```

The second Spark uses `.11` on both subnets. There are no routes on these interfaces.

Do **not** put a hostname in the per-node patch after the node has joined. A rename re-registers the node, and the new node object loses the taint you set by hand.

## 5. Validate and apply

```bash
talosctl validate --mode metal --strict --config <(talosctl machineconfig patch worker.yaml \
  --patch @manifests/talos/worker-dgx-spark.patch.yaml \
  --patch @manifests/talos/patches/spark-0-fabric.yaml)

talosctl apply-config -n "$MAINT_IP" --insecure --file worker.yaml \
  --config-patch @manifests/talos/worker-dgx-spark.patch.yaml \
  --config-patch @manifests/talos/patches/spark-0-fabric.yaml
```

Check before apply: install disk, installer image (the nonfree schematic), unique hostnames, MACs on the right node, no route on fabric NICs.

## 6. Verify

```bash
kubectl get nodes -o wide
talosctl -n <NODE_IP> get extensions          # expect nonfree-kmod-nvidia-lts + nvidia-container-toolkit-lts
talosctl -n <NODE_IP> dmesg | grep -Ei 'nvidia|NVRM|mlx5'
talosctl -n <NODE_IP> get links               # fabric NICs Up, MTU 9000
talosctl -n <NODE_IP> ls /dev/infiniband      # rdma_cm, uverbs0..3, umad0..3
```

## 7. Set the taint on joined nodes

A node that has already joined cannot change its own taints through machine config. Apply the taint with kubectl once:

```bash
kubectl taint node <spark> nvidia.com/gpu=present:NoSchedule
```

Then add tolerations to every DaemonSet that must run on the Sparks (log shippers, node exporters, canaries). The GPU Operator DaemonSets already tolerate `nvidia.com/gpu`.

## Storage layout

The 4 TB NVMe is split so model weights cannot fill `/var`:

- `EPHEMERAL` (`/var`): capped at 500 GiB with a `VolumeConfig`.
- `models` user volume: fixed 3 TiB XFS, mounted at `/var/mnt/models`.

The EPHEMERAL cap applies only when the partition is first created. On a node that is already installed:

```bash
# one node at a time
talosctl -n <NODE_IP> reset --system-labels-to-wipe EPHEMERAL --reboot --graceful=true
```

Result on both nodes: `/var` 537 GB, `u-models` 3.3 TB. Node names, taints and fabric addresses stay.

**Gotcha:** after this reset one Spark fell through to PXE boot. Selecting the NVMe entry in the firmware boot menu fixed it. Set NVMe first in the boot order on both Sparks before you reset.

The kubelet needs `extraMounts` for `/var/mnt` with `rshared`, or hostPath pods see an empty directory.
