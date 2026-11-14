"""Independent ordinary on_close replay against shared-geometry population scan."""
import argparse,csv,json,sys,time
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Bar
from trading_system.strategies import build_strategies
import backtest_candidate_policy as runner

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--warmup-only',action='store_true');parser.add_argument('--shared-caches',action='store_true');parser.add_argument('--signal-days-only',action='store_true');parser.add_argument('--tail-only',action='store_true');args=parser.parse_args()
 run=runner.OUT;protocol=runner.load(run/'protocol.json');configs=protocol['configs']
 snapshots=[runner.load(p) for p in sorted((run/'stocks').glob('*.json'))]
 eligible=[s for s in snapshots if s['plans']['baseline']]
 chosen=eligible[:3]+eligible[-3:]
 if not args.warmup_only:
  changed=[]
  for s in snapshots:
   sig=lambda ps:{(p['date'],p['setup_id'].split(':',1)[1]) for p in ps}
   if sig(s['plans']['baseline'])!=sig(s['plans']['balance_fallback']):changed.append(s)
  chosen=changed[:3]+changed[-3:]
  if args.tail_only:chosen=changed[-3:]
 symbols={s['symbol'] for s in chosen};hist=defaultdict(list)
 with (run/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   if r['symbol'] in symbols:hist[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
 out=run/('signal-days-verification' if args.signal_days_only else ('shared-cache-verification' if args.shared_caches else ('warmup-verification' if args.warmup_only else 'ordinary-verification')));out.mkdir(exist_ok=True)
 if args.tail_only:out=run/'ordinary-tail-verification';out.mkdir(exist_ok=True)
 (out/'stocks').mkdir(exist_ok=True);(out/'candidate-events').mkdir(exist_ok=True)
 weekends=set(runner.load(run/'calendar.json')['week_ends']);checks=[]
 for s in chosen:
  symbol=s['symbol'];bars=sorted(hist[symbol],key=lambda b:b.date);started=time.monotonic()
  if args.warmup_only:
   signal_days=None
   if args.signal_days_only:
    signal_days=defaultdict(set)
    for p in runner.load(runner.DATA/'plans.json'):signal_days[p['symbol']].add(p['date'])
   runner.initialize(configs,weekends,str(out),True,args.shared_caches,signal_days)
   actual=runner.scan((symbol,bars))
   assert actual==s,symbol
   checks.append(dict(symbol=symbol,all_modes_exact=True))
  else:
   for label in ('balance_single','area_selected','area_fallback','balance_fallback'):
    strategy=build_strategies([configs[label]['strategies'][0]])[0];plans=[];history=[]
    for bar in bars:
     history.append(bar);intents,_=strategy.on_close(history,weekends)
     if bar.date>='20251009':plans.extend(dict(date=i.date,symbol=i.symbol,setup_id=i.setup_id,trigger=i.trigger,stop=i.stop,target=i.target,**i.evidence) for i in intents)
    assert plans==s['plans'][label],(symbol,label)
    checks.append(dict(symbol=symbol,policy=label,ordinary_exact=True,signals=len(plans)))
  print('VERIFIED',symbol,round(time.monotonic()-started,2),flush=True)
 runner.dump(out/'verification.json',checks)
 print('COMPLETE',len(checks),flush=True)
if __name__=='__main__':main()
