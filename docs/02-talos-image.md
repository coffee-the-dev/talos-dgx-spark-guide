# 2. Talos image and schematics

## Bottom line

Use the **proprietary** NVIDIA 580 LTS kernel module extension. The open-module image does not boot on GB10. Use the installer from the same schematic as the ISO.

## The schematic that works

[`manifests/talos/schematics/dgx-spark-nonfree.yaml`](../manifests/talos/schematics/dgx-spark-nonfree.yaml):

```yaml
customization:
  extraKernelArgs:
    - arm64.nobti
  systemExtensions:
    officialExtensions:
      - siderolabs/nonfree-kmod-nvidia-lts
      - siderolabs/nvidia-container-toolkit-lts
```

For Talos v1.14.1 this gives schematic ID `bc668cd34c1b046652bf89b476b33178418e343d51d4e2e3e0b5335d4e40e7ad` and driver `580.178.04`.

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

## Firmware

Update firmware under DGX OS before you wipe the disk. You can read firmware versions from Talos later without a shell:

```bash
kubectl debug node/<spark> --profile=sysadmin -it --image=alpine -- sh
# inside:
cat /sys/firmware/efi/esrt/entries/*/fw_version
apk add dmidecode && dmidecode -t 0
```

Versions we ran: BIOS 5.36, EC 0x03000508, SoC 0x02009b0b. Firmware was not a factor in any result here.
