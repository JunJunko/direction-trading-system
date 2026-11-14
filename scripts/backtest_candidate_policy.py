
"""Frozen 2x2 candidate-policy experiment, complete population scan and account replay."""
import argparse,copy,csv,gzip,hashlib,json,os,shutil,sys,time
from collections import defaultdict,Counter
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
from functools import lru_cache
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Bar,Intent
from trading_system.data import save_csv,validate
from trading_system.strategies import build_strategies
from trading_system.engine import Backtest
from trading_system.universe import MainboardUniverse
from trading_system.strategies.enclosing_inverse_head_shoulders import _PriceRanges
BASE=ROOT/'runs/20261109-algorithm-combination-legacy-check/IHS_v7_first_W_v3'
DATA=ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v5-breakout-trend'
OLDW=ROOT/'runs/20261007-212241-mainboard-v3'
OUT=ROOT/'runs/20261109-candidate-policy-full'
MODES={'baseline':None,'balance_single':('time_balance','all'),'area_selected':('area','selected'),
       'area_fallback':('area','fallback'),'balance_fallback':('time_balance','fallback')}
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def initialize(configs,calendar,output,fast_warmup=False,shared_caches=False,signal_days=None):
 global CONFIGS,CALENDAR,OUTPUT,FAST_WARMUP,SHARED_CACHES,SIGNAL_DAYS
 CONFIGS=configs;CALENDAR=calendar;OUTPUT=Path(output);FAST_WARMUP=fast_warmup;SHARED_CACHES=shared_caches;SIGNAL_DAYS=signal_days
def scan(item):
 symbol,bars=item
 strategies={k:build_strategies([c['strategies'][0]])[0] for k,c in CONFIGS.items()}
 w=build_strategies([CONFIGS['baseline']['strategies'][1]])[0]
 probe=strategies['baseline'];original=probe.candidate_layouts
 if SHARED_CACHES:
  ranges=_PriceRanges();update=ranges.update;query=lru_cache(maxsize=50000)(ranges.query)
  def cached_update(bs):
   if ranges.anchor!=bs[-1].factor or len(bs)<ranges.count or (ranges.count and bs[ranges.count-1]!=ranges.last):query.cache_clear()
   return update(bs)
  ranges.query=query;ranges.update=cached_update;probe.ranges[symbol]=ranges
  for label,strategy in strategies.items():
   if label=='baseline':continue
   strategy.caches=probe.caches;strategy.ranges=probe.ranges
   strategy.normalized_history=lambda history:probe.adjusted_bars[history[-1].symbol][2]
 raw=[]
 def capture(bs,ps,rs):
  raw[:]=[] if FAST_WARMUP and bs[-1].date<'20251009' else original(bs,ps,rs)
  return raw
 probe.candidate_layouts=capture
 for k,s in strategies.items():
  if k!='baseline':s.candidate_layouts=lambda bs,ps,rs:raw
 history=[];plans={k:[] for k in strategies};plans['W']=[]
 counts=Counter();shortlists=[]
 for bar in bars:
  history.append(bar)
  for label,strategy in strategies.items():
   if SIGNAL_DAYS is not None and bar.date not in SIGNAL_DAYS.get(symbol,set()):continue
   intents,events=strategy.on_close(history,set())
   if bar.date<'20251009':continue
   plans[label].extend(dict(date=i.date,symbol=i.symbol,setup_id=i.setup_id,trigger=i.trigger,stop=i.stop,target=i.target,**i.evidence) for i in intents)
   ranked=[e for e in events if e['event']=='candidate_ranked']
   if ranked:
    counts[label+'_days']+=1
    counts[label+'_multi_days']+=len(ranked)>1
    shortlists.extend(ranked)
  intents,_=w.on_close(history,CALENDAR)
  if bar.date>='20251009':
   plans['W'].extend(dict(date=i.date,symbol=i.symbol,setup_id=i.setup_id,trigger=i.trigger,stop=i.stop,target=i.target,**i.evidence) for i in intents)
 payload=dict(symbol=symbol,plans=plans,counts=dict(counts),bars=len(bars))
 dump(OUTPUT/'stocks'/f'{symbol}.json',payload)
 with gzip.open(OUTPUT/'candidate-events'/f'{symbol}.jsonl.gz','wt',encoding='utf-8') as f:
  for e in shortlists:f.write(json.dumps(e)+'\n')
 return payload
def bind(strategy,plans):
 buckets=defaultdict(list)
 for p in plans:
  evidence={k:copy.deepcopy(v) for k,v in p.items() if k not in ('date','symbol','setup_id','trigger','stop','target')}
  reason='inverse_head_shoulders' if 'ihs_head_date' in evidence else 'double_bottom_retest_restart'
  i=Intent(strategy.name,p['symbol'],p['date'],p['trigger'],p['stop'],p['target'],p['setup_id'],reason,evidence)
  event=dict(p,strategy=strategy.name,event='entry_intent')
  if reason=='inverse_head_shoulders':event['decision']='BUY_CANDIDATE'
  buckets[p['symbol'],p['date']].append((i,event))
 def cached(history,weekends):
  items=buckets.get((history[-1].symbol,history[-1].date),[])
  return [copy.deepcopy(i) for i,e in items],[copy.deepcopy(e) for i,e in items]
 strategy.on_close=cached
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--resume',action='store_true');parser.add_argument('--workers',type=int,default=10);parser.add_argument('--fast-warmup',action='store_true');parser.add_argument('--shared-caches',action='store_true');parser.add_argument('--signal-days-only',action='store_true');args=parser.parse_args()
 base=load(BASE/'config.json');configs={}
 for label,mode in MODES.items():
  cfg=copy.deepcopy(base)
  if mode:
   spec=cfg['strategies'][0];spec['type']='candidate_policy_ihs';spec['id']='inverse_head_shoulders_v10_'+label
   spec['params'].update(candidate_ranking=mode[0],candidate_consumption=mode[1])
  configs[label]=cfg
 if not args.resume:
  OUT.mkdir();(OUT/'stocks').mkdir();(OUT/'candidate-events').mkdir()
  shutil.copytree(ROOT/'src',OUT/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
  shutil.copy2(__file__,OUT/'source'/Path(__file__).name)
  shutil.copy2(ROOT/'tests/test_candidate_policy_ihs.py',OUT/'source/test_candidate_policy_ihs.py')
  shutil.copy2(ROOT/'runs/candidate-policy-tests.log',OUT/'tests.log')
  for name in ('calendar.json','universe.json','stocks.csv','coverage.csv'):shutil.copy2(DATA/name,OUT/name)
  os.link(DATA/'bars.csv',OUT/'bars.csv')
  digest=sha(OUT/'bars.csv');assert digest==load(DATA/'manifest.json')['bars_sha256']
  protocol=dict(population=3214,bars=2856672,warmup='20230103',start='20251009',end='20260930',
   bars_sha256=digest,ranking='time_balance = minimum/maximum of four pivot-to-pivot session lengths; ties newer right shoulder, then shorter span, then ID',
   modes=MODES,consumption='all: all geometric candidates consumed, only first emitted; selected: only first consumed/emitted; fallback: all ranked candidates emitted once on initial breakout date, account assesses each, at most one position per symbol, unused orders expire',
   same_day_fallback='all candidates tested at signal close and actual following session, never future selection',
   geometry='existing geometric, first breakout, prior trend, stop and target formulas',
   accounts=['IHS alone','IHS first + weekly W v3'],costs=[1,2],upside_gate=.05,exit='existing v7',
   visual_audit='all distinct filled IHS setups across arms, plus changed W fills; review signal-date-only images before consulting outcome where practical; prior cases already known',
   shape_diagnostics='span, four leg balance, tiny outer legs; these are proxies, no fixed numeric error-rate claim',
   statistical_status='known development snapshot, result-driven new hypothesis, no untouched holdout',
   configs=configs,source_hashes={str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'src').rglob('*.py')})
  dump(OUT/'protocol.json',protocol)
 else:
  protocol=load(OUT/'protocol.json')
  assert configs==protocol['configs']
  assert all(sha(ROOT/p)==v for p,v in protocol['source_hashes'].items())
  assert sha(OUT/'bars.csv')==protocol['bars_sha256']
 for label,cfg in configs.items():
  dump(OUT/(label+'-config.json'),cfg)
  # Standalone, loadable experimental configurations.
  if label!='baseline':dump(ROOT/'configs/experiments'/('ihs_v10_'+label+'_with_weekly_w.json'),cfg)
 dump(OUT/'status.json',dict(status='loading'))
 grouped=defaultdict(list)
 with (OUT/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   grouped[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
 assert len(grouped)==3214 and sum(map(len,grouped.values()))==2856672
 for bs in grouped.values():
  bs.sort(key=lambda b:b.date)
  # Resume reads the identical SHA-256-verified file already fully validated.
  if not args.resume:validate(bs)
 cal=load(OUT/'calendar.json');ud=load(OUT/'universe.json');weekends=set(cal['week_ends'])
 done=set()
 if args.resume:
  for p in (OUT/'stocks').glob('*.json'):
   try:
    load(p)
    with gzip.open(OUT/'candidate-events'/(p.stem+'.jsonl.gz'),'rt',encoding='utf-8') as f:
     for line in f:json.loads(line)
    done.add(p.stem)
   except (OSError,EOFError,ValueError):pass
 started=time.monotonic()
 signal_days=None
 if args.signal_days_only:
  signal_days=defaultdict(set)
  for p in load(DATA/'plans.json'):signal_days[p['symbol']].add(p['date'])
 with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize,initargs=(configs,weekends,str(OUT),args.fast_warmup,args.shared_caches,signal_days)) as pool:
  pending=[pool.submit(scan,item) for item in sorted(grouped.items()) if item[0] not in done]
  for future in as_completed(pending):
   result=future.result();done.add(result['symbol'])
   if len(done)%50==0 or len(done)==3214:
    status=dict(status='scanning',stocks_done=len(done),stocks=3214,seconds=round(time.monotonic()-started))
    dump(OUT/'status.json',status);print(json.dumps(status),flush=True)
 plans={k:[] for k in list(MODES)+['W']};counts=Counter()
 for symbol in sorted(grouped):
  result=load(OUT/'stocks'/f'{symbol}.json');counts.update(result['counts'])
  for k,ps in result['plans'].items():plans[k].extend(ps)
 for k,ps in plans.items():
  ps.sort(key=lambda p:(p['date'],p['symbol'],p.get('candidate_rank',0),p['setup_id']))
  assert len({p['setup_id'] for p in ps})==len(ps),k
  dump(OUT/(k+'-plans.json'),ps)
 def sig(ps):return {(p['symbol'],p['setup_id'].split(':',1)[1]):(p['date'],p['trigger'],p['stop'],p['target']) for p in ps}
 assert sig(plans['baseline'])==sig(load(DATA/'plans.json'))
 oldw=[dict(date=r['date'],symbol=r['symbol'],setup_id=r['setup_id'],**{k:float(r[k]) for k in ('trigger','stop','target')}) for r in rows(OLDW/'decisions.csv') if r['event']=='entry_intent']
 assert sig(plans['W'])==sig(oldw)
 dump(OUT/'scan-verification.json',dict(stocks=len(done),baseline_1713_exact=True,W_1146_exact=True,
  signal_counts={k:len(v) for k,v in plans.items()},candidate_counts=dict(counts),
  area_selected_equivalent=sig(plans['baseline'])==sig(plans['area_selected'])))
 print('SCAN COMPLETE', {k:len(v) for k,v in plans.items()},flush=True)
 universe=MainboardUniverse(ud['stocks'],ud['st_by_date']);summaries=[]
 for label,cfg in configs.items():
  for combo in (False,True):
   for cost in (1,2):
    case=f"{label}_{'combined' if combo else 'IHS'}_cost{cost}"
    folder=OUT/case;folder.mkdir(exist_ok=True)
    current=copy.deepcopy(cfg);current['strategies']=current['strategies'][:2 if combo else 1]
    current['execution']['commission_rate']*=cost;current['execution']['slippage']*=cost
    strategies=build_strategies(current['strategies'])
    selected=[plans[label]]+([plans['W']] if combo else [])
    for s,ps in zip(strategies,selected):bind(s,ps)
    symbols={p['symbol'] for ps in selected for p in ps}
    bs=sorted((b for symbol in symbols for b in grouped[symbol]),key=lambda b:(b.date,b.symbol))
    engine=Backtest(current,strategies).run(bs,cal['open_dates'],weekends,evaluation_start='20251009',evaluation_end='20260930',universe=universe)
    actual=[(e['setup_id'],e['date'],e['trigger'],e['stop'],e['target']) for e in engine.events if e['event']=='entry_intent']
    expected=[(p['setup_id'],p['date'],p['trigger'],p['stop'],p['target']) for ps in selected for p in ps]
    assert sorted(actual)==sorted(expected)
    for name,rs in [('decisions',engine.events),('orders',engine.orders),('trades',engine.trades),('entry_audit',engine.entry_audits),('equity',engine.curve)]:
     save_csv(folder/(name+'.csv'),rs)
     if case=='baseline_combined_cost1' and name!='decisions':assert rows(folder/(name+'.csv'))==rows(BASE/(name+'.csv')),name
    fills=[a for a in engine.entry_audits if a.get('filled_quantity',0)>0]
    assert all(a['net_rr']>3 and a['expected_upside']>.05 for a in fills)
    assert all(r['cash']>=-1e-7 and r['positions']<=5 for r in engine.curve)
    assert len({(a['symbol'],a['date']) for a in fills})==len(fills)
    summary=engine.summary();summary.update(case=case,policy=label,combined=combo,cost=cost,
     entry_signals=len(expected),fallback_fills=sum(a.get('setup_id') in {p['setup_id'] for p in plans[label] if p.get('candidate_rank',1)>1} for a in fills))
    dump(folder/'config.json',current);dump(folder/'summary.json',summary)
    summaries.append({k:v for k,v in summary.items() if k!='positions'})
    save_csv(OUT/'comparison.csv',summaries)
    print('ACCOUNT',case,round(summary['total_return']*100,4),round(summary['max_drawdown']*100,4),summary['filled_buys'],flush=True)
 dump(OUT/'verification.json',dict(all_population_scanned=True,baseline_shared_account_exact=True,all_signals_accounted_for=True,all_fills_risk_checked=True,cases=len(summaries)))
 dump(OUT/'status.json',dict(status='complete',stocks=3214,cases=len(summaries)))
if __name__=='__main__':main()

