#!/usr/bin/env python3
"""Needle-in-a-haystack + TTFT at long context. usage: needle.py BASE MODEL TOKDIR OUT.jsonl CTX [CTX...]"""
import json, sys, time, random, urllib.request
from transformers import AutoTokenizer
base, model, tokdir, out = sys.argv[1:5]; ctxs = [int(x) for x in sys.argv[5:]]
tok = AutoTokenizer.from_pretrained(tokdir)
words = ("river stone quiet lamp orbit copper meadow signal harbor pencil velvet engine window forest "
         "ladder marble thunder garden rocket cotton silver canyon pillow falcon").split()
for ctx in ctxs:
    for depth in (0.1, 0.5, 0.9):
        rnd = random.Random(f"{ctx}-{depth}")
        code = f"{rnd.randint(1000,9999)}-{rnd.choice(['BLUE','AMBER','OLIVE','CORAL'])}"
        needle = f" The vault access code is {code}. "
        filler = " ".join(rnd.choice(words) for _ in range(int(ctx * 1.1)))
        ids = tok(filler, add_special_tokens=False)["input_ids"][: ctx - 200]
        cut = int(len(ids) * depth)
        text = tok.decode(ids[:cut]) + needle + tok.decode(ids[cut:])
        body = {"model": model, "stream": True, "max_tokens": 64, "temperature": 0,
                "stream_options": {"include_usage": True},
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": [{"role": "user", "content": text + "\n\nWhat is the vault access code? Reply with the code only."}]}
        t0 = time.time(); first = None; txt = ""; usage = None; err = None
        try:
            r = urllib.request.urlopen(urllib.request.Request(base + "/v1/chat/completions", json.dumps(body).encode(),
                                       {"Content-Type": "application/json"}), timeout=3600)
            for line in r:
                if not line.startswith(b"data: {"): continue
                j = json.loads(line[6:])
                if j.get("usage"): usage = j["usage"]
                for c in j.get("choices") or []:
                    d = (c.get("delta") or {}).get("content") or ""
                    if d and first is None: first = time.time() - t0
                    txt += d
        except Exception as e:
            err = repr(e)[:300]
        rec = {"ctx": ctx, "depth": depth, "code": code, "pass": code in txt, "ttft_s": first,
               "e2e_s": round(time.time() - t0, 2), "prompt_tokens": (usage or {}).get("prompt_tokens"),
               "answer": txt.strip()[:80], "err": err}
        print(json.dumps(rec), flush=True); open(out, "a").write(json.dumps(rec) + "\n")
