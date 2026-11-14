"""Pre-specified descriptive key-line event research; no execution rule changes."""
import csv,json,math,hashlib,statistics,shutil,random
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];B=ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v3-retest';O=ROOT/'audits/20261025-ihs-keyline-events'
H=[1,3,5,10,20]
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def save(p,rs):
 if not rs:return
 keys=list(dict.fromkeys(k for r in rs for k in r))
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rs)
def mean(x):return statistics.mean(x) if x else None
def forward(bs,i,line,peak,h,calindex):
 if i+h>=len(bs):return None
 future=bs[i+1:i+h+1]
 if calindex[future[-1]['date']]-calindex[bs[i]['date']]!=h:return None
 c=bs[i]['close'];reclaim=next((j+1 for j,b in enumerate(future) if b['close']>=line),None);newhigh=next((j+1 for j,b in enumerate(future) if b['close']>peak),None)
 return dict(ret=future[-1]['close']/c-1,down=min(b['low'] for b in future)/c-1,up=max(b['high'] for b in future)/c-1,reclaim=reclaim is not None,reclaim_days=reclaim,newhigh=newhigh is not None,newhigh_days=newhigh)
def main():
 O.mkdir(parents=True,exist_ok=True)
 protocol=dict(cohort='all708 frozen v3 signal plans, not just executed14; no post20260930 data',roles=['neckline','retest_low','right_shoulder','head','higher_low'],monitor='next session after signal through60 exchange sessions; higher lows confirmed left2/right2, active next session',events='first wick-only breach (low<line close>=line); first close breach; first subsequent close reclaim after first close breach; one per line/type',higher_low='strict 5bar pivot, post-signal, higher than immediately prior confirmed pivot (initial reference right shoulder); no ATR stop buffer',horizons=H,outcomes='from event close, next exchange sessions only; exclude horizons crossing suspension/missingbars; adjusted prices; raw price prediction not executable PnL',overlap='same symbol role type date deduplicated; same symbol/date other roles marked within0.1ATR; no pooling across roles; cluster bootstrap by symbol',controls='prior-close above line; low in [line,line+0.5ATR]; no breach today; all causal features from prior close; same role, prior dates within120 calendar days, different symbol, age within20 sessions, volatility ratio<=2, prior20d trend difference<=10pp, prior line distance difference<=1ATR, prior market proxy difference<=3pp; controls not previously close-broken; greedy nearest match 1:1 without replacement per role/type',feature_distance='abs(market)/0.03+abs(age)/20+abs(trend)/0.1+abs(log volatility ratio)/log2+abs(line distance ATR)',bootstrap='symbol clusters, seed20261025,500 replicates, pointwise95% intervals; exploratory not causal or multiple-testing adjusted',holdout='20261102-20271029 untouched; no parameter search; production unchanged',limitations='frozen strategy selected cohort; line roles confounded with distance and structural scale; market proxy is prior20d median of583 signal-selected stocks, not official index; selection bias remains')
 dump(O/'protocol.json',protocol);shutil.copy2(__file__,O/Path(__file__).name)
 plans=json.loads((B/'plans.json').read_text());calendar=json.loads((B/'calendar.json').read_text())['open_dates'];ci={d:i for i,d in enumerate(calendar)};needed={p['symbol'] for p in plans};by=defaultdict(list)
 with (B/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   if r['symbol'] in needed and r['date']<='20260930':
    factor=float(r['factor']);by[r['symbol']].append(dict(date=r['date'],**{k:float(r[k])*factor for k in ['open','high','low','close']}))
 print('LOADED',len(plans),len(by),flush=True)
 # All transformations are causal; price*factor is an invariant economic scale.
 for bs in by.values():
  bs.sort(key=lambda b:b['date'])
  for i,b in enumerate(bs):
   trs=[max(bs[j]['high']-bs[j]['low'],abs(bs[j]['high']-bs[j-1]['close']),abs(bs[j]['low']-bs[j-1]['close'])) for j in range(max(1,i-14),i)]
   b['atr']=mean(trs) if len(trs)==14 else None
 market=defaultdict(list)
 for bs in by.values():
  for i in range(21,len(bs)):
   market[bs[i]['date']].append(bs[i-1]['close']/bs[i-21]['close']-1)
 market={d:statistics.median(v) for d,v in market.items()}
 events=[];controls=[];linecount=0
 for p in plans:
  bs=by[p['symbol']];ix={b['date']:i for i,b in enumerate(bs)};start=ix[p['date']];end=min(len(bs)-1,start+80);lines=[];factor=float(p['factor'])
  for role,key,formed in [('neckline','ihs_neckline',p['ihs_peak2_date']),('retest_low','ihs_retest_low',p['ihs_retest_date']),('right_shoulder','ihs_right_low',p['ihs_right_date']),('head','ihs_floor',p['ihs_head_date'])]:
   lines.append(dict(role=role,price=p[key]*factor,formed=formed,confirmed=p['date'],active=start+1,seen=set(),broken=False))
  prevpivot=p['ihs_right_low']*factor
  for i in range(start+1,end+1):
   b=bs[i]
   if ci[b['date']]-ci[p['date']]>60:break
   # A pivot confirmed yesterday becomes usable today; never uses current bar to form its line.
   t=i-3
   if t>start and t>=2 and all(bs[t]['low']<bs[j]['low'] for j in range(t-2,t+3) if j!=t):
    price=bs[t]['low']
    if price>prevpivot:lines.append(dict(role='higher_low',price=price,formed=bs[t]['date'],confirmed=bs[t+2]['date'],active=i,seen=set(),broken=False))
    prevpivot=price
   atr=b['atr']
   if not atr or i<21:continue
   for line in lines:
    if i<line['active']:continue
    price=line['price'];prev=bs[i-1]['close'];kind=None
    if b['close']<price and prev>=price and 'close_break' not in line['seen']:kind='close_break';line['broken']=True
    elif b['low']<price<=b['close'] and prev>=price and 'wick_only' not in line['seen']:kind='wick_only'
    elif line['broken'] and prev<price<=b['close'] and 'reclaim' not in line['seen']:kind='reclaim'
    control=not line['broken'] and prev>=price and price<=b['low']<=price+.5*atr
    if not kind and not control:continue
    record=dict(symbol=p['symbol'],setup_id=p['setup_id'],signal_date=p['date'],date=b['date'],role=line['role'],kind=kind or 'near_hold',line=price,formed=line['formed'],confirmed=line['confirmed'],active=bs[line['active']]['date'],structural_span=ci[b['date']]-ci.get(line['formed'],ci[p['date']]),prior_market=market[b['date']],age=ci[b['date']]-ci[p['date']],prior_trend=prev/bs[i-21]['close']-1,prior_vol=atr/prev,prior_distance=(prev-price)/atr,coincident_roles=';'.join(sorted({x['role'] for x in lines if x['role']!=line['role'] and abs(x['price']-price)<=.1*atr})))
    assert record['confirmed']<record['date']
    peak=max(x['high'] for x in bs[start:i+1])
    for h in H:
     outcome=forward(bs,i,price,peak,h,ci)
     if outcome:
      for k,v in outcome.items():record[f'{k}_{h}']=v
    if kind:line['seen'].add(kind);events.append(record)
    elif control:controls.append(record)
  linecount+=len(lines)
 def dedup(rs):
  seen=set();out=[]
  for r in sorted(rs,key=lambda r:(r['date'],r['symbol'],r['signal_date'],r['formed'])):
   key=tuple(r[k] for k in ['symbol','role','kind','date'])
   if key not in seen:seen.add(key);out.append(r)
  return out
 before=len(events);events=dedup(events);controls=dedup(controls)
 save(O/'events.csv',events);save(O/'controls.csv',controls)
 print('EVENTS',len(events),'CONTROLS',len(controls),flush=True)
 # Matching uses no outcomes. Different dates/symbols make controls imperfect; disclose this.
 from datetime import datetime
 from functools import lru_cache
 @lru_cache(None)
 def day(d):return datetime.strptime(d,'%Y%m%d').toordinal()
 groups=defaultdict(list)
 for c in controls:groups[c['role']].append(c)
 paired=[];used=defaultdict(set)
 for e in events:
  candidates=[];key=(e['role'],e['kind'])
  for j,c in enumerate(groups[e['role']]):
   if j in used[key] or c['symbol']==e['symbol'] or not 0<=day(e['date'])-day(c['date'])<=120:continue
   age=abs(c['age']-e['age']);trend=abs(c['prior_trend']-e['prior_trend']);vol=abs(math.log(c['prior_vol']/e['prior_vol']));dist=abs(c['prior_distance']-e['prior_distance'])
   marketgap=abs(c['prior_market']-e['prior_market'])
   if marketgap>.03 or age>20 or trend>.1 or vol>math.log(2) or dist>1:continue
   candidates.append((marketgap/.03+age/20+trend/.1+vol/math.log(2)+dist,j,c))
  if not candidates:continue
  score,j,c=min(candidates,key=lambda x:(x[0],x[2]['date'],x[2]['symbol']));used[key].add(j)
  r=dict(symbol=e['symbol'],date=e['date'],role=e['role'],kind=e['kind'],control_symbol=c['symbol'],control_date=c['date'],score=score,event_trend=e['prior_trend'],control_trend=c['prior_trend'],event_vol=e['prior_vol'],control_vol=c['prior_vol'],event_age=e['age'],control_age=c['age'],event_distance=e['prior_distance'],control_distance=c['prior_distance'],event_market=e['prior_market'],control_market=c['prior_market'])
  for h in H:
   if f'ret_{h}' in e and f'ret_{h}' in c:
    for k in ['ret','down','up','reclaim','newhigh']:
     r[f'event_{k}_{h}']=e[f'{k}_{h}'];r[f'control_{k}_{h}']=c[f'{k}_{h}'];r[f'delta_{k}_{h}']=e[f'{k}_{h}']-c[f'{k}_{h}']
  paired.append(r)
 save(O/'matched-pairs.csv',paired)
 result=[];rng=random.Random(20261025)
 for role in protocol['roles']:
  for kind in ['wick_only','close_break','reclaim']:
   es=[e for e in events if e['role']==role and e['kind']==kind];ps=[r for r in paired if r['role']==role and r['kind']==kind]
   for h in H:
    valid=[e for e in es if f'ret_{h}' in e];pairs=[r for r in ps if f'delta_ret_{h}' in r];clusters=defaultdict(list)
    for r in pairs:clusters[r['symbol']].append(r[f'delta_ret_{h}'])
    boot=[];syms=list(clusters)
    if len(syms)>=5:
     for _ in range(500):
      sample=[v for s in rng.choices(syms,k=len(syms)) for v in clusters[s]];boot.append(mean(sample))
     boot.sort()
    r=dict(role=role,kind=kind,horizon=h,events=len(es),complete=len(valid),symbols=len({e['symbol'] for e in valid}),matched=len(pairs),matched_symbols=len(clusters),mean_return=mean([e[f'ret_{h}'] for e in valid]),mean_down=mean([e[f'down_{h}'] for e in valid]),mean_up=mean([e[f'up_{h}'] for e in valid]),reclaim_rate=mean([e[f'reclaim_{h}'] for e in valid]),newhigh_rate=mean([e[f'newhigh_{h}'] for e in valid]),median_reclaim_days=statistics.median([e[f'reclaim_days_{h}'] for e in valid if e[f'reclaim_days_{h}'] is not None]) if any(e[f'reclaim_days_{h}'] is not None for e in valid) else None,delta_return=mean([r[f'delta_ret_{h}'] for r in pairs]),ci_low=boot[12] if boot else None,ci_high=boot[487] if boot else None,mean_structural_span=mean([e['structural_span'] for e in valid]),mean_prior_distance_ATR=mean([e['prior_distance'] for e in valid]))
    result.append(r)
 save(O/'summary.csv',result);dump(O/'summary.json',result)
 diff=[str(p) for p in (B/'source/src').rglob('*.py') if p.read_bytes()!=(ROOT/'src'/p.relative_to(B/'source/src')).read_bytes()];assert not diff
 dump(O/'verification.json',dict(plans=len(plans),symbols=len(needed),lines=linecount,events_before_dedup=before,events=len(events),controls=len(controls),matched_pairs=len(paired),production_unchanged=True,holdout_accessed=False,all_lines_confirmed_before_event=True,input_plans_sha256=hashlib.sha256((B/'plans.json').read_bytes()).hexdigest(),script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
 print('COMPLETE',len(paired),flush=True)
if __name__=='__main__':main()
