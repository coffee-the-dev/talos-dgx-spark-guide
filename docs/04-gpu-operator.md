# 4. GPU Operator and time-slicing

## Bottom line

The driver is in the immutable Talos image. The GPU Operator must not install a driver or a toolkit. It runs the device plugin, GPU feature discovery, validation and DCGM.

## Values

[`manifests/k8s/gpu-operator/values.yaml`](../manifests/k8s/gpu-operator/values.yaml) (key parts):

```yaml
hostPaths:
  driverInstallDir: /usr/local
driver:
  enabled: false
toolkit:
  enabled: false
mig:
  strategy: none
```

Upstream Talos integration tests enable the Operator toolkit with `installDir: /var/lib/nvidia` and CDI. In this cluster, the `nvidia-container-toolkit-lts` system extension provides the runtime, and the Operator toolkit is off. Both approaches work. Pick one, not both.

Do not set `driver.rdma.enabled`. It targets `nvidia-peermem`, which GB10 does not support.

```bash
kubectl create namespace gpu-operator
kubectl label namespace gpu-operator pod-security.kubernetes.io/enforce=privileged
helm upgrade --install gpu-operator nvidia/gpu-operator -n gpu-operator \
  --version v26.7.1 -f manifests/k8s/gpu-operator/values.yaml --wait
```

## CUDA smoke test

```yaml
apiVersion: batch/v1
kind: Job
metadata: {name: cuda-test}
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      nodeSelector: {hardware.nvidia.com/gb10: "true"}
      tolerations: [{key: nvidia.com/gpu, operator: Exists, effect: NoSchedule}]
      containers:
        - name: cuda-test
          image: nvcr.io/nvidia/k8s/cuda-sample:vectoradd-cuda12.5.0
          resources: {limits: {nvidia.com/gpu: 1}}
```

Expect `Test PASSED`. The Operator's own CUDA validator also passes on GB10.

## Time-slicing

We keep time-slicing on with 4 replicas per GPU, so the LLM rank (1 replica) can share the GB10 with speech and embedding services.

- `renameByDefault: false` keeps the resource name `nvidia.com/gpu`. The LLM pods request `nvidia.com/gpu: 1`, which is one ticket, not the whole GPU.
- `failRequestsGreaterThanOne: true` - two tickets do not give twice the compute.
- A ticket is an admission slot. It gives no compute quota, no memory quota and no fault isolation.
- On unified memory, the LLM, its KV cache, other GPU pods and the page cache all share 128 GB. Size the model's memory budget for what else runs on the node.
- For clean benchmarks, scale other GPU clients to zero.

Per-node configs are possible with the label `nvidia.com/device-plugin.config=<key>`, if other GPU nodes in the cluster need different sharing.

## Priority classes (suggested)

- `model-serving` (100000) - the TP=2 LLM. A transient job must never evict one rank, because that restarts the whole group.
- `interactive-gpu` (50000) - STT, TTS.
- `gpu-batch` (1000) - benchmarks.

Priority affects scheduling and preemption only. It does not reserve GPU time.

## Observability

- DCGM exporter works on GB10 for utilization, clocks, power and XID errors. Per-container attribution under time-slicing is limited.
- Framebuffer memory metrics are not meaningful on unified memory. Use node-exporter `MemAvailable` and PSI memory pressure.
- vLLM `/metrics` from the leader gives TTFT, inter-token latency, queue depth, KV use and spec-decode acceptance.
