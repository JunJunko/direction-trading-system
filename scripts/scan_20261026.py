"""Premarket scan with frozen v7 entry rules and official Tushare data."""
import sys,json,csv,os,time
from pathlib import Path
from collections import defaultdict,Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
import requests
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Bar
from trading_system.data import validate
from trading_system.strategies import build_strategies
from trading_system.risk import RiskManager
OUT=ROOT/'runs/20261026-premarket-w-ihs'
CACHE=ROOT/'data/raw/scan-20261026'
CFG=json.loads((ROOT/'configs/experiments/double_bottom_ihs_v7_pressure_support.json').read_text())
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def query(e,**p):
 path=CACHE/(e+'_'+ '_'.join(f'{k}-{v}' for k,v in sorted(p.items()))+'.json')
 if path.exists():
  cached=json.loads(path.read_text(encoding='utf-8'))
  if cached:return cached
 r=requests.post('https://api.tushare.pro',json=dict(api_name=e,token=os.environ['TUSHARE_TOKEN'],params=p,fields=''),timeout=25)
 r.raise_for_status();j=r.json()
 if j['code']!=0:raise RuntimeError('Tushare query failed: '+e+' code '+str(j['code']))
 d=j['data'];rs=[dict(zip(d['fields'],v)) for v in d['items']];dump(path,rs);return rs
def scan(item):
 symbol,bs=item;validate(bs);ss=build_strategies(CFG['strategies']);plans=[];events=[]
 # A W seed can live at most 14 subsequent bars. All historical bars remain
 # available to geometry; first-observable gating prevents old registration.
 for i in range(max(0,len(bs)-16),len(bs)):
  for s in ss:
   intents,es=s.on_close(bs[:i+1],set())
   if bs[i].date=='20261023':
    plans.extend(asdict(v) for v in intents);events.extend(es)
 waiting=[asdict(v) for v in ss[0].waiting.get(symbol,[])]
 return dict(symbol=symbol,last=bs[-1].date,plans=plans,waiting=waiting,events=events)
def main():
 OUT.mkdir(exist_ok=True);CACHE.mkdir(exist_ok=True)
 cal=query('trade_cal',exchange='SSE',start_date='20261001',end_date='20261030')
 dates=sorted(r['cal_date'] for r in cal if r['is_open']==1 and r['cal_date']<='20261023')
 assert dates and dates[-1]=='20261023'
 stocks=query('stock_basic',exchange='',list_status='L')
 stocks=[r for r in stocks if r['market']=='主板' and r['ts_code'].startswith(('60','00')) and r['list_date']<='20261023']
 st=query('stock_st',trade_date='20261023');assert st and len(st)<1000
 excluded={r['ts_code'] for r in st};names={r['ts_code']:r['name'] for r in stocks if r['ts_code'] not in excluded}
 grouped=defaultdict(list);print('loading historical bars',len(names),flush=True)
 base=ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v5-breakout-trend/bars.csv'
 with base.open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   if r['symbol'] in names:grouped[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
 coverage=[]
 for d in dates:
  daily=query('daily',trade_date=d);fs=query('adj_factor',trade_date=d);ls=query('stk_limit',trade_date=d)
  assert daily and len(daily)<6000 and len(ls)<6000
  fs={r['ts_code']:r['adj_factor'] for r in fs};ls={r['ts_code']:r for r in ls}
  for r in daily:
   s=r['ts_code']
   if s not in names:continue
   assert s in fs and s in ls
   grouped[s].append(Bar(s,d,*[float(r[k]) for k in ('open','high','low','close','vol')],float(fs[s]),float(ls[s]['up_limit']),float(ls[s]['down_limit'])))
  coverage.append(dict(date=d,daily_rows=len(daily)));print('fetched',d,len(daily),flush=True)
 for bs in grouped.values():bs.sort(key=lambda b:b.date)
 dump(OUT/'config.json',CFG);dump(OUT/'coverage.json',coverage);dump(OUT/'stocks.json',stocks)
 results=[]
 with ProcessPoolExecutor(max_workers=8) as pool:
  for n,r in enumerate(pool.map(scan,sorted(grouped.items()),chunksize=8),1):
   results.append(r)
   if n%200==0:print('scanned',n,len(grouped),flush=True)
 plans=[];waiting=[];risk=RiskManager(CFG['risk'])
 from trading_system.domain import Intent
 for r in results:
  if r['last']!='20261023':continue
  for p in r['plans']:
   i=Intent(**p);a=risk.assess(i,i.trigger*1.001,1000000,1000000,{}, {},.0003,.0005,slippage=.001)
   plans.append(dict(p,name=names[r['symbol']],reference_assessment=a))
  waiting.extend(dict(p,name=names[r['symbol']]) for p in r['waiting'])
 dump(OUT/'results.json',results);dump(OUT/'plans.json',plans);dump(OUT/'waiting.json',waiting)
 summary=dict(as_of='20261023',for_session='20261026',scope='SH/SZ mainboard excluding ST as of 20261023',stocks=len(grouped),missing_history=sorted(set(names)-set(grouped)),stale=[r['symbol'] for r in results if r['last']!='20261023'],plans=len(plans),waiting=len(waiting),risk_reasons=dict(Counter(p['reference_assessment']['risk_reason'] for p in plans)),source=str(base),method='full historical geometry; last 16 bars state warmup; first-observable gating and maximum 14-bar W lifetime',daily_20261026_unavailable_before_open=True)
 dump(OUT/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
