#!/usr/bin/env python3
"""Recipe-style single-stream decode test: chat template, thinking off, real code
prompt, natural stop (no ignore_eos). Reports stream decode tok/s and server
acceptance delta. usage: matched.py [reps]"""
import json, sys, time, urllib.request, statistics, re

BASE = "http://spark-llm.spark-llm.svc:8888"
MODEL = "qwen3.8-flash-next"
PROMPTS = {
    "code": "Write a complete, well-commented Python module that implements an LRU cache class with get, put, "
            "delete, resize and stats methods, plus a thorough unittest suite for it.",
    "prose": "Write a detailed essay of about 1500 words on the history of the printing press and its effects on Europe.",
}


def metrics():
    t = urllib.request.urlopen(BASE + "/metrics", timeout=10).read().decode()
    g = lambda n: sum(float(x) for x in re.findall(rf"^{n}(?:{{[^}}]*}})? ([0-9.e+]+)$", t, re.M))
    return g("vllm:spec_decode_num_accepted_tokens_total"), g("vllm:spec_decode_num_drafts_total")


def run(prompt, temp, max_tokens=3000):
    body = {"model": MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
            "temperature": temp, "top_p": 0.95 if temp else 1.0, "stream": True,
            "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(BASE + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json"})
    start = time.time(); first = last = None; n = 0
    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            d = json.loads(line[5:])
            if d.get("usage"):
                n = d["usage"]["completion_tokens"]
            if d.get("choices") and (d["choices"][0]["delta"].get("content")):
                now = time.time(); first = first or now; last = now
    return {"tokens": n, "ttft": round(first - start, 2), "tps": round((n - 1) / (last - first), 1)}


reps = int(sys.argv[1]) if len(sys.argv) > 1 else 3
for name, p in PROMPTS.items():
    for temp in (0.6, 0.0):
        run(p, temp, 200)  # warm-up
        res = []
        for _ in range(reps):
            a0, d0 = metrics(); r = run(p, temp); a1, d1 = metrics()
            r["accept_len"] = round(1 + (a1 - a0) / max(d1 - d0, 1), 2)
            res.append(r)
        print(json.dumps({"prompt": name, "temp": temp,
                          "tps_median": statistics.median(x["tps"] for x in res), "runs": res}), flush=True)
