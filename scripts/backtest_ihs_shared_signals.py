"""Shared-account replay of unchanged causal IHS signals with a frozen exit implementation."""
import argparse,ast,copy,csv,gzip,hashlib,json,os,shutil,sys,time
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def method(p,name):
 tree=ast.parse(p.read_text(encoding='utf-8'))
 return ast.dump(next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name),include_attributes=False)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--config',required=True);ap.add_argument('--output',required=True)
 ap.add_argument('--scan',default=str(ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v5-breakout-trend'))
 a=ap.parse_args();base,out=Path(a.scan).resolve(),Path(a.output).resolve();cfg=load(Path(a.config));old=load(base/'config.json')
 spec=cfg['strategies'][0];assert len(cfg['strategies'])==1
 assert spec['type'] in ('confirmed_support_ihs','pressure_support_ihs')
 assert {k:v for k,v in cfg.items() if k!='strategies'}=={k:v for k,v in old.items() if k!='strategies'}
 assert {k:v for k,v in spec['params'].items() if k!='pressure_breakout_atr'}==old['strategies'][0]['params']
 src=ROOT/'src/trading_system';frozen=base/'source/src/trading_system'
 for name in ('candidate_layouts','on_close'):
  assert method(src/'strategies/breakout_trend_ihs.py',name)==method(frozen/'strategies/breakout_trend_ihs.py',name)
 for rel in ('engine.py','risk.py','ihs_geometry.py','structure.py','strategies/inverse_head_shoulders.py','strategies/enclosing_inverse_head_shoulders.py'):
  assert (src/rel).read_bytes()==(frozen/rel).read_bytes(),rel
 out.mkdir();shutil.copytree(ROOT/'src',out/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
 shutil.copy2(__file__,out/'source'/Path(__file__).name);shutil.copy2(ROOT/'runs/ihs-v7-tests.log',out/'tests.log')
 for f in ('calendar.json','universe.json','stocks.csv','coverage.csv','signal-counts.json'):shutil.copy2(base/f,out/f)
 os.link(base/'bars.csv',out/'bars.csv');dump(out/'config.json',cfg)
 manifest=load(base/'manifest.json');assert sha(out/'bars.csv')==manifest['bars_sha256']
 plan=dict(source_scan=str(base),evaluation_start=manifest['evaluation_start'],evaluation_end=manifest['evaluation_end'],
  rule_version=spec['id'],bars_sha256=manifest['bars_sha256'],config_sha256=sha(out/'config.json'),universe_sha256=sha(out/'universe.json'),
  entry_params_equal_to_v5=True,entry_detector_methods_equal_to_v5=True,engine_and_risk_equal_to_v5=True,
  method='reuse full causal population signal scan; rerun all account eligibility, sizing, actual fills and new holding logic',
  parameters_changed_after_results=False,holdout_accessed=False,initial_position_policy='flat at evaluation start',
  limitations=['previously studied historical sample','daily OHLC conservative initial-stop priority','synthetic factor share adjustment'])
 dump(out/'evaluation-plan.json',plan)
 sys.path.insert(0,str(out/'source/src'))
 from trading_system.domain import Bar,Intent
 from trading_system.engine import Backtest
 from trading_system.strategies import build_strategies
 from trading_system.universe import MainboardUniverse
 from trading_system.data import save_csv
 oldid=old['strategies'][0]['id'];newid=spec['id']
 def alias(pid):
  assert pid.startswith(oldid+':');return newid+pid[len(oldid):]
 plans=load(base/'plans.json');aliases={alias(p['setup_id']):p['setup_id'] for p in plans}
 plans=[dict(p,setup_id=alias(p['setup_id'])) for p in plans];dump(out/'plans.json',plans);dump(out/'signal-aliases.json',aliases)
 symbols={p['symbol'] for p in plans};buckets=defaultdict(list);seen={};started=time.monotonic()
 for symbol in sorted(symbols):
  with gzip.open(base/'signal-events'/(symbol+'.jsonl.gz'),'rt',encoding='utf-8') as f:
   for line in f:
    event=json.loads(line);event.update(strategy=newid,setup_id=alias(event['setup_id']))
    intent=Intent(newid,symbol,event['date'],event['trigger'],event['stop'],event['target'],event['setup_id'],'inverse_head_shoulders',
     {k:v for k,v in event.items() if k not in ('strategy','symbol','date','setup_id','event','decision','trigger','stop','target')})
    buckets[symbol,event['date']].append((intent,event))
    if plan['evaluation_start']<=event['date']<=plan['evaluation_end']:seen[event['setup_id']]=(event['date'],event['trigger'],event['stop'],event['target'])
 assert seen=={p['setup_id']:(p['date'],p['trigger'],p['stop'],p['target']) for p in plans}
 print(json.dumps(dict(status='loading',output=str(out),plans=len(plans))),flush=True)
 bars=[]
 with (out/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   if r['symbol'] in symbols:bars.append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
 bars.sort(key=lambda b:(b.date,b.symbol));cal=load(out/'calendar.json');ud=load(out/'universe.json');s=build_strategies(cfg['strategies'])[0]
 def on_close(history,weekends):
  b=history[-1];items=buckets.get((b.symbol,b.date),[])
  return [copy.deepcopy(i) for i,e in items],[copy.deepcopy(e) for i,e in items]
 s.on_close=on_close
 def progress(state):
  if state['session']%100==0:
   state=dict(state,status='account_replay',elapsed_seconds=round(time.monotonic()-started));dump(out/'status.json',state);print(json.dumps(state),flush=True)
 e=Backtest(copy.deepcopy(cfg),[s]).run(bars,cal['open_dates'],set(cal['week_ends']),evaluation_start=plan['evaluation_start'],evaluation_end=plan['evaluation_end'],universe=MainboardUniverse(ud['stocks'],ud['st_by_date']),progress=progress)
 assert {v['setup_id']:(v['date'],v['trigger'],v['stop'],v['target']) for v in e.events if v['event']=='entry_intent'}==seen
 for name,records in (('decisions',e.events),('warmup_decisions',e.warmup_events),('orders',e.orders),('trades',e.trades),('entry_audit',e.entry_audits),('equity',e.curve)):save_csv(out/(name+'.csv'),records)
 summary=e.summary();summary.update(signal_counts=load(out/'signal-counts.json')['evaluation'],signal_stocks=len(symbols),
  rejection_counts=dict(Counter(v.get('reason') for v in e.events if v['event'] in ('plan_rejected','entry_rejected'))),
  risk_reasons=dict(Counter(v.get('risk_reason',v.get('execution_reason')) for v in e.entry_audits)))
 dump(out/'summary.json',summary)
 h=hashlib.sha256()
 for p in sorted((out/'source/src').rglob('*.py')):h.update(str(p.relative_to(out/'source/src')).encode());h.update(p.read_bytes())
 dump(out/'manifest.json',dict(plan,stocks=3214,bar_count=2856672,sessions=len(e.curve),code_sha256=h.hexdigest()))
 dump(out/'account-verification.json',dict(signal_cache_match=True,candidates=len(plans),signal_stocks=len(symbols),engine_rerun=True,fixed_entry_cohort=False))
 dump(out/'status.json',dict(status='complete',plans=len(plans),buys=summary['filled_buys']))
 print(json.dumps(dict(status='complete',output=str(out),summary=summary)),flush=True)
if __name__=='__main__':main()
