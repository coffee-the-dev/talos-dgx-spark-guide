# Talos Linux on NVIDIA DGX Spark

A field guide to running two NVIDIA DGX Spark (GB10) systems as Talos Linux Kubernetes workers, and serving one large LLM across both with tensor parallelism (TP=2) over the ConnectX-7 link.

This is a record of a real build. It covers what worked, what did not, the Talos-specific traps, and measured benchmark results. All hostnames, addresses and MAC addresses in this repo are placeholders.

## Result in one paragraph

Two Sparks run as ordinary Talos workers with the proprietary NVIDIA 580 LTS driver from an Image Factory schematic. The ConnectX-7 ports carry RoCE v2 at about 97 Gb/s per port (about 182 Gb/s with both). NCCL all-reduce reaches 178-189 Gb/s once the kernel argument `pci=pcie_bus_safe` is set (Talos omits it; DGX OS sets it). A LeaderWorkerSet places one vLLM rank on each Spark. GLM-5.3-Flash (NVFP4, TP=2, DFlash speculative decoding) serves at 37-40 tok/s single stream on random-word prompts, 65-99 tok/s on real code and structured prompts, and prefills about 2,700 tok/s at 32k context. Qwen3.8-Flash-Next reaches 90-95 tok/s on code prompts.

## Contents

1. [Architecture and constraints](docs/01-architecture.md) - topology, what GB10 does and does not support
2. [Talos image and schematics](docs/02-talos-image.md) - Image Factory, driver choice, why the open driver fails
3. [Install and join](docs/03-install-and-join.md) - disk and NIC discovery, machine config, storage layout
4. [GPU Operator and time-slicing](docs/04-gpu-operator.md)
5. [ConnectX-7, RoCE and RDMA device plugin](docs/05-networking-rdma.md)
6. [Model storage and sync](docs/06-model-storage.md)
7. [LeaderWorkerSet serving](docs/07-lws-serving.md) - the pod spec that works, and why each field is there
8. [Benchmarks](docs/08-benchmarks.md) - method and results
9. [Optimizations tried](docs/09-optimizations.md) - kept, reverted, and why
10. [Talos gotchas](docs/10-talos-gotchas.md) - the short list you want before you start
11. [Troubleshooting](docs/11-troubleshooting.md)
12. [Upgrades and acceptance checklist](docs/12-upgrades-checklist.md)

## Repo layout

```text
manifests/
  talos/
    schematics/            Image Factory schematics (nonfree = the one that boots)
    worker-dgx-spark.patch.yaml   machine-config patch for a Spark worker
    patches/               per-node ConnectX-7 fabric addressing
  k8s/
    gpu-operator/          Helm values (driver + toolkit off)
    lws/                   LeaderWorkerSet controller (Argo CD app + values)
    rdma-shared-device-plugin/
    model-sync/            pinned model catalog + never-delete sync DaemonSet
    spark-llm/             serving: LWS per model, Service, HTTPRoute, toggle script
bench/                     GuideLLM matrix runner, aggregation, matched-decode and needle tests
```

## Versions tested

- Talos v1.14.1 (arm64), Kubernetes v1.36.1
- NVIDIA driver 580.178.04 (`nonfree-kmod-nvidia-lts` extension)
- GPU Operator v26.7.x, LeaderWorkerSet v0.11.0
- RDMA shared device plugin v1.5.4
- vLLM v0.30.0 (Qwen lane) and recipe-specific vLLM builds (GLM lanes)
- GuideLLM v0.7.4

## Credits

The model-serving work stands on community recipes. This repo does not re-host their code; the manifests fetch it at pinned commits.

- [MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks](https://github.com/MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks)
- [MiaAI-Lab/Qwen3.8-Flash-Next-Dual-DGX-Sparks](https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Dual-DGX-Sparks)
- [mmastrac/glm-5.3-flash-4x-gx10](https://github.com/mmastrac/glm-5.3-flash-4x-gx10)
- myllmbox Qwen3.8-Flash-Next cluster kit and hibrid48 weights
- [Sidero Labs](https://github.com/siderolabs) for Talos, extensions and the GPU Operator integration test values
- [keiretsu-labs talconfig](https://github.com/keiretsu-labs/kubernetes-manifests) - early field report of the open-driver boot failure

## License

Documentation: CC BY 4.0. Scripts and manifests written for this repo: MIT. Third-party recipes keep their own licenses. Some model weights referenced here (for example the DFlash2 drafter, CC BY-NC-ND) have non-commercial terms; check each model card.
