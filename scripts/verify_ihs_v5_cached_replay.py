"""Compare ordinary and frozen-signal engine replay on deterministic trade samples."""
import copy,csv,gzip,json,shutil,sys
from collections import defaultdict
from pathlib import Path
OUT=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(OUT/'source/src'))
from trading_system.domain import Bar,Intent
from trading_system.engine import Backtest
from trading_system.strategies import build_strategies
from trading_system.universe import MainboardUniverse
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def main():
 cfg=load(OUT/'config.json');plan=load(OUT/'evaluation-plan.json');cal=load(OUT/'calendar.json');ud=load(OUT/'universe.json')
 with (OUT/'trades.csv').open(encoding='utf-8-sig',newline='') as f:trades=list(csv.DictReader(f))
 with (OUT/'entry_audit.csv').open(encoding='utf-8-sig',newline='') as f:audits=list(csv.DictReader(f))
 # Selection exercises early entries, an eventual winner, and a position still open.
 symbols={a['symbol'] for a in [a for a in audits if a['execution_reason']=='filled'][:2]}
 symbols.update(t['symbol'] for t in trades if float(t['pnl'])>0)
 symbols.update(p['symbol'] for p in load(OUT/'summary.json')['positions'][:1])
 bars=[];buckets=defaultdict(list)
 with (OUT/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   if r['symbol'] in symbols:bars.append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
 for symbol in sorted(symbols):
  with gzip.open(OUT/'signal-events'/(symbol+'.jsonl.gz'),'rt',encoding='utf-8') as f:
   for line in f:
    e=json.loads(line)
    i=Intent(e['strategy'],symbol,e['date'],e['trigger'],e['stop'],e['target'],e['setup_id'],'inverse_head_shoulders',
       {k:v for k,v in e.items() if k not in ('date','symbol','strategy','setup_id','event','decision','trigger','stop','target')})
    buckets[(symbol,e['date'])].append((i,e))
 bars.sort(key=lambda b:(b.date,b.symbol))
 ordinary=build_strategies(cfg['strategies'])[0];cached=build_strategies(cfg['strategies'])[0]
 def on_close(history,weekends):
  b=history[-1];items=buckets.get((b.symbol,b.date),[])
  return [copy.deepcopy(i) for i,e in items],[copy.deepcopy(e) for i,e in items]
 cached.on_close=on_close
 def run(s):return Backtest(copy.deepcopy(cfg),[s]).run(bars,cal['open_dates'],set(cal['week_ends']),evaluation_start=plan['evaluation_start'],evaluation_end=plan['evaluation_end'],universe=MainboardUniverse(ud['stocks'],ud['st_by_date']))
 a=run(ordinary);b=run(cached)
 for key in ('curve','orders','trades','entry_audits','events','warmup_events'):
  assert getattr(a,key)==getattr(b,key),key
 assert a.summary()==b.summary()
 result=dict(symbols=sorted(symbols),ordinary_recomputed=True,frozen_replay_equal=True,
  equal_outputs=['all daily equity','orders','trades','entry audits','events','warmup events','summary'],
  bars=len(bars),closed_trades=len(a.trades),filled_buys=a.summary()['filled_buys'])
 (OUT/'cached-replay-equivalence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 shutil.copy2(__file__,OUT/'source/verify_ihs_v5_cached_replay.py')
 print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
