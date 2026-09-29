#!/bin/sh
# Init container: fetch the recipe at a pinned commit into /recipe/r.
set -eu
SHA=d23790b440d9a0977951ebbe3883ba44b89814da
git clone -q https://github.com/MiaAI-Lab/Qwen3.8-Flash-Next-Dual-DGX-Sparks /recipe/r
cd /recipe/r && git checkout -q "$SHA"
echo "recipe $SHA staged"
