"""Qualified W + inverse H&S, independent and shared-account v7 exit evaluation."""
import copy,csv,hashlib,json,os,shutil,sys,time
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/20261025-w-ihs-v7-shared-account'
WSCAN=ROOT/'runs/20261025-mainboard-qualified-w-v519-signals'
ISCAN=ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v5-breakout-trend'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 assert load(WSCAN/'status.json')['status']=='complete'
 assert load(WSCAN/'verification.json')['cohort_99_entry_plans_exact']
 out=OUT;out.mkdir();shutil.copytree(ROOT/'src',out/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
 shutil.copy2(__file__,out/'source'/Path(__file__).name);shutil.copy2(ROOT/'runs/w-ihs-v7-tests.log',out/'tests.log')
 sys.path.insert(0,str(out/'source/src'))
 from trading_system.domain import Bar,Intent
 from trading_system.engine import Backtest
 from trading_system.data import save_csv
 from trading_system.strategies import build_strategies
 from trading_system.universe import MainboardUniverse
 wold=load(WSCAN/'config.json');iold=load(ISCAN/'config.json')
 wnew=load(ROOT/'configs/experiments/double_bottom_v7_pressure_support.json')
 inew=load(ROOT/'configs/experiments/inverse_head_shoulders_v7_pressure_support.json')
 for c in (wold,iold,wnew,inew):assert {k:v for k,v in c.items() if k!='strategies'}=={k:v for k,v in wold.items() if k!='strategies'}
 assert {k:v for k,v in wnew['strategies'][0]['params'].items() if k!='pressure_breakout_atr'}==wold['strategies'][0]['params']
 assert {k:v for k,v in inew['strategies'][0]['params'].items() if k!='pressure_breakout_atr'}==iold['strategies'][0]['params']
 assert sha(ISCAN/'bars.csv')==load(WSCAN/'manifest.json')['bars_sha256']==load(ISCAN/'manifest.json')['bars_sha256']
 for name in ('calendar.json','universe.json','stocks.csv','coverage.csv'):shutil.copy2(ISCAN/name,out/name)
 os.link(ISCAN/'bars.csv',out/'bars.csv')
 plan=dict(evaluation_start='20251009',evaluation_end='20260930',source_W_scan=str(WSCAN),source_IHS_scan=str(ISCAN),
  W_full_population=3214,IHS_full_population=3214,bars_sha256=load(ISCAN/'manifest.json')['bars_sha256'],
  entry='qualified W v5.19 retest + IHS v5 breakout; brackets and all entry eligibility unchanged',
  W_entry_distance_cap='original W 2% local retest risk cap retained; IHS has no 2% cap',
  exit='shared v7 pressure-to-support manager, completed weekly left2/right2; daily close signal and next executable open',
  account='one 1M account, single portfolio risk budget and exposure limits; never sum separate accounts',
  signal_priority='W first then IHS, then symbol; fixed before results',same_symbol='one position only; later intent must pass current position check',
  causal_scan_reused=True,entry_quantity_and_cash_recomputed=True,holdout_accessed=False,parameter_tuning=False,
  limitations=['known development interval','daily OHLC conservative initial-stop priority','synthetic factor share convention'])
 dump(out/'evaluation-plan.json',plan)
 sources={'W':load(WSCAN/'plans.json'),'IHS':load(ISCAN/'plans.json')}
 symbols={p['symbol'] for ps in sources.values() for p in ps};print(json.dumps(dict(status='loading',W_signals=len(sources['W']),IHS_signals=len(sources['IHS']),signal_stocks=len(symbols))),flush=True)
 bars=[]
 with (out/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   if r['symbol'] in symbols:bars.append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
 bars.sort(key=lambda b:(b.date,b.symbol));cal=load(out/'calendar.json');ud=load(out/'universe.json');universe=MainboardUniverse(ud['stocks'],ud['st_by_date'])
 cohort=ROOT/'runs/20261024-qualified-w-cohort';cohort_symbols=set(load(cohort/'symbols.json'))
 scenarios=[('cohort_control',[('W',wold['strategies'][0])]),('baseline_w',[('W',wold['strategies'][0])]),
  ('candidate_w',[('W',wnew['strategies'][0])]),
  ('baseline_combined',[('W',wold['strategies'][0]),('IHS',iold['strategies'][0])]),
  ('candidate_combined',[('W',wnew['strategies'][0]),('IHS',inew['strategies'][0])])]
 summaries={}
 for label,items in scenarios:
  folder=out/label;folder.mkdir();cfg=copy.deepcopy(wold);cfg['strategies']=[copy.deepcopy(spec) for family,spec in items]
  dump(folder/'config.json',cfg);slist=build_strategies(cfg['strategies']);allplans=[];aliases={};families={}
  for s,(family,spec) in zip(slist,items):
   buckets=defaultdict(list)
   for p in sources[family]:
    if label=='cohort_control' and p['symbol'] not in cohort_symbols:continue
    original=p['setup_id'];pid=spec['id']+original[original.index(':'):]
    e={k:copy.deepcopy(v) for k,v in p.items() if k not in ('date','symbol','setup_id','trigger','stop','target')}
    if 'w_owner' in e:e['w_owner']=pid
    if spec['type'] in ('pressure_support_w','pressure_support_ihs'):e['target_exit_rule']='reference_only'
    intent=Intent(spec['id'],p['symbol'],p['date'],p['trigger'],p['stop'],p['target'],pid,'direct_w' if family=='W' else 'inverse_head_shoulders',e)
    event=dict(date=p['date'],symbol=p['symbol'],strategy=spec['id'],setup_id=pid,event='entry_intent',trigger=p['trigger'],stop=p['stop'],target=p['target'],**e)
    if family=='IHS':event['decision']='BUY_CANDIDATE'
    buckets[p['symbol'],p['date']].append((intent,event));allplans.append(dict(p,setup_id=pid,**({'w_owner':pid,'target_exit_rule':e['target_exit_rule']} if family=='W' else {})))
    aliases[pid]=original;families[spec['id']]=family
   def cached(history,weekends,book=buckets):
    b=history[-1];items=book.get((b.symbol,b.date),[])
    return [copy.deepcopy(i) for i,e in items],[copy.deepcopy(e) for i,e in items]
   s.on_close=cached
  dump(folder/'plans.json',allplans);dump(folder/'signal-aliases.json',aliases);dump(folder/'strategy-families.json',families)
  current_bars=[b for b in bars if b.symbol in cohort_symbols] if label=='cohort_control' else bars
  started=time.monotonic()
  def progress(state):
   if state['session']%200==0:print(json.dumps(dict(case=label,elapsed_seconds=round(time.monotonic()-started),**state)),flush=True)
  e=Backtest(cfg,slist).run(current_bars,cal['open_dates'],set(cal['week_ends']),evaluation_start='20251009',evaluation_end='20260930',universe=universe,progress=progress)
  emitted={v['setup_id']:(v['date'],v['trigger'],v['stop'],v['target']) for v in e.events if v['event']=='entry_intent'}
  assert emitted=={p['setup_id']:(p['date'],p['trigger'],p['stop'],p['target']) for p in allplans}
  for name,rs in (('decisions',e.events),('orders',e.orders),('trades',e.trades),('entry_audit',e.entry_audits),('equity',e.curve)):save_csv(folder/(name+'.csv'),rs)
  summary=e.summary();summary.update(entry_signals=len(allplans),signal_stocks=len({p['symbol'] for p in allplans}),exit_reasons=dict(Counter(t['reason'] for t in e.trades)),
   risk_reasons=dict(Counter(a.get('risk_reason',a.get('execution_reason')) for a in e.entry_audits)))
  dump(folder/'summary.json',summary);summaries[label]=summary
  if label=='cohort_control':
   oldtrades=rows(cohort/'candidate/trades.csv');oldcurve=rows(cohort/'candidate/equity.csv');assert len(oldtrades)==len(e.trades)==14
   for a,b in zip(oldtrades,e.trades):
    for k in ('strategy','symbol','entry_date','exit_date','reason','setup_id'):assert a[k]==b[k],k
    for k in ('entry','exit','quantity','pnl','realized_r'):assert abs(float(a[k])-b[k])<1e-7,k
   for a,b in zip(oldcurve,e.curve):
    assert a['date']==b['date']
    for k in ('cash','equity','drawdown'):assert abs(float(a[k])-b[k])<1e-7,k
   dump(folder/'verification.json',dict(original_14_trades_exact=True,original_241_cash_equity_drawdown_rows_exact=True))
  print(json.dumps(dict(status='case_complete',case=label,summary=summary)),flush=True)
 dump(out/'summaries.json',summaries)
 h=hashlib.sha256()
 for p in sorted((out/'source/src').rglob('*.py')):h.update(str(p.relative_to(out/'source/src')).encode());h.update(p.read_bytes())
 dump(out/'manifest.json',dict(plan,code_sha256=h.hexdigest(),bar_count=2856672,W_signals=len(sources['W']),IHS_signals=len(sources['IHS'])))
 dump(out/'status.json',dict(status='complete',cases=list(summaries)))
 print('COMPLETE',flush=True)
if __name__=='__main__':main()
