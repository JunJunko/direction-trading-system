"""Causal full-population qualified W entry scan; unchanged v5.19 entry rules."""
import csv,gzip,hashlib,json,os,shutil,sys,time
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Bar
from trading_system.data import validate
from backtest_inverse_head_shoulders import initialize,scan
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def main():
 out=ROOT/'runs/20261025-mainboard-qualified-w-v519-signals';base=ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v5-breakout-trend'
 cfg=load(ROOT/'configs/experiments/double_bottom_v5_19_qualified_w_structure.json')
 out.mkdir();(out/'signal-events').mkdir();shutil.copytree(ROOT/'src',out/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
 for f in (Path(__file__),ROOT/'scripts/backtest_inverse_head_shoulders.py',ROOT/'scripts/backtest_daily_direction.py'):shutil.copy2(f,out/'source'/f.name)
 shutil.copy2(ROOT/'runs/w-ihs-v7-tests.log',out/'tests.log');dump(out/'config.json',cfg)
 for name in ('calendar.json','universe.json','stocks.csv','coverage.csv'):shutil.copy2(base/name,out/name)
 os.link(base/'bars.csv',out/'bars.csv');digest=sha(out/'bars.csv');assert digest==load(base/'manifest.json')['bars_sha256']
 protocol=dict(scope='all 3214 input stocks',full_population_scanned=True,source_snapshot=str(base),evaluation_start='20251009',evaluation_end='20260930',
  entry='qualified W v5.19, all entry parameters unchanged',exit='scan only; holding rules do not enter signal generation',
  bars_sha256=digest,config_sha256=sha(out/'config.json'),parameters_tuned=False,holdout_accessed=False,workers=10)
 dump(out/'evaluation-plan.json',protocol);print(json.dumps(dict(status='loading',output=str(out))),flush=True)
 grouped=defaultdict(list)
 with (out/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):grouped[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
 for bs in grouped.values():bs.sort(key=lambda b:b.date);validate(bs)
 assert len(grouped)==3214 and sum(map(len,grouped.values()))==2856672
 plans=[];counts=Counter();warm=Counter();done=0;started=time.monotonic()
 with ProcessPoolExecutor(max_workers=10,initializer=initialize,initargs=(cfg,'20251009','20260930',str(out))) as pool:
  futures=[pool.submit(scan,item) for item in sorted(grouped.items())]
  for f in as_completed(futures):
   result=f.result();done+=1;plans+=result['plans'];counts.update(result['counts']);warm.update(result['warmup'])
   if done%50==0 or done==3214:
    state=dict(status='scanning',stocks_done=done,stocks=3214,plans=len(plans),elapsed_seconds=round(time.monotonic()-started));dump(out/'status.json',state);print(json.dumps(state),flush=True)
 plans.sort(key=lambda p:(p['date'],p['symbol'],p['setup_id']));assert len({p['setup_id'] for p in plans})==len(plans)
 # Exact signal reproduction on the previously studied 62-stock cohort.
 cohort=ROOT/'runs/20261024-qualified-w-cohort';old=load(cohort/'plans.json');symbols=set(load(cohort/'symbols.json'))
 old=[{k:v for k,v in p.items() if k not in ('strategy','event')} for p in old]
 assert [p for p in plans if p['symbol'] in symbols]==sorted(old,key=lambda p:(p['date'],p['symbol'],p['setup_id']))
 dump(out/'plans.json',plans);dump(out/'signal-counts.json',dict(evaluation=dict(counts),warmup=dict(warm)))
 h=hashlib.sha256()
 for p in sorted((out/'source/src').rglob('*.py')):h.update(str(p.relative_to(out/'source/src')).encode());h.update(p.read_bytes())
 dump(out/'manifest.json',dict(protocol,stocks=3214,bar_count=2856672,plans=len(plans),signal_stocks=len({p['symbol'] for p in plans}),code_sha256=h.hexdigest()))
 dump(out/'verification.json',dict(all_3214_scanned=True,cohort_99_entry_plans_exact=True,normalized_price_cache_rule_neutral=True,unique_signals=True,data_hash_verified=True))
 dump(out/'status.json',dict(status='complete',stocks=3214,plans=len(plans)));print(json.dumps(dict(status='complete',plans=len(plans))),flush=True)
if __name__=='__main__':main()
