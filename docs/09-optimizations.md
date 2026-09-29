# 9. Optimizations tried

Every change was one git commit, one ConfigMap sync and one group restart, then the same benchmark. "Noise" means the difference was inside the run-to-run spread we measured with no change (for example C4 aggregate moved 69-84 tok/s between identical runs).

## Platform level

| Change | Result | Kept |
|---|---|---|
| `vm.compaction_proactiveness=0` | No change on short runs. Recipe reports it removes 4-5 s stalls every ~37 s under memory pressure. | Yes |
| `arp_ignore=1`, `arp_announce=2` | Fixed RoCE on the second ConnectX subnet. | Yes (required) |
| `NCCL_MAX_NCHANNELS=4` (from 8) | Fabric 151 -> 162 Gb/s, prefill +2%. Decode unchanged. | Yes |
| `NCCL_MAX_NCHANNELS=16` | Fabric 126 Gb/s, prefill -3%. | No |
| CPU governor `performance` | Noise. | No |
| GPU clock lock 3,003 MHz | Accepted, no effect. GB10 stays near 2.5 GHz under load. | No |
| DCGM exporter off | No effect. | No |
| Persist NVIDIA JIT / Triton / TileLang / vLLM caches on hostPath | Minutes off cold start. | Yes |
| Bake runtime patches into an image | Start patch phase 4 min -> 1 s. | Yes |

## GLM-5.3-Flash EXL3 lane (MiaAI-Lab recipe)

| Change | Result | Kept |
|---|---|---|
| `MAX_NUM_SEQS` 4 -> 8 | Short prompts at C8: +43-49% aggregate, TTFT 73 s -> 3.3 s. No change at 32k+ (prefill-bound). | Yes, later back to 4 with the cooperative MoE kernel |
| Adaptive-k (`ema`, k set 2,4,7) + FP8 dense | Decode +10-32%, prefill 10-13% slower. | Yes |
| Adaptive-k without FP8 dense | Leader host RAM fell to 0-25 MB; a 32k request took 16.5 min. FP8 dense saves ~2 GiB. | No |
| Long CUDA-graph capture list (24 sizes) | +2.2 GiB graph memory, leader MemAvailable 0.29 GB. | No |
| Short capture list `1 2 3 4 5 8 16 24 32` | Same speed as the long list, ~1.9 GiB freed. | Yes |
| k set 2,3,4 | Slower everywhere; structured -23%. | No |
| `GLM53_EXL3_MOE_FAST=1` | +8-11% decode. | Replaced by cooperative MoE |
| Cooperative MoE kernel (release `.so`, digest-pinned) | Same as MOE_FAST within noise. Alternatives, not additive. | Yes |
| Recipe author's pinned image | Same speed as our own image. | No (slower start, no instanttensor) |
| `GLM53_DENSE_FP8=all`, KV 11 GiB | Prose 31.7 -> 35.0, structured 72.9 -> 75.6. | Yes |
| `GLM53_KDA_BF16_LARGE_M=1` | 69.6k prefill -13% TTFT. Decode unchanged. | Yes |

## GLM-5.3-Flash NVFP4 lane (mmastrac recipe)

Baseline: recipe defaults at TP=2.

| Change | Result | Kept |
|---|---|---|
| All dense linears NVFP4 (`VLLM_DENSE_W4=.`, 265 layers incl. lm_head) | Structured +7%, code/prose flat, 16 streams best. GSM8K 97.6%, HumanEval 153/164. | Yes |
| NVFP4 lm_head only | Also a gain, close to the above. Differences on code/prose likely noise. | Runner-up |
| Force k=7 | Prose 35.7 -> 28.8. Adaptive k is correct. | No |
| RecoverSSM off | 16 streams 155 -> 76, KV pool 1.10M -> 689k tokens. | No |
| MegaMoE max tokens 8 -> 16 | 16 streams 155 -> 143. | No |
| All-reduce ceiling 256K -> 512K | Neutral. | No |
| Adaptive-k fixed cost table | 16 streams 132 (worse). | No |
| Adaptive-k per-request k | 10-15% slower above 1 stream. | No |
| KV pin 8 -> 4 GiB | Crash at start: `KVBlockZeroer` block count not a multiple of the drafter pool. | No |
| Eager safetensors load | Both ranks OOM-killed mid-load. | No, use lazy |

## Qwen3.8-Flash-Next lane

| Change | Result | Kept |
|---|---|---|
| Marlin MoE backend alone | No gain, TTFT 3-8% slower. | No |
| K=5 sampled drafts + block verify, without matching drafter weights | -15-20%; acceptance 3.1 of 6. | No |
| hibrid48 weights + cluster-kit settings (K=5 block verify, Marlin, no EP, FULL_AND_PIECEWISE graphs, reviewed patches) | Decode +60-150%, KV pool 1.38M -> 2.15M tokens, 11 GB more free memory. Prefill 15-17% slower. Quality within noise. | Yes |
| TensorFold runtime (MLX 4-bit weights) | Short replies 1.5x faster, but prefill ~240 tok/s vs ~3,500, one request at a time. 128k TTFT ~10 min. | No, wrong fit for long-prompt agents |

We did not run third-party binaries we could not review. One kit's single-node image shipped a closed shared library. For its cluster image, we pulled the registry layers without running them: all but the last two layers were byte-identical to stock `vllm/vllm-openai:v0.30.0`, the last two held only Python patches (ELF scan clean), and we vendored the four patches we needed.

## Why we trail published numbers by 5-15%

- Per-step kernel cost matches the recipe authors' (GLM NVFP4: 31.5-32.4 ms step base vs 32.1 published). A MoE microbenchmark on our node matched the author's to within 5%.
- Draft acceptance depends on the prompt. Our random-word matrix gives about 2.2 tokens/step; code prompts give 5+.
- Fabric: 162 Gb/s vs about 190 expected. Affects prefill more than decode.
- A full power drain (unplugged) has fixed a slow fabric for others. Not yet tested here.

## Lessons

- Change one thing per restart. Two changes together hid a memory regression once.
- Always watch host `MemAvailable` during a benchmark. Throughput regressions on GB10 are often memory pressure.
- Match the benchmark protocol before you compare with someone else's number.
- Use unique prompts per cell, or the prefix cache will make the numbers look far too good.
