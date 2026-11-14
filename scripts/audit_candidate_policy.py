
"""Render filled setups and evaluate selection changes against the frozen baseline."""
import csv,hashlib,html,json,sys
from pathlib import Path
from collections import defaultdict,Counter
from dataclasses import replace
from statistics import median
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Bar
from trading_system.analysis import adjusted,weekly
from trading_system.ihs_geometry import neckline_at
from trading_system.main_trend import completed_weeks
from trading_system.confirmed_support_trend import confirmed_weekly_points
from trading_system.data import save_csv
RUN=ROOT/'runs/20261109-candidate-policy-full';OUT=RUN/'chart-audit'
POLICIES=['baseline','area_selected','balance_single','area_fallback','balance_fallback']
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def canonical(pid):return pid.split(':',1)[1]
def candles(ax,view):
 for i,b in enumerate(view):
  color='#c64f4f' if b.close>=b.open else '#168675'
  ax.vlines(i,b.low,b.high,color=color,lw=.6)
  ax.add_patch(Rectangle((i-.32,min(b.open,b.close)),.64,max(abs(b.open-b.close),.001),color=color))
 ticks=list(range(0,len(view),max(1,len(view)//7)))
 ax.set_xticks(ticks,[view[i].date for i in ticks],fontsize=7,rotation=20);ax.grid(alpha=.15)
def shape(ax,record,hist,weekends,start_date=None):
 e=record['plan'];pre=adjusted([b for b in hist if b.date<=record['signal']])
 if record['family']=='IHS':
  start=next(i for i,b in enumerate(pre) if b.date==(start_date or e['ihs_left_date']))
  view=pre[max(0,start-22):];ix={b.date:i for i,b in enumerate(view)}
  dates=[e[k] for k in ('ihs_left_date','ihs_peak1_date','ihs_head_date','ihs_peak2_date','ihs_right_date')]
  prices=[getattr(view[ix[d]],'low' if i%2==0 else 'high') for i,d in enumerate(dates)]
  candles(ax,view);ax.plot([ix[d] for d in dates],prices,'--',color='#2859aa',lw=1)
  for d,p,label in zip(dates,prices,['L','P1','H','P2','R']):
   ax.scatter(ix[d],p,s=16,color='#2859aa')
   ax.annotate(label+' '+d,(ix[d],p),xytext=(2,9),textcoords='offset points',fontsize=7)
  ax.plot(range(len(view)),[neckline_at(e,b.date) for b in view],color='#c58c21',label='Frozen neckline')
 else:
  view=weekly(pre,weekends);dates=canonical(record['setup_id']).split(':')[1:]
  start=next(i for i,b in enumerate(view) if b.date==dates[0]);view=view[max(0,start-15):]
  candles(ax,view)
  for d in dates:
   i=next(i for i,b in enumerate(view) if b.date==d)
   ax.scatter(i,view[i].low,s=20,color='#2859aa');ax.annotate(d,(i,view[i].low),fontsize=7)
 ax.set_title(f"{record['chart_id']} | {record['symbol']} | signal {record['signal']} | {record['family']}",fontsize=10)
 return pre
def main():
 OUT.mkdir(exist_ok=True);(OUT/'structures').mkdir(exist_ok=True);(OUT/'holdings').mkdir(exist_ok=True)
 assert load(RUN/'status.json')['status']=='complete'
 cal=load(RUN/'calendar.json');weekends=set(cal['week_ends'])
 records=[];cases={}
 for policy in POLICIES:
  folder=RUN/(policy+'_combined_cost1')
  fills=[a for a in rows(folder/'entry_audit.csv') if int(a.get('filled_quantity') or 0)>0]
  trades={t['setup_id']:t for t in rows(folder/'trades.csv')}
  plans={p['setup_id']:p for p in load(RUN/(policy+'-plans.json'))+load(RUN/'W-plans.json')}
  events=rows(folder/'decisions.csv');cases[policy]=(folder,events)
  for a in fills:
   pid=a['setup_id'];p=plans[pid]
   record=dict(policy=policy,setup_id=pid,canonical=canonical(pid),symbol=a['symbol'],signal=a['signal_date'],entry=a['date'],
    family='IHS' if p.get('ihs_head_date') else 'W',plan=p,fill=a,trade=trades.get(pid),
    chart_id=hashlib.sha256((canonical(pid)+'|'+a['signal_date']).encode()).hexdigest()[:10])
   records.append(record)
 symbols={r['symbol'] for r in records};hist=defaultdict(list)
 with (RUN/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for row in csv.DictReader(f):
   if row['symbol'] in symbols:hist[row['symbol']].append(Bar(row['symbol'],row['date'],**{k:float(row[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
 for h in hist.values():h.sort(key=lambda b:b.date)
 unique={r['chart_id']:r for r in records};basekeys={r['canonical'] for r in records if r['policy']=='baseline'}
 # Hash order, no performance ranking. Structure panels contain no PnL or arm label.
 for number,(key,r) in enumerate(sorted(unique.items()),1):
  fig,axes=plt.subplots(2,1,figsize=(14,8))
  pre=shape(axes[0],r,hist[r['symbol']],weekends);recent=pre[-65:];candles(axes[1],recent)
  if r['family']=='IHS':axes[1].plot(range(len(recent)),[neckline_at(r['plan'],b.date) for b in recent],color='#c58c21')
  axes[1].axhline(r['plan']['stop'],ls='--',color='#b94771',label='Signal stop')
  axes[1].set_title('Daily context ending at signal close | no later candles',fontsize=10)
  axes[1].legend(fontsize=8);fig.tight_layout();fig.savefig(OUT/'structures'/(key+'.png'),dpi=105);plt.close(fig)
  if number%20==0:print('STRUCTURES',number,len(unique),flush=True)
 unique_rows=list(sorted(unique.values(),key=lambda r:r['chart_id']))
 (OUT/'paired').mkdir(exist_ok=True);pairs=defaultdict(list);pair_index=[]
 for r in unique_rows:
  if r['family']=='IHS':pairs[r['symbol'],r['signal']].append(r)
 for (symbol,signal),items in pairs.items():
  if len(items)<2:continue
  start=min(r['plan']['ihs_left_date'] for r in items)
  fig,axes=plt.subplots(len(items),1,figsize=(14,4*len(items)),sharex=True,sharey=True)
  for ax,r in zip(axes,items):shape(ax,r,hist[symbol],weekends,start_date=start)
  path=f'paired/{symbol}-{signal}.png';fig.tight_layout();fig.savefig(OUT/path,dpi=110);plt.close(fig)
  pair_index.append(dict(symbol=symbol,signal=signal,chart_ids=[r['chart_id'] for r in items],image=path))
 (OUT/'paired/index.json').write_text(json.dumps(pair_index,indent=2),encoding='utf-8')
 for start in range(0,len(unique_rows),6):
  fig,axes=plt.subplots(3,2,figsize=(18,13))
  for ax,r in zip(axes.flat,unique_rows[start:start+6]):shape(ax,r,hist[r['symbol']],weekends)
  for ax in list(axes.flat)[len(unique_rows[start:start+6]):]:ax.axis('off')
  fig.tight_layout();fig.savefig(OUT/f'contact-{start//6+1:02d}.png',dpi=110);plt.close(fig)
 flat=[];exit_checks=0;support_checks=0;entry_checks=0
 for number,r in enumerate(records,1):
  a=r['fill'];p=r['plan'];t=r['trade'];h=hist[r['symbol']];by={b.date:b for b in h}
  end=t['exit_date'] if t else '20260930';ef=by[r['entry']].factor
  held=[b for b in h if r['entry']<=b.date<=end]
  view=[replace(b,open=b.open*b.factor/ef,high=b.high*b.factor/ef,low=b.low*b.factor/ef,close=b.close*b.factor/ef) for b in held]
  completed=[b for b in view if not t or b.date<end]
  fill=float(a['fill']);qty=float(a['filled_quantity']);fee=float(a['entry_fee']);risk=float(a['expected_loss'])
  sf=by[r['signal']].factor;eb=by[r['entry']]
  assert cal['open_dates'][cal['open_dates'].index(r['signal'])+1]==r['entry']
  expected_entry=(eb.open if p.get('entry_order')=='next_open' else max(eb.open,p['trigger']*sf/ef))*1.001
  assert abs(expected_entry-fill)<1e-7
  assert abs(float(a['stop'])-p['stop']*sf/ef)<1e-7
  assert abs(float(a['target'])-p['target']*sf/ef)<1e-7
  assert float(a['net_rr'])>3 and float(a['expected_upside'])>.05
  entry_checks+=1
  peak=max(b.close for b in completed)
  pnl=float(t['pnl']) if t else (view[-1].close-fill)*qty-fee
  peak_net=(peak-fill)*qty-fee-max(5,peak*qty*.0003)-peak*qty*.0005
  events=cases[r['policy']][1]
  ev=[e for e in events if e.get('symbol')==r['symbol'] and e.get('strategy')==a['strategy'] and r['entry']<=e['date']<=end]
  changes=[e for e in ev if e['event']=='main_protection_raised' and e.get('setup_id')==r['setup_id']]
  for e in changes:
   assert e['formed']<=e['confirmed']<=e['date']
   if e.get('old'):assert float(e['new'])>float(e['old'])
   weeks=completed_weeks([b for b in h if b.date<=e['date']],cal['open_dates'])
   points=confirmed_weekly_points(weeks);level=float(e['new'])
   if e['source']=='confirmed_weekly_low':
    assert any(q['kind']=='L' and q['date']==e['formed'] and q['confirmed']==e['date'] and q['start']>r['entry'] and abs(q['price']-level)<1e-7 for q in points)
   else:
    point=next(q for q in points if q['kind']=='H' and q['date']==e['formed'] and abs(q['price']-level)<1e-7)
    assert point['confirmed']<e['date']
    j=next(i for i,b in enumerate(h) if b.date==e['date']);tr=[]
    for i in range(max(1,j-14),j):
     b,z=h[i],h[i-1];tr.append(max(b.high*b.factor-b.low*b.factor,abs(b.high*b.factor-z.close*z.factor),abs(b.low*b.factor-z.close*z.factor)))
    assert len(tr)==14 and by[e['date']].close*by[e['date']].factor>level+.1*sum(tr)/14
   support_checks+=1
  if t:
   b=by[end]
   if t['reason']=='dynamic_support_daily_break':
    signal=next(e for e in ev if e['event']=='dynamic_support_daily_break' and e['setup_id']==r['setup_id'])
    assert signal['date']<end
    assert by[signal['date']].close*by[signal['date']].factor<float(signal['economic_protection'])
    earlier=[e for e in changes if e['date']<signal['date']]
    assert earlier and abs(float(earlier[-1]['new'])-float(signal['economic_protection']))<1e-7
    sellable=[z for z in h if z.date>signal['date'] and z.volume>0 and (not z.down_limit or z.open>z.down_limit+.00001)]
    assert end==sellable[0].date
    expected=max(b.down_limit,b.open*.999)
   else:
    stop=float(a['stop'])*ef/b.factor
    prior=[e for e in ev if e['event']=='stop_raised' and e['date']<end]
    if prior:stop=float(prior[-1]['new_stop'])*by[prior[-1]['date']].factor/b.factor
    if t['reason'].startswith('deferred_') or t['reason'] in ('blocked_structural_stop','t1_deferred_structural_stop'):
     breached=[x for x in held if x.date<end and x.low*x.factor<=float(a['stop'])*ef]
     assert breached
     expected=max(b.low,b.open*.999)
    else:
     assert b.low<=stop
     expected=max(b.low,min(b.open,stop)*.999)
   assert abs(expected-float(t['exit']))<1e-7
   exit_checks+=1
  balance=span=outer=None
  if r['family']=='IHS':
   ix={b.date:i for i,b in enumerate(h)}
   ds=[p[k] for k in ('ihs_left_date','ihs_peak1_date','ihs_head_date','ihs_peak2_date','ihs_right_date')]
   legs=[ix[y]-ix[x] for x,y in zip(ds,ds[1:])]
   balance=min(legs)/max(legs);span=sum(legs);outer=min(legs[0],legs[-1])
  row=dict(policy=r['policy'],chart_id=r['chart_id'],symbol=r['symbol'],setup_id=r['setup_id'],canonical=r['canonical'],family=r['family'],
   signal=r['signal'],entry=r['entry'],exit=end if t else '',pnl=pnl,closed=bool(t),reason=t['reason'] if t else 'open',
   peak_close_net_R=peak_net/risk,realized_R=pnl/risk,time_balance=balance,span=span,outer_min_sessions=outer,
   candidate_rank=p.get('candidate_rank',1),candidate_count=p.get('candidate_count',1),
   new_vs_baseline=r['canonical'] not in basekeys,stop_pct=1-float(a['stop'])/fill,target_upside=float(a['target'])/fill-1,
   entry_day_stop=view[0].low<=float(a['stop']),holding_sessions=len(view),support_raises=len(changes))
  flat.append(row)
  # Draw actual holding support/stop only from next session onward.
  fig,ax=plt.subplots(figsize=(12,4));candles(ax,view)
  ax.axhline(fill,color='#2859aa',label='Entry')
  active_stop=float(a['stop']);active_support=None;stops=[];supports=[]
  for b in held:
   stops.append(active_stop);supports.append(active_support)
   for e in ev:
    if e['date']!=b.date:continue
    if e['event']=='stop_raised':active_stop=float(e['new_stop'])*b.factor/ef
    if e in changes:active_support=float(e['new'])/ef
  ax.step(range(len(view)),stops,where='post',ls='--',color='#bc506d',label='Active stop')
  ax.step(range(len(view)),supports,where='post',color='#8b5bb1',label='Active support')
  if t:ax.scatter(len(view)-1,float(t['exit'])*by[end].factor/ef,color='black',s=24,label='Exit')
  ax.set_title(f"{r['policy']} | {r['symbol']} | {r['entry']} - {end} | PnL {pnl:+,.0f}")
  ax.legend(fontsize=8);fig.tight_layout();fig.savefig(OUT/'holdings'/(r['policy']+'-'+r['chart_id']+'.png'),dpi=100);plt.close(fig)
  if number%30==0:print('HOLDINGS',number,len(records),flush=True)
 save_csv(OUT/'trade-audit.csv',flat)
 stats={}
 for policy in POLICIES:
  subset=[r for r in flat if r['policy']==policy];ihs=[r for r in subset if r['family']=='IHS']
  keys={r['canonical'] for r in subset}
  loss=[r for r in subset if r['closed'] and r['pnl']<0]
  stats[policy]=dict(buys=len(subset),IHS=len(ihs),new=len(keys-basekeys),absent=len(basekeys-keys),
   median_balance=median(r['time_balance'] for r in ihs) if ihs else None,
   span_gt250=sum(r['span']>250 for r in ihs),leg_ratio_gt10=sum(r['time_balance']<.1 for r in ihs),
   outer_at_most2=sum(r['outer_min_sessions']<=2 for r in ihs),
   closed_losses=len(loss),loss_pnl=sum(r['pnl'] for r in loss),
   loss_never_1R=sum(r['peak_close_net_R']<1 for r in loss),
   new_closed_pnl=sum(r['pnl'] for r in subset if r['new_vs_baseline'] and r['closed']))
 (OUT/'summary.json').write_text(json.dumps(stats,indent=2),encoding='utf-8')
 (OUT/'verification.json').write_text(json.dumps(dict(distinct_charts=len(unique),trade_records=len(flat),entry_checks=entry_checks,exit_checks=exit_checks,support_timing_and_level_checks=support_checks),indent=2),encoding='utf-8')
 page='<meta charset="utf-8"><title>候选规则逐笔图审</title><style>body{font:16px/1.7 system-ui;max-width:1400px;margin:35px auto}img{width:100%}summary{padding:12px;background:#edf3f8;cursor:pointer}details{margin:10px 0}</style><h1>候选规则全量对照与逐笔K线</h1><p>结构图截止信号日，持仓图单独显示后续行情。时间平衡与跨度为诊断代理，不能直接等同于形态误判率。</p>'
 for policy in POLICIES:
  page+='<h2>'+policy+'</h2>'
  for r in flat:
   if r['policy']!=policy:continue
   page+=f"<details><summary>{r['symbol']} {r['entry']} {'新增' if r['new_vs_baseline'] else '基准已有'} ｜ {r['pnl']:+,.0f} ｜ {r['reason']}</summary><img loading='lazy' src='structures/{r['chart_id']}.png'><img loading='lazy' src='holdings/{policy}-{r['chart_id']}.png'></details>"
 (OUT/'charts.html').write_text(page,encoding='utf-8')
 print('AUDIT COMPLETE',json.dumps(stats),flush=True)
if __name__=='__main__':main()

