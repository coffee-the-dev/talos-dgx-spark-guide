# 2. Talos image and schematics

## Bottom line

Use the **proprietary** NVIDIA 580 LTS kernel module extension. The open-module image does not boot on GB10. Use the installer from the same schematic as the ISO. Add `pci=pcie_bus_safe`, or the ConnectX-7 link loses about 15% of its bandwidth.

## The schematic that works

[`manifests/talos/schematics/dgx-spark-nonfree.yaml`](../manifests/talos/schematics/dgx-spark-nonfree.yaml):

```yaml
customization:
  extraKernelArgs:
    - arm64.nobti
    - pci=pcie_bus_safe
  systemExtensions:
    officialExtensions:
      - siderolabs/nonfree-kmod-nvidia-lts
      - siderolabs/nvidia-container-toolkit-lts
```

For Talos v1.14.1 this gives schematic ID `2c3e2f033ecf0565e7700c66011e47fc3f0c68a83b6b76afd5fb8d106e8fb052` and driver `580.178.04`.

## What did not work: open kernel modules

NVIDIA recommends the open GPU kernel modules for GB10 on DGX OS. On Talos, the image with `siderolabs/nvidia-open-gpu-kernel-modules-lts` hit an **RCU stall on CPU 0** during boot, before the Talos API came up. The same hardware booted the proprietary image at once. Talos documentation also states that Grace Blackwell arm64 needs the proprietary driver. An independent public Talos + Spark deployment reported the same crash.

You lose nothing by using the proprietary module: GPUDirect RDMA, the main feature that differs, is unsupported on GB10 anyway.

The failed schematic is kept as [`dgx-spark-open-DO-NOT-USE.yaml`](../manifests/talos/schematics/dgx-spark-open-DO-NOT-USE.yaml).

## Do not add

- `nvidia-gdrdrv-device` - GPUDirect path, unsupported on GB10.
- `nvidia-fabricmanager-*` - no NVSwitch.
- Mellanox or mlx5 extensions - `mlx5_core`, `mlx5_ib` and the RDMA stack are already in the base Talos arm64 kernel. You only need to load them (see [install](03-install-and-join.md)).

## Build the image

```bash
export TALOS_VERSION=v1.14.1
ID=$(curl -fsS -X POST -H 'Content-Type: application/yaml' \
  --data-binary @manifests/talos/schematics/dgx-spark-nonfree.yaml \
  https://factory.talos.dev/schematics | jq -r .id)
echo "$ID"
curl -fL -o talos-dgx-spark-${TALOS_VERSION}.iso \
  "https://factory.talos.dev/image/${ID}/${TALOS_VERSION}/metal-arm64.iso"
echo "installer: factory.talos.dev/metal-installer/${ID}:${TALOS_VERSION}"
```

Schematic IDs are content hashes. The same YAML always gives the same ID.

Before you pick a Talos version, check that the Image Factory catalog lists a `nonfree-kmod-nvidia-lts` build for it.

## Why the installer image matters

The ISO is only the boot environment. The machine config field `.machine.install.image` decides what goes on disk. If it points at the generic `ghcr.io/siderolabs/installer`, the installed system has no NVIDIA driver. The same rule applies to every upgrade (see [upgrades](12-upgrades-checklist.md)).

## `arm64.nobti`

Kept from community Talos-on-GB10 reports to avoid Branch Target Identification problems with the NVIDIA module. We did not test removing it.

## `pci=pcie_bus_safe` (required for full fabric speed)

DGX OS boots with `pci=pcie_bus_safe`. Talos does not. Without it, the kernel leaves every PCIe device at a Max Payload Size of 128 bytes, although the root ports, the ConnectX-7 and the GPU support more. A ConnectX-7 root is a PCIe Gen5 x4 link, so the smaller payload costs a large share of its bandwidth.

Check from a privileged debug pod:

```bash
lspci -vvv -s 0000:01:00.0 | grep -E 'MaxPayload [0-9]+ bytes, MaxReadReq'
# bad:  MaxPayload 128 bytes, MaxReadReq 512 bytes
# good: MaxPayload 512 bytes, MaxReadReq 512 bytes   (same as DGX OS)
```

Measured on our pair (NCCL all-reduce over RoCE, two ranks, BF16, 32-512 MiB):

- One ConnectX-7 root: 96 -> 111 Gb/s.
- Both roots, 8 channels: 131-163 -> 178-189 Gb/s.
- Both roots, 4 channels: 162-164 -> 173-178 Gb/s. With the fix, the NCCL default of 8 channels is better.
- GLM-5.3-Flash NVFP4 (mmastrac recipe, stock settings, RigMark): decode +5-8%, 64k cold prefill +6%.

A Talos upgrade to the new schematic applies it. It needs one reboot per node.

## Other DGX OS kernel arguments

Stock DGX OS also sets `init_on_alloc=0`, `iommu.passthrough=0` and `initcall_blacklist=tegra234_cbb_init`. Talos already translates device DMA through the IOMMU, the same as DGX OS. We are testing `init_on_alloc=0`, `preempt=none`, `pci=pcie_bus_perf` and `pcie_aspm.policy=performance`; see [optimizations](09-optimizations.md).

The NVIDIA Aerial (5G RAN) Spark guide adds real-time settings such as 1 GiB hugepages, `idle=poll`, `isolcpus` and `nohz_full`. They target radio timing, not LLM serving. The hugepages reserve 32 GiB of the unified memory that vLLM needs, so we did not use them.

## Firmware

Update firmware under DGX OS before you wipe the disk. You can read firmware versions from Talos later without a shell:

```bash
kubectl debug node/<spark> --profile=sysadmin -it --image=alpine -- sh
# inside:
cat /sys/firmware/efi/esrt/entries/*/fw_version
apk add dmidecode && dmidecode -t 0
```

Versions we ran: BIOS 5.36, EC 0x03000508, SoC 0x02009b0b. Firmware was not a factor in any result here.
