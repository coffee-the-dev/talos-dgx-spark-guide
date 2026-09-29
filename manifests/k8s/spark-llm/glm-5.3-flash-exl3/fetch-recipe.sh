#!/bin/sh
# Init container: fetch the recipe's runtime overlay files at a pinned commit
# into /recipe/opt/glm53 (copied over the image's /opt/glm53 at start).
set -eu
SHA=943912cdcda25f4b7e02f4626656e873c6f14847
git clone -q https://github.com/MiaAI-Lab/GLM-5.3-Flash-EXL3-2x-DGX-Sparks /tmp/r
cd /tmp/r && git checkout -q "$SHA"
O=/recipe/opt/glm53; mkdir -p "$O"
cp files/chat_template.jinja "$O/chat_template.jinja"
for p in patch_glm_video_placeholders patch_suppress_stops_in_reasoning patch_scheduler_decode_floor \
         patch_tool_choice_none patch_glm5_drafter_group patch_hybrid_prefix_hit patch_apc_per_group_retention \
         patch_apc_no_store patch_kv_capacity_log patch_xgrammar_termination patch_cache_reset \
         patch_kpool_tail_slotmap patch_kpool_tail_seed_stride patch_mamba_align_state_free patch_mamba_align_chunking patch_spinwait \
         patch_loadclone patch_adaptive_k patch_dense_fp8 patch_default_max_new_tokens patch_ablit; do
  cp "overlay/$p.py" "$O/$p.py"
done
cp overlay/exl3.py "$O/exl3.py"
cp overlay/ablit_runtime.py "$O/ablit_runtime.py"
cp -r ablit "$O/ablit"
cp scripts/boot-shape-warmup.sh "$O/boot-shape-warmup.sh"

# Cooperative MoE sources (docs/cooperative-moe-quickstart.md): adapter,
# profile generator and GPU gate. The .so is Mia's pinned release asset,
# fetched and digest-checked by entrypoint.sh.
C=/recipe/coop; mkdir -p "$C"
cp -r extensions/cooperative_moe "$C/src"
cp tests/test_exl3_overlay.py "$C/test_exl3_overlay.py"
echo "coop sources staged"
echo "recipe $SHA staged: $(ls "$O" | wc -l) entries"
