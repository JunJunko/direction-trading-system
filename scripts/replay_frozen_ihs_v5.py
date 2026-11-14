"""Replay a completed causal v5 population scan without repeating shape search."""
import copy,csv,gzip,hashlib,html,json,shutil,sys,time
from collections import Counter,defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(sys.argv[1]).resolve()
# Use the implementation frozen before scanning, including the trading engine.
sys.path.insert(0,str(OUT/'source/src'))
from trading_system.domain import Bar,Intent
from trading_system.engine import Backtest
from trading_system.strategies import build_strategies
from trading_system.universe import MainboardUniverse
from trading_system.data import save_csv
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
 cfg=load(OUT/'config.json');plan=load(OUT/'evaluation-plan.json');plans=load(OUT/'plans.json')
 counts=load(OUT/'signal-counts.json');cal=load(OUT/'calendar.json');ud=load(OUT/'universe.json')
 symbols={p['symbol'] for p in plans};buckets=defaultdict(list)
 seen={};warm_events=0;start=time.monotonic()
 assert len(list((OUT/'signal-events').glob('*.gz')))==3214
 for symbol in sorted(symbols):
  with gzip.open(OUT/'signal-events'/(symbol+'.jsonl.gz'),'rt',encoding='utf-8') as f:
   for line in f:
    e=json.loads(line);assert e['event']=='entry_intent'
    intent=Intent(e['strategy'],symbol,e['date'],e['trigger'],e['stop'],e['target'],e['setup_id'],'inverse_head_shoulders',
        {k:v for k,v in e.items() if k not in ('date','symbol','strategy','setup_id','event','decision','trigger','stop','target')})
    buckets[(symbol,e['date'])].append((intent,e))
    if plan['evaluation_start']<=e['date']<=plan['evaluation_end']:
     seen[e['setup_id']]=(e['date'],e['trigger'],e['stop'],e['target'])
    else:warm_events+=1
 assert seen=={p['setup_id']:(p['date'],p['trigger'],p['stop'],p['target']) for p in plans}
 bars=[]
 with (OUT/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   if r['symbol'] in symbols:
    bars.append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
 bars.sort(key=lambda b:(b.date,b.symbol))
 s=build_strategies(cfg['strategies'])[0]
 def frozen_on_close(history,weekends):
  b=history[-1];items=buckets.get((b.symbol,b.date),[])
  # Engine visits each stock close once; no future-date event enters this call.
  return [copy.deepcopy(i) for i,e in items],[copy.deepcopy(e) for i,e in items]
 s.on_close=frozen_on_close
 def progress(state):
  if state['session']%100==0:
   state=dict(state,status='frozen_signal_account_replay',elapsed_seconds=round(time.monotonic()-start))
   dump(OUT/'status.json',state);print(json.dumps(state),flush=True)
 engine=Backtest(copy.deepcopy(cfg),[s]).run(bars,cal['open_dates'],set(cal['week_ends']),
   evaluation_start=plan['evaluation_start'],evaluation_end=plan['evaluation_end'],
   universe=MainboardUniverse(ud['stocks'],ud['st_by_date']),progress=progress)
 actual={e['setup_id']:(e['date'],e['trigger'],e['stop'],e['target']) for e in engine.events if e['event']=='entry_intent'}
 assert actual==seen
 for name,records in (('decisions',engine.events),('warmup_decisions',engine.warmup_events),('orders',engine.orders),
                     ('trades',engine.trades),('entry_audit',engine.entry_audits),('equity',engine.curve)):
  save_csv(OUT/(name+'.csv'),records)
 summary=engine.summary();summary.update(signal_counts=counts['evaluation'],signal_stocks=len(symbols),
  rejection_counts=dict(Counter(e.get('reason') for e in engine.events if e['event'] in ('plan_rejected','entry_rejected'))),
  risk_reasons=dict(Counter(a.get('risk_reason',a.get('execution_reason')) for a in engine.entry_audits)))
 dump(OUT/'summary.json',summary)
 plan['method']='scan every input stock causally; replay frozen dated signals in the original shared-account engine; recompute actual execution risk and live weekly exits'
 dump(OUT/'evaluation-plan.json',plan)
 digest=hashlib.sha256()
 for p in sorted((OUT/'source/src').rglob('*.py')):digest.update(str(p.relative_to(OUT/'source/src')).encode());digest.update(p.read_bytes())
 dates=[d for d in cal['open_dates'] if plan['evaluation_start']<=d<=plan['evaluation_end']]
 dump(OUT/'manifest.json',dict(plan,stocks=3214,bar_count=2856672,sessions=len(engine.curve),
  first_session=dates[0],last_session=dates[-1],code_sha256=digest.hexdigest()))
 dump(OUT/'account-verification.json',dict(all_population_scanned=True,scan_signal_cache_match=True,
  signal_id_date_price_match=True,unique_plans=len(plans),signal_stocks=len(symbols),
  engine_and_live_exit_implementation='frozen source/src',historical_search_not_repeated=True))
 shutil.copy2(__file__,OUT/'source/replay_frozen_ihs_v5.py')
 dump(OUT/'status.json',dict(status='complete',stocks=3214,plans=len(plans)))
 print(json.dumps(dict(status='complete',summary=summary)),flush=True)
if __name__=='__main__':main()
