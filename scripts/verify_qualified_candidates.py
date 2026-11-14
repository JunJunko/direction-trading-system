"""Uncached native detector checks for a deterministic mixed-admission sample."""
import csv,sys,time
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Bar
from trading_system.strategies import build_strategies
from backtest_candidate_policy import load,dump,rows
RUN=ROOT/'runs/20261109-qualified-candidates-verified'
protocol=load(RUN/'protocol.json');q=rows(RUN/'quality_10_guard-qualification.csv')
by=defaultdict(set)
for r in q:
 if r['event']=='candidate_qualification':by[r['symbol']].add(r['shape_qualified'])
mixed=sorted(s for s,v in by.items() if v=={'True','False'});chosen=mixed[:3]+mixed[-3:]
hist=defaultdict(list)
with (RUN/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
 for r in csv.DictReader(f):
  if r['symbol'] in chosen:hist[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
checks=[]
for label in ['propagation_only','quality_10_guard']:
 expected=defaultdict(list)
 for p in load(RUN/(label+'-plans.json')):expected[p['symbol']].append(p)
 for symbol in chosen:
  s=build_strategies([protocol['configs'][label]['strategies'][0]])[0];history=[];actual=[];start=time.monotonic()
  for b in sorted(hist[symbol],key=lambda b:b.date):
   history.append(b);intents,_=s.on_close(history,set())
   if b.date>='20251009':actual.extend(dict(date=i.date,symbol=i.symbol,setup_id=i.setup_id,trigger=i.trigger,stop=i.stop,target=i.target,**i.evidence) for i in intents)
  assert actual==expected[symbol],(label,symbol)
  checks.append(dict(policy=label,symbol=symbol,signals=len(actual),ordinary_exact=True));print('VERIFIED',label,symbol,round(time.monotonic()-start,2),flush=True)
dump(RUN/'native-verification.json',checks)
