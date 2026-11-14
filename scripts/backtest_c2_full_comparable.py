"""Qualified W + inverse H&S, independent and shared-account v7 exit evaluation."""
import copy,csv,hashlib,json,os,shutil,sys,time
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/20261026-c2-full-comparable'
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
 shutil.copy2(__file__,out/'source'/Path(__file__).name)
 sys.path.insert(0,str(out/'source/src'))
 from trading_system.strategies.causal_target_w import CausalTargetW
 from dataclasses import replace
 from trading_system.domain import Bar,Intent
 from trading_system.engine import Backtest
 from trading_system.data import save_csv
 from trading_system.strategies import build_strategies
 from trading_system.universe import MainboardUniverse
 wold=load(WSCAN/'config.json');iold=load(ISCAN/'config.json')
 v7=load(ROOT/'configs/experiments/double_bottom_ihs_v7_pressure_support.json')
 assert sha(ISCAN/'bars.csv')==load(WSCAN/'manifest.json')['bars_sha256']==load(ISCAN/'manifest.json')['bars_sha256']
 for name in ('calendar.json','universe.json','stocks.csv','coverage.csv'):shutil.copy2(ISCAN/name,out/name)
 os.link(ISCAN/'bars.csv',out/'bars.csv')
 plan=dict(evaluation_start='20251009',evaluation_end='20260930',source_W_scan=str(WSCAN),source_IHS_scan=str(ISCAN),
  W_full_population=3214,IHS_full_population=3214,bars_sha256=load(ISCAN/'manifest.json')['bars_sha256'],
  entry='qualified W v5.19 retest + IHS v5 breakout; brackets and all entry eligibility unchanged',
  W_entry_distance_cap='original W 2% local retest risk cap retained; IHS has no 2% cap',
  exit='v7 versus frozen C2; W-only and shared account; no parameter tuning',
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
 wc2=copy.deepcopy(v7['strategies'][0]);wc2['type']='c2_replay'
 ic2=copy.deepcopy(v7['strategies'][1]);ic2['type']='c2_replay'
 scenarios=[('W_v7',[('W',v7['strategies'][0])]),('W_C2',[('W',wc2)]),
  ('combined_v7',list(zip(('W','IHS'),v7['strategies']))),
  ('combined_W_C2',[('W',wc2),('IHS',v7['strategies'][1])]),
  ('combined_both_C2',[('W',wc2),('IHS',ic2)])]
 summaries={}
 for label,items in scenarios:
  folder=out/label;folder.mkdir();cfg=copy.deepcopy(v7);cfg['strategies']=[copy.deepcopy(spec) for family,spec in items];cfg['execution']['daily_exit_order']='open_first'
  dump(folder/'config.json',cfg);slist=[];allplans=[];aliases={};families={}
  for family,spec in items:
   if spec['type']=='c2_replay':
    s=CausalTargetW(spec['id'],dict(target_arm='C2'))
    if family=='IHS':
     original_manage=s.manage_position
     def ihs_manage(history,position,manage=original_manage):
      position.plan['w_neckline']=position.plan['ihs_neckline']
      position.plan['w_target']=position.plan['ihs_target']
      exits,events=manage(history,position)
      return [replace(x,reason='ihs_target_close_confirmed') if x.reason=='w_target_close_confirmed' else x for x in exits],events
     s.manage_position=ihs_manage
   else:s=build_strategies([spec])[0]
   slist.append(s)
  for s,(family,spec) in zip(slist,items):
   buckets=defaultdict(list)
   for p in sources[family]:
    original=p['setup_id'];pid=spec['id']+original[original.index(':'):]
    e={k:copy.deepcopy(v) for k,v in p.items() if k not in ('date','symbol','setup_id','trigger','stop','target')}
    if 'w_owner' in e:e['w_owner']=pid
    if spec['type'] in ('pressure_support_w','pressure_support_ihs','matched_cycle_w','matched_cycle_ihs'):e['target_exit_rule']='reference_only'
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
  current_bars=bars
  started=time.monotonic()
  def progress(state):
   if state['session']%200==0:print(json.dumps(dict(case=label,elapsed_seconds=round(time.monotonic()-started),**state)),flush=True)
  e=Backtest(cfg,slist).run(current_bars,cal['open_dates'],set(cal['week_ends']),evaluation_start='20251009',evaluation_end='20260930',universe=universe,progress=progress)
  emitted={v['setup_id']:(v['date'],v['trigger'],v['stop'],v['target']) for v in e.events if v['event']=='entry_intent'}
  assert emitted=={p['setup_id']:(p['date'],p['trigger'],p['stop'],p['target']) for p in allplans}
  for name,rs in (('decisions',e.events),('orders',e.orders),('trades',e.trades),('entry_audit',e.entry_audits),('equity',e.curve)):save_csv(folder/(name+'.csv'),rs)
  summary=e.summary();summary.update(entry_signals=len(allplans),signal_stocks=len({p['symbol'] for p in allplans}),exit_reasons=dict(Counter(t['reason'] for t in e.trades)),
   risk_reasons=dict(Counter(a.get('risk_reason',a.get('execution_reason')) for a in e.entry_audits)))
  changes=0
  for event in e.events:
   if event.get('event')=='target_migration':
    assert event['t_formed']<=event['t_confirmed']<=event['t_detected']<event['valid_from']
    if event.get('valid_from_date'):assert event['date']<event['valid_from_date']
    if event.get('action')=='raise_stop_next_bar':
     assert event['new_stop']>event['old_stop'];changes+=1
  summary['causal_stop_raises']=changes
  if label=='combined_v7':
   reference=ROOT/'runs/20261026-book-stage2-shared/X0'
   for name in ('orders','trades','entry_audit','equity'):
    assert rows(folder/(name+'.csv'))==rows(reference/(name+'.csv')),name
   summary['previous_v7_exact_replay']=True
  dump(folder/'summary.json',summary);summaries[label]=summary
  print(json.dumps(dict(status='case_complete',case=label,summary={k:v for k,v in summary.items() if k not in ('positions','risk_reasons')})),flush=True)
 dump(out/'summaries.json',summaries)
 h=hashlib.sha256()
 for p in sorted((out/'source/src').rglob('*.py')):h.update(str(p.relative_to(out/'source/src')).encode());h.update(p.read_bytes())
 dump(out/'manifest.json',dict(plan,code_sha256=h.hexdigest(),bar_count=2856672,W_signals=len(sources['W']),IHS_signals=len(sources['IHS'])))
 dump(out/'status.json',dict(status='complete',cases=list(summaries)))
 print('COMPLETE',flush=True)
if __name__=='__main__':main()
