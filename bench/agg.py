import json,glob,os,sys,statistics as st
def pct(xs,p):
    xs=sorted(xs); 
    if not xs: return float('nan')
    k=(len(xs)-1)*p; f=int(k); c=min(f+1,len(xs)-1); return xs[f]+(xs[c]-xs[f])*(k-f)
rows=[]
for tagdir in sorted(glob.glob('/work/results/*')):
    tag=os.path.basename(tagdir)
    for f in glob.glob(tagdir+'/c*-ctx*.json'):
        name=os.path.basename(f)[:-5]; c=int(name.split('-')[0][1:]); ctx=int(name.split('ctx')[1])
        b=json.load(open(f))['benchmarks'][0]; R=b['requests']
        ok=R['successful']; nerr=len(R['errored']); ninc=len(R['incomplete'])
        if not ok: rows.append(dict(tag=tag,c=c,ctx=ctx,n=0,err=nerr,inc=ninc)); continue
        ttft=[r['time_to_first_token_ms']/1000 for r in ok]
        dec=[1000/r['inter_token_latency_ms'] for r in ok if r['inter_token_latency_ms']]
        e2e=[r['request_latency'] for r in ok]
        t0=min(r['request_start_time'] for r in ok); t1=max(r['request_end_time'] for r in ok)
        out=sum(r['output_tokens'] for r in ok); inp=sum(r['prompt_tokens'] for r in ok)
        rows.append(dict(tag=tag,c=c,ctx=ctx,n=len(ok),err=nerr,inc=ninc,
          in_tok=round(st.mean(r['prompt_tokens'] for r in ok)),
          ttft_p50=pct(ttft,.5),ttft_p95=pct(ttft,.95),
          sess_tps_p50=pct(dec,.5),sess_tps_p5=pct(dec,.05),
          e2e_p50=pct(e2e,.5),e2e_p95=pct(e2e,.95),
          agg_out_tps=out/(t1-t0),agg_total_tps=(out+inp)/(t1-t0),wall=t1-t0,
          acc=st.mean(r['output_tokens_per_iteration'] for r in ok)))
rows.sort(key=lambda r:(r['tag'],r['ctx'],r['c']))
json.dump(rows,open('/work/results/summary.json','w'),indent=1)
for r in rows:
    if r['n']==0: print(r); continue
    print(f"{r['tag']:6} ctx={r['ctx']:>6} C{r['c']} n={r['n']} err={r['err']} ttft p50={r['ttft_p50']:.2f}s p95={r['ttft_p95']:.2f}s sess={r['sess_tps_p50']:.1f}t/s(p5 {r['sess_tps_p5']:.1f}) agg_out={r['agg_out_tps']:.1f} agg_tot={r['agg_total_tps']:.0f} e2e p50={r['e2e_p50']:.1f} p95={r['e2e_p95']:.1f} tok/iter={r['acc']:.2f}")
