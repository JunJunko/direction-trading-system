"""Render rejected leaders alongside filled fallbacks and attribute matched trades."""
import csv,json,hashlib
from collections import defaultdict
import audit_candidate_policy as a
R=a.RUN;O=a.OUT
symbols={'002006.SZ','603098.SH','000762.SZ'};hist=defaultdict(list)
with (R/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
 for r in csv.DictReader(f):
  if r['symbol'] in symbols:hist[r['symbol']].append(a.Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
for h in hist.values():h.sort(key=lambda b:b.date)
weekends=set(a.load(R/'calendar.json')['week_ends']);examples=[]
for symbol,date,policy in [('002006.SZ','20251118','balance_fallback'),('603098.SH','20260325','area_fallback'),('000762.SZ','20260506','area_fallback')]:
 plans=[p for p in a.load(R/(policy+'-plans.json')) if p['symbol']==symbol and p['date']==date]
 plans.sort(key=lambda p:p['candidate_rank']);start=min(p['ihs_left_date'] for p in plans)
 fig,axes=a.plt.subplots(len(plans),1,figsize=(14,4*len(plans)),sharex=True,sharey=True)
 for ax,p in zip(axes,plans):
  pid=p['setup_id'];key=hashlib.sha256((a.canonical(pid)+'|'+date).encode()).hexdigest()[:10]
  record=dict(plan=p,signal=date,symbol=symbol,family='IHS',setup_id=pid,chart_id=key)
  a.shape(ax,record,hist[symbol],weekends,start_date=start)
  ax.set_title(f"{symbol} | signal {date} | rank {p['candidate_rank']} | R {p['ihs_right_date']} | stop {p['stop']:.2f} | target {p['target']:.2f}")
 fig.tight_layout();path=f'paired/rejected-{symbol}-{date}.png';fig.savefig(O/path,dpi=110);a.plt.close(fig)
 examples.append(dict(symbol=symbol,signal=date,policy=policy,image=path,plans=plans))
(O/'rejected-candidate-examples.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2),encoding='utf-8')
rows=a.rows(O/'trade-audit.csv');base={(r['symbol'],r['signal']):r for r in rows if r['policy']=='baseline'};comparison={}
for policy in a.POLICIES:
 current={(r['symbol'],r['signal']):r for r in rows if r['policy']==policy}
 added=current.keys()-base.keys();removed=base.keys()-current.keys();shared=current.keys()&base.keys()
 changed=[k for k in shared if base[k]['canonical']!=current[k]['canonical']]
 comparison[policy]=dict(added=[current[k] for k in sorted(added)],removed=[base[k] for k in sorted(removed)],
  redrawn=[dict(symbol=k[0],signal=k[1],baseline_chart=base[k]['chart_id'],new_chart=current[k]['chart_id'],pnl_delta=float(current[k]['pnl'])-float(base[k]['pnl'])) for k in sorted(changed)],
  added_pnl=sum(float(current[k]['pnl']) for k in added),removed_pnl=sum(float(base[k]['pnl']) for k in removed),
  redrawn_pnl_delta=sum(float(current[k]['pnl'])-float(base[k]['pnl']) for k in changed),
  other_pnl_delta=sum(float(current[k]['pnl'])-float(base[k]['pnl']) for k in shared if k not in changed))
(R/'matched-trade-attribution.json').write_text(json.dumps(comparison,ensure_ascii=False,indent=2),encoding='utf-8')
print('SUPPLEMENT COMPLETE')
