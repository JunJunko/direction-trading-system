"""Frozen admission/propagation ablation over the entire previously verified candidate pool."""
import copy,csv,json,os,shutil,sys
from collections import defaultdict,Counter
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Bar,Intent
from trading_system.strategies import build_strategies
from trading_system.engine import Backtest
from trading_system.universe import MainboardUniverse
from trading_system.data import save_csv
from backtest_candidate_policy import load,dump,rows,sha,bind
OLD=ROOT/'runs/20261109-candidate-policy-full';OUT=ROOT/'runs/20261109-qualified-candidates-verified'
MODES={'propagation_only':(0,0,True),
       'quality_05':(3,.05,False),'quality_10':(3,.1,False),'quality_20':(3,.2,False),
       'quality_05_guard':(3,.05,True),'quality_10_guard':(3,.1,True),'quality_20_guard':(3,.2,True)}
CONTROLS=['baseline','balance_single','balance_fallback']

def as_intent(p,name):
 evidence={k:copy.deepcopy(v) for k,v in p.items() if k not in ('date','symbol','setup_id','trigger','stop','target') and not k.startswith('candidate_')}
 for k in ('candidate_leg_sessions','candidate_time_balance','candidate_area'):evidence[k]=p[k]
 return Intent(name,p['symbol'],p['date'],p['trigger'],p['stop'],p['target'],name+':'+p['setup_id'].split(':',1)[1],'inverse_head_shoulders',evidence)

def main():
 OUT.mkdir();(OUT/'source').mkdir()
 base=load(OLD/'baseline-config.json');configs={p:load(OLD/(p+'-config.json')) for p in CONTROLS}
 for label,(sessions,ratio,guard) in MODES.items():
  cfg=copy.deepcopy(base);cfg['strategies'][0]=dict(type='qualified_candidate_ihs',id='inverse_head_shoulders_v11_'+label,
   params=dict(base['strategies'][0]['params'],candidate_ranking='time_balance',candidate_consumption='fallback',
    min_shoulder_sessions=sessions,min_shoulder_ratio=ratio,propagate_bottom_failure=guard))
  configs[label]=cfg
 cfg=copy.deepcopy(base);cfg['strategies']=cfg['strategies'][1:];configs['W_only']=cfg
 oldmanifest=load(OLD/'manifest.json')
 for filename in ['balance_fallback-plans.json','W-plans.json']:
  assert sha(OLD/filename)==oldmanifest['artifact_hashes'][filename]
 assert sha(OLD/'bars.csv')==oldmanifest['data_sha256']
 protocol=dict(population=3214,bars=2856672,start='20251009',end='20260930',warmup='20230103',
  bars_sha256=oldmanifest['data_sha256'],raw_candidates=2064,signal_dates=1713,configs=configs,
  source_candidate_hash=sha(OLD/'balance_fallback-plans.json'),W_signal_hash=sha(OLD/'W-plans.json'),
  primary_hypothesis='quality_10_guard; 05 and 20 are predeclared sensitivity checks, no post-result threshold tuning',
  review_correction='Prevent unused alternatives from invalidating an already filled leader. Initial results retained in ../20261109-qualified-candidates; parameters unchanged; all 42 cases rerun.',
  quality='Both outer legs >=3 observed stock sessions and left outer/left core and right outer/right core >= threshold. No absolute pattern-span limit.',
  group='(symbol, confirmed head pivot date), invariant to left/right shoulder or neckline changes; a distinct confirmed head is a new group',
  permanent_failure='Actual entry opening loses neckline or invalidates initial stop; initial protection breach is known only at close and cannot veto earlier same-day opening orders',
  cohort_veto='RR/upside/entry-distance/noise/bracket failure vetoes same-head candidates from that signal date; no permanent invalidation from budget, position count or suspension',
  cache='All 2064 geometric candidates from verified prior full population scan, not prior fills. Only admission and runtime account failure state change. Legs independently recalculated from raw bars; native on_close checks separately.',
  account_cases=42,costs=[1,2],risk='unchanged: upside >5%, net RR >3, per-trade .5%, account 2%, single name10%, gross50%, max5',
  limits='Known development sample, no untouched holdout; time halves will be descriptive only. Nonblind chart review, no labeled error-rate claim.',
  source_hashes={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'src').rglob('*.py')})
 dump(OUT/'protocol.json',protocol)
 shutil.copytree(ROOT/'src',OUT/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
 for p in [Path(__file__),ROOT/'tests/test_qualified_candidate_ihs.py',ROOT/'scripts/backtest_candidate_policy.py',ROOT/'run.py']:shutil.copy2(p,OUT/'source'/p.name)
 shutil.copy2(ROOT/'runs/qualified-candidate-tests.log',OUT/'tests.log')
 for name in ['calendar.json','universe.json','stocks.csv','coverage.csv']:shutil.copy2(OLD/name,OUT/name)
 os.link(OLD/'bars.csv',OUT/'bars.csv')
 for label,cfg in configs.items():
  dump(OUT/(label+'-config.json'),cfg)
  if label in MODES:dump(ROOT/'configs/experiments'/('ihs_v11_'+label+'_with_weekly_w.json'),cfg)
 raw=load(OLD/'balance_fallback-plans.json');plans={p:load(OLD/(p+'-plans.json')) for p in CONTROLS};plans['W_only']=[]
 w=load(OLD/'W-plans.json');dump(OUT/'W-plans.json',w)
 buckets=defaultdict(list)
 for p in raw:buckets[p['date'],p['symbol']].append(p)
 for label in MODES:
  strategy=build_strategies([configs[label]['strategies'][0]])[0];plans[label]=[];events=[]
  for (date,symbol),ps in sorted(buckets.items()):
   intents,ev=strategy.choose_intents([as_intent(p,strategy.name) for p in ps],SimpleNamespace(date=date,symbol=symbol))
   events.extend(ev)
   plans[label].extend(dict(date=i.date,symbol=i.symbol,setup_id=i.setup_id,trigger=i.trigger,stop=i.stop,target=i.target,**i.evidence) for i in intents)
  save_csv(OUT/(label+'-qualification.csv'),events)
 for label,ps in plans.items():dump(OUT/(label+'-plans.json'),ps)
 print('QUALIFIED SIGNALS',{k:len(v) for k,v in plans.items()},flush=True)
 dump(OUT/'status.json',dict(status='loading',cases_done=0))
 symbols={p['symbol'] for p in raw+w};grouped=defaultdict(list);population=set();bar_count=0
 with (OUT/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   population.add(r['symbol']);bar_count+=1
   if r['symbol'] in symbols:grouped[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
 assert len(population)==3214 and bar_count==2856672
 for h in grouped.values():h.sort(key=lambda b:b.date)
 indices={s:{b.date:i for i,b in enumerate(h)} for s,h in grouped.items()}
 for p in raw:
  ix=indices[p['symbol']];ds=[p[k] for k in ('ihs_left_date','ihs_peak1_date','ihs_head_date','ihs_peak2_date','ihs_right_date')]
  assert [ix[b]-ix[a] for a,b in zip(ds,ds[1:])]==p['candidate_leg_sessions']
 dump(OUT/'pool-verification.json',dict(population=3214,bars=bar_count,all_2064_legs_recomputed=True,
  prior_pool_hash_matches=True,signal_counts={k:len(v) for k,v in plans.items()},W_signals=len(w)))
 cal=load(OUT/'calendar.json');ud=load(OUT/'universe.json');universe=MainboardUniverse(ud['stocks'],ud['st_by_date']);summaries=[]
 for label,cfg in configs.items():
  for combo in ([True] if label=='W_only' else [False,True]):
   for cost in [1,2]:
    case=f"{label}_{'combined' if combo else 'IHS'}_cost{cost}";folder=OUT/case;folder.mkdir()
    current=copy.deepcopy(cfg);current['execution']['commission_rate']*=cost;current['execution']['slippage']*=cost
    if label=='W_only':selected=[w]
    else:
     current['strategies']=current['strategies'][:2 if combo else 1];selected=[plans[label]]+([w] if combo else [])
    strategies=build_strategies(current['strategies'])
    for s,ps in zip(strategies,selected):bind(s,ps)
    used={p['symbol'] for ps in selected for p in ps}
    bars=sorted((b for symbol in used for b in grouped[symbol]),key=lambda b:(b.date,b.symbol))
    engine=Backtest(current,strategies).run(bars,cal['open_dates'],set(cal['week_ends']),evaluation_start='20251009',evaluation_end='20260930',universe=universe)
    actual=[(e['setup_id'],e['date'],e['trigger'],e['stop'],e['target']) for e in engine.events if e['event']=='entry_intent']
    expected=[(p['setup_id'],p['date'],p['trigger'],p['stop'],p['target']) for ps in selected for p in ps]
    assert sorted(actual)==sorted(expected)
    for name,rs in [('decisions',engine.events),('orders',engine.orders),('trades',engine.trades),('entry_audit',engine.entry_audits),('equity',engine.curve)]:
     save_csv(folder/(name+'.csv'),rs)
     if label in CONTROLS:assert rows(folder/(name+'.csv'))==rows(OLD/case/(name+'.csv')),(case,name)
    fills=[a for a in engine.entry_audits if a.get('filled_quantity',0)>0]
    assert all(a['net_rr']>3 and a['expected_upside']>.05 for a in fills)
    assert all(r['cash']>=-1e-7 and r['positions']<=5 for r in engine.curve)
    assert len({(a['symbol'],a['date']) for a in fills})==len(fills)
    summary=engine.summary();summary.update(case=case,policy=label,combined=combo,cost=cost,
     entry_signals=len(expected),bottom_blocks=sum(a.get('risk_reason') in ('ihs_bottom_invalidated','ihs_bottom_cohort_veto') for a in engine.entry_audits),
     failure_events=sum(e['event']=='bottom_failure_recorded' for e in engine.events),
     IHS_buys=sum('inverse_head_shoulders' in a['strategy'] for a in fills),W_buys=sum(a['strategy']=='double_bottom_v3' for a in fills))
    dump(folder/'config.json',current);dump(folder/'summary.json',summary)
    summaries.append({k:v for k,v in summary.items() if k!='positions'});save_csv(OUT/'comparison.csv',summaries)
    dump(OUT/'status.json',dict(status='accounts',cases_done=len(summaries),cases=42))
    print('ACCOUNT',case,round(summary['total_return']*100,4),round(summary['max_drawdown']*100,4),summary['filled_buys'],summary['bottom_blocks'],flush=True)
 assert len(summaries)==42
 dump(OUT/'verification.json',dict(all_population_accounted=True,prior_12_accounts_exact=True,all_42_cases_risk_checked=True,all_candidate_signals_accounted=True))
 dump(OUT/'status.json',dict(status='complete',cases=42,stocks=3214))
if __name__=='__main__':main()
