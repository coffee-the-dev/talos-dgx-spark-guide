import json,glob,os,sys
def pct(xs,p):
    xs=sorted(xs)
    if not xs: return float('nan')
    k=(len(xs)-1)*p; f=int(k); c=min(f+1,len(xs)-1); return xs[f]+(xs[c]-xs[f])*(k-f)
def load(tag):
    R={}
    for f in glob.glob(f'/work/results/{tag}/c*-ctx*.json'):
        name=os.path.basename(f)[:-5]; c=int(name.split('-')[0][1:]); ctx=int(name.split('ctx')[1])
        try: b=json.load(open(f))['benchmarks'][0]['requests']
        except Exception as e: continue
        ok=b['successful']
        if not ok: R[(ctx,c)]=dict(n=0,err=len(b['errored'])); continue
        t0=min(r['request_start_time'] for r in ok); t1=max(r['request_end_time'] for r in ok)
        R[(ctx,c)]=dict(n=len(ok),err=len(b['errored']),
          ttft=pct([r['time_to_first_token_ms']/1000 for r in ok],.5),
          sess=pct([1000/r['inter_token_latency_ms'] for r in ok if r['inter_token_latency_ms']],.5),
          agg=sum(r['output_tokens'] for r in ok)/(t1-t0),
          tot=sum(r['output_tokens']+r['prompt_tokens'] for r in ok)/(t1-t0),
          e2e=pct([r['request_latency'] for r in ok],.5),
          tpi=sum(r['output_tokens_per_iteration'] for r in ok)/len(ok),
          outtok=sum(r['output_tokens'] for r in ok)/len(ok), intok=sum(r['prompt_tokens'] for r in ok)/len(ok))
    return R
A=load(sys.argv[1]); B=load(sys.argv[2])
for k in sorted(set(A)|set(B)):
    a=A.get(k); b=B.get(k)
    f=lambda r: 'n/a' if not r or not r.get('n') else f"n={r['n']} e={r['err']} in={r['intok']:.0f} out={r['outtok']:.0f} ttft={r['ttft']:.2f}s sess={r['sess']:.1f} agg={r['agg']:.1f} tot={r['tot']:.0f} e2e={r['e2e']:.1f} tpi={r['tpi']:.2f}"
    print(f"ctx={k[0]:>6} C{k[1]}  MIA: {f(a)}\n              NOW: {f(b)}")
