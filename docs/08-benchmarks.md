# 8. Benchmarks

All numbers: two DGX Sparks, TP=2 over one QSFP DAC, no other GPU traffic during runs, client inside the cluster (no ingress in the path) unless stated.

## Method

Three test types. They answer different questions, and their numbers are **not** comparable with each other.

1. **GuideLLM matrix** ([`bench/matrix.sh`](../bench/matrix.sh), [`bench/agg.py`](../bench/agg.py)) - capacity under load.
   - GuideLLM v0.7.4, OpenAI chat API, streaming.
   - Random English words (`synthetic_text`), fixed prompt length, 512 output tokens forced (`ignore_eos`).
   - `concurrent` profile: exactly C requests in flight.
   - Matrix C1/C2/C4/C8 x 1k/8k/32k/128k input tokens.
   - One discarded warm-up per context size.
   - **Unique seed per cell.** Our first run used the default seed everywhere, and vLLM's prefix cache served later cells warm (128k TTFT 2.4 s instead of 87 s). That run was discarded.
   - Random words are the worst case for speculative decoding. Treat these numbers as a floor.
2. **Matched decode** ([`bench/matched.py`](../bench/matched.py)) - single-stream speed comparable to recipe READMEs: chat template, thinking off, temperature 0, fixed real prompts (prose, code, structured), natural stop, median of several runs.
3. **Needle recall** ([`bench/needle.py`](../bench/needle.py)) - long-context correctness at 8k/32k/128k and three depths.

Metrics:

- **TTFT** - time to first token, includes queue time.
- **Session tok/s** - 1000 / inter-token latency for one request.
- **Aggregate output tok/s** - all output tokens / wall time.
- **Tokens per step** - output tokens per engine iteration; above 1 means speculative drafts were accepted.

## Headline: GLM-5.3-Flash NVFP4 (current best config)

mmastrac recipe, TP=2, DFlash2 drafter with adaptive k, all dense layers NVFP4, `NCCL_MAX_NCHANNELS=4`.

### Matched decode (recipe gate bench, median of 3, 512 tokens)

- Non-streaming (structured / code / prose): **98.8 / 65.9 / 37.3 tok/s**
- Streaming: 93.0 / 70.2 / 47.5 tok/s
- Code at 1 / 2 / 4 / 8 / 16 streams: 67 / 77 / 107 / 122 / 187 tok/s aggregate
- 32k cold prefill: **2,748 tok/s**
- Preemptions: 0
- Quality: GSM8K (first 250) 97.6%, HumanEval 153/164

### GuideLLM matrix (random words, 512 output tokens)

| Input | C | TTFT p50 | Session tok/s | Aggregate out tok/s | Tok/step |
|---|---|---:|---:|---:|---:|
| 1k | 1 | 0.6 s | 40.6 | 39.4 | 2.56 |
| 1k | 8 | 1.2 s | 11.5 | 86.6 | 2.24 |
| 8k | 1 | 3.1 s | 40.1 | 32.6 | 2.50 |
| 8k | 8 | 6.5 s | 8.8 | 61.2 | 2.18 |
| 32k | 1 | 12.0 s | 39.0 | 20.8 | 2.47 |
| 32k | 8 | 42.7 s | 5.9 | 29.0 | 2.10 |
| 128k | 1 | 48.3 s | 40.4 | 8.4 | 2.52 |
| 128k | 8 | 278.6 s | 4.0 | 9.8 | 2.05 |

20/20 cells, 0 errors. Full per-cell output: [results/glm-nvfp4-guidellm.txt](../results/glm-nvfp4-guidellm.txt).

Reading it:

- Single-stream decode stays near 40 tok/s from 1k to 128k. Context length does not slow decode on this hybrid-attention model.
- Prefill is about 2,500-2,700 tok/s. A cold 128k prompt costs about 48 s.
- Long-context concurrency queues on prefill. At 128k x C8 the median request waits 4.6 minutes for its first token.

## Comparison: GLM-5.3-Flash EXL3 4bpw vs NVFP4

Same GuideLLM matrix, `MAX_NUM_SEQS=8`. EXL3 = MiaAI-Lab recipe early config. Aggregate output tok/s (TTFT p50):

| Input | C | EXL3 | NVFP4 |
|---|---|---:|---:|
| 1k | 1 | 22.2 (1.2 s) | 36.2 (0.7 s) |
| 1k | 8 | 52.7 (3.3 s) | 86.6 (1.0 s) |
| 8k | 8 | 27.9 (83 s) | 59.9 (8 s) |
| 32k | 8 | 10.9 (309 s) | 29.1 (45 s) |
| 128k | 8 | 4.8 (543 s) | 9.7 (278 s) |

NVFP4 is 1.6-2.7x higher in every cell. The gain comes from faster steps and 2x prefill, not from better draft acceptance (2.2 vs 3.1 tokens/step on random words).

The EXL3 lane improved later with tuning (matched prose 30 -> 35 tok/s, structured 64 -> 76 tok/s, see [optimizations](09-optimizations.md)), but prefill stayed near 1,300-1,500 tok/s.

## Qwen3.8-Flash-Next

Stock vLLM v0.30.0, TP=2, MTP speculative decoding.

GuideLLM C1 vs GLM EXL3 (tuned) on the same matrix. TTFT p50 | session tok/s:

- 1k: 0.55 s | 45.6 vs 1.35 s | 27.3
- 8k: 2.4 s | 34.6 vs 6.7 s | 25.1
- 32k: 9.4 s | 32.7 vs 24.9 s | 25.8
- 128k: 38.6 s | 33.6 vs 100.3 s | 26.1

With the hibrid48 weights and cluster-kit settings (see optimizations), 512-token decode at C1 rose to 55-96 tok/s, and matched decode on a code prompt reached **91-95 tok/s** (4.9-5.1 accepted tokens per step). Prose prompts: 50-52 tok/s. Prefill became 15-17% slower. Needle recall 6/6. Quality A/B vs the NVIDIA NVFP4 weights (thinking on, 764 questions): all gaps 0.5-2 points, within noise.

## Real agent traffic

An agent harness with about 25k tokens of system prompt and tool schemas, pointed at the cluster:

- **Prefix caching is the biggest single factor.** GLM EXL3: cold 20.4 s TTFT, warm 3.2 s. Qwen: warm 0.5 s.
- Tool-call turns (~9k prompt, cached): GLM 1.8-2.2 s TTFT, Qwen 0.3-0.6 s.
- A turn that adds a 28-37k token file pays full prefill for the new tokens (GLM EXL3 22 s, Qwen 11 s).
- vLLM did not report `cached_tokens` in usage; infer cache hits from TTFT.

## Load and unload times

- Unload (delete to both pods gone): about 30 s.
- GLM EXL3 cold start: 8.5 min at first (4 min of patch scripts, 55 s weights, 89 s CUDA graphs). With patches baked into an image and a persisted JIT cache: 4.5-6.5 min.
- Qwen stock vLLM: 8.5 min (3.6 min weights).
- GLM NVFP4: first boot writes a processed-weight snapshot (~48 GB per node) and builds kernels; later boots reuse both. Lazy loading costs 690 s vs 511 s eager, but eager OOM-killed both ranks.

## Hardware ceilings we measured

- GPU memory read: about 220-240 GB/s (80-88% of the 273 GB/s spec). This bounds decode, because MoE expert weights stream from memory every step.
- GPU clocks under load: 2.5 GHz, 38-45 W, no throttle. Locking to 3,003 MHz is accepted but has no effect.
- RoCE: 97.5 Gb/s per function, about 182 Gb/s both. NCCL all-reduce: 162 Gb/s at 4 channels.
- A decode step at TP=2 (GLM NVFP4, one stream): MoE about 62% of kernel time, all-reduce about 11%, dense layers about 7%. The all-reduce cost is latency (about 100 us per 64 KB call), not bandwidth.
