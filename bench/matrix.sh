#!/bin/sh
# usage: TARGET=http://spark-llm.spark-llm.svc:8888 MODEL=GLM-5.3-Flash-NVFP4 TOK=/work/tok matrix.sh <tag>
# Runs inside a GuideLLM v0.7.4 pod. TOK = local copy of the served model's tokenizer.
TAG=$1; OUT=/work/results/$TAG; mkdir -p $OUT
TARGET=${TARGET:-http://spark-llm.spark-llm.svc:8888}; MODEL=${MODEL:-GLM-5.3-Flash-NVFP4}; TOK=${TOK:-/work/tok}
BK="kind=openai_http,target=$TARGET,model=$MODEL,timeout=3600"
TK="kind=huggingface_auto,model=$TOK"
run() { name=$1; ctx=$2; c=$3; n=$4
  seed=$(printf "%s-%s" "$TAG" "$name" | cksum | cut -d" " -f1)
  echo "$(date -u +%FT%TZ) START $name ctx=$ctx c=$c n=$n seed=$seed" >> $OUT/progress.log
  guidellm run --backend $BK --tokenizer $TK --profile kind=concurrent,streams=$c \
    --data kind=synthetic_text,prompt_tokens=$ctx,output_tokens=512 \
    --seed kind=static,value=$seed --constraint kind=max_requests,count=$n --constraint kind=max_duration,seconds=2700 \
    --label tag=$TAG --label ctx=$ctx --label conc=$c \
    --output kind=json,path=$OUT/$name.json --disable-progress > $OUT/$name.log 2>&1
  echo "$(date -u +%FT%TZ) END $name rc=$?" >> $OUT/progress.log
}
for ctx in 1024 8192 32768 131072; do run warm-$ctx $ctx 1 1; done
for ctx in 1024 8192 32768 131072; do
  for c in 1 2 4 8; do
    case $ctx in 1024|8192) n=$((c*4)); [ $n -lt 4 ] && n=4;; 32768) n=$((c*2)); [ $n -lt 3 ] && n=3;; *) n=$c; [ $n -lt 2 ] && n=2;; esac
    run c$c-ctx$ctx $ctx $c $n
  done
done
echo "$(date -u +%FT%TZ) MATRIX DONE" >> $OUT/progress.log
