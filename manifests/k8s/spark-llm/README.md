# spark-llm manifests

One LeaderWorkerSet per model. Only one runs at a time; toggle with `switch-model.sh glm|qwen|mm`.

- `lws-glm-exl3.yaml` + `glm-5.3-flash-exl3/` - GLM-5.3-Flash EXL3 4bpw, MiaAI-Lab recipe. Image built from that recipe at commit `943912c` (`ghcr.io/<your-org>/glm53-flash-sm121:943912c`).
- `lws-glm-nvfp4.yaml` + `glm-5.3-flash-nvfp4/` - GLM-5.3-Flash NVFP4, mmastrac recipe image at `6db84d4`, with `experimental/` fetched at `2288993` and mounted over the image. Current best configuration.
- `lws-qwen.yaml` + `qwen3.8-flash-next/` - Qwen3.8-Flash-Next, stock `vllm/vllm-openai:v0.30.0` plus the MiaAI-Lab v0.30 lane recipe.

Replace before use:

- `kubernetes.io/hostname: spark-0|spark-1` - your node names.
- `10.100.0.x` / `10.101.0.x` - your fabric addresses. `10.0.0.20/21` - your management addresses (NVFP4 lane only).
- `ghcr.io/<your-org>/...` - your image registry, plus an `imagePullSecret` named `regcred` if private.
- `llm.example.com` in `httproute.yaml`.
- Interface names (`enp1s0f0np0`, `enP7s7`) if yours differ.

Weights come from the `/var/mnt/models` volume; see `../model-sync/catalog.yaml` for the pinned revisions.
