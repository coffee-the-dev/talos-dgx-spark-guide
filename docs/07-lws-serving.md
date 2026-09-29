# 7. LeaderWorkerSet serving

## Bottom line

One LeaderWorkerSet group of size 2. The leader is rank 0 and serves the API. The worker is rank 1 (`--headless`). Both use host networking so NCCL can reach the ConnectX interfaces.

## Install LWS

```bash
helm install lws oci://registry.k8s.io/lws/charts/lws --version 0.11.0 \
  -n lws-system --create-namespace --wait
```

LWS 0.11.0 needs Kubernetes 1.34 or later. The chart requests 1 CPU / 1 GiB by default; the controller is idle most of the time, so we lower it ([values](../manifests/k8s/lws/helm-values.yaml)).

With Argo CD, ignore the webhook cert Secret data and the webhook `caBundle` fields. LWS writes them at runtime ([app](../manifests/k8s/lws/argocd-app.yaml)).

## The pod spec, field by field

Full manifests: [`manifests/k8s/spark-llm/`](../manifests/k8s/spark-llm/). The important fields:

```yaml
apiVersion: leaderworkerset.x-k8s.io/v1
kind: LeaderWorkerSet
spec:
  replicas: 1
  startupPolicy: LeaderCreated
  leaderWorkerTemplate:
    size: 2
    restartPolicy: RecreateGroupOnPodRestart
    leaderTemplate:
      spec:
        nodeSelector: {kubernetes.io/hostname: spark-0}
        tolerations: [{key: nvidia.com/gpu, operator: Exists, effect: NoSchedule}]
        hostNetwork: true
        hostIPC: true
        dnsPolicy: ClusterFirstWithHostNet
        containers:
          - name: server
            env: [{name: VLLM_HOST_IP, value: 10.100.0.10}]
            securityContext:
              capabilities: {add: [IPC_LOCK, SYS_NICE]}
            resources:
              limits: {nvidia.com/gpu: 1, rdma/spark_roce: 1}
            startupProbe:
              httpGet: {path: /health, port: 8888}
              periodSeconds: 20
              failureThreshold: 270      # cold start can take 10+ minutes
            volumeMounts:
              - {name: models, mountPath: /hf, readOnly: true}
              - {name: cache,  mountPath: /root/.cache}
              - {name: shm,    mountPath: /dev/shm}
        volumes:
          - {name: models, hostPath: {path: /var/mnt/models, type: Directory}}
          - {name: cache,  hostPath: {path: /var/lib/spark-llm-cache, type: DirectoryOrCreate}}
          - {name: shm,    emptyDir: {medium: Memory, sizeLimit: 32Gi}}
    workerTemplate: {}  # same shape, nodeSelector spark-1, rank 1, --headless
```

Why each field:

- `restartPolicy: RecreateGroupOnPodRestart` - TP ranks cannot rejoin a running group. If one dies, restart both.
- `startupPolicy: LeaderCreated` - the worker starts after the leader pod exists, so the master address resolves.
- `nodeSelector` by hostname - simpler and more explicit than anti-affinity with two fixed nodes. With time-slicing, both ranks would otherwise fit on one node. If you prefer anti-affinity, it must be required, on the hostname key, on a label both templates share.
- `hostNetwork` - NCCL needs the ConnectX interfaces and their GIDs. Pod networking (flannel) has neither.
- `hostIPC` and a large memory-backed `/dev/shm` - NCCL and vLLM worker processes share memory.
- `IPC_LOCK` - RDMA memory registration pins pages.
- `VLLM_HOST_IP` on the fabric subnet - otherwise vLLM advertises the management address.
- Startup probe budget - first boots include JIT kernel builds and weight processing.

## Pick ports that Talos does not use

With `hostNetwork`, the pod shares the host's port space. Port 50000 is Talos `apid` (control-plane nodes also use 50001 for `trustd`). A recipe default of `MASTER_PORT=50000` failed with address-in-use. We use `29521`/`29531`.

## Multiple models, one at a time

Each model has its own LWS (GLM EXL3, GLM NVFP4, Qwen), all labeled `app: spark-llm, role: leader|worker`. The Service selects `app: spark-llm, role: leader`, so the endpoint follows whichever model runs. Only one set may run at a time.

[`switch-model.sh`](../manifests/k8s/spark-llm/switch-model.sh) scales the others to 0, waits for their pods to exit (frees GPU memory and the port), then scales the chosen one to 1. With Argo CD, ignore `/spec/replicas` on LeaderWorkerSets so a sync does not undo the switch, and use server-side diff, because the LWS webhook defaults fields.

## Config changes without name hashes

The model settings are a ConfigMap from an env file. With `disableNameSuffixHash`, a ConfigMap change does not roll the pods. Bump an annotation (`spark-llm/config-rev`) in both templates to roll the group.

## Recipes, not invented flags

Each lane follows a published 2x Spark recipe, fetched at a pinned commit by an init container:

- GLM-5.3-Flash EXL3 4bpw: MiaAI-Lab recipe. 20+ runtime patches applied at start, cooperative MoE kernel `.so` from the recipe's release, verified by SHA-256 and a GPU gate before serving.
- GLM-5.3-Flash NVFP4: mmastrac recipe image plus `experimental/` overrides mounted file by file, and a `mentatd` sidecar.
- Qwen3.8-Flash-Next: stock `vllm/vllm-openai:v0.30.0` plus the MiaAI-Lab v0.30 lane, later the myllmbox cluster-kit settings.

Build your own image when a recipe patches vLLM at every start. One lane spent 4 minutes of each boot in 25 patch scripts that each re-imported vLLM. Baking the patches into an image took that to about 1 second.

## Streaming through an ingress

nginx buffers upstream responses by default. Through the gateway, the first byte arrived after 4.1 s instead of 0.25 s, because the whole reply was buffered. Also, a 128k prefill can exceed nginx's 60 s read timeout before the first byte. Fix with [`snippetsfilter.yaml`](../manifests/k8s/spark-llm/snippetsfilter.yaml):

```nginx
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 1h;
proxy_send_timeout 1h;
```
