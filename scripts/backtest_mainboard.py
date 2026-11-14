"""Resumable full-market fetch and shared-account v3 replay. Never logs SDK secrets."""
import sys, json, time, shutil, hashlib, html
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from dataclasses import asdict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.data import TushareSource, save_csv, validate
from trading_system.domain import Bar
from trading_system.engine import Backtest
from trading_system.strategies import build_strategies
from trading_system.universe import MainboardUniverse

ROOT=Path(__file__).resolve().parents[1]
START,END='20251008','20261007'
def main():
    source=TushareSource()
    cal=json.loads((ROOT/'runs/20261007-205753-437412-csv/calendar.json').read_text(encoding='utf-8'))
    dates=cal['open_dates']; evaluation=[d for d in dates if START<=d<=END]
    rows=[]
    for status in ('L','D','P'):
        rows+=source.query('stock_basic',exchange='',list_status=status,
            fields='ts_code,symbol,name,market,exchange,list_status,list_date,delist_date')
    stocks=[r for r in rows if r.get('market')=='主板' and
            (r['ts_code'].startswith('60') and r['ts_code'].endswith('.SH') or
             r['ts_code'].startswith('00') and r['ts_code'].endswith('.SZ')) and
            r.get('list_date') and r['list_date']<=evaluation[-1] and
            (not r.get('delist_date') or r['delist_date']>evaluation[0])]
    symbols={r['ts_code'] for r in stocks}
    out=ROOT/'runs'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-mainboard-v3')
    out.mkdir(parents=True)
    (out/'status.json').write_text(json.dumps({'status':'fetching','stocks':len(stocks)}),encoding='utf-8')
    print(json.dumps({'output':str(out),'stocks':len(stocks),'sessions':len(dates),'evaluation':len(evaluation)}),flush=True)
    bars=[]; st={}; coverage=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for index,date in enumerate(dates):
            endpoints=['daily','adj_factor','stk_limit']
            futures=[pool.submit(source.query,e,trade_date=date) for e in endpoints]
            daily,factors,limits=[f.result() for f in futures]
            if len(daily)>=6000 or len(limits)>=5800:
                raise RuntimeError('Whole-market endpoint may be truncated; explicit pagination required')
            factors={r['ts_code']:r['adj_factor'] for r in factors}
            limits={r['ts_code']:r for r in limits}
            selected=[r for r in daily if r['ts_code'] in symbols]
            for r in selected:
                code=r['ts_code']
                if code not in factors or code not in limits:
                    raise RuntimeError('Missing factor or price limit: '+date+' '+code)
                lim=limits[code]
                bars.append(Bar(code,date,*[float(r[k]) for k in ('open','high','low','close','vol')],
                    float(factors[code]),float(lim['up_limit']),float(lim['down_limit'])))
            if date in evaluation:
                strows=source.query('stock_st',trade_date=date)
                if len(strows)>=1000 or not strows:
                    raise RuntimeError('Historical ST coverage missing or truncated: '+date)
                st[date]=[r['ts_code'] for r in strows]
            coverage.append(dict(date=date,mainboard_bars=len(selected),daily_rows=len(daily),
                                 factor_rows=len(factors),limit_rows=len(limits)))
            if index%10==0 or index==len(dates)-1:
                print(json.dumps({'fetched':index+1,'total':len(dates),'date':date,'bars':len(bars)}),flush=True)
    validate(bars)
    universe=MainboardUniverse(stocks,st)
    save_csv(out/'stocks.csv',stocks); save_csv(out/'coverage.csv',coverage)
    (out/'universe.json').write_text(json.dumps(dict(stocks=stocks,st_by_date=st),ensure_ascii=False),encoding='utf-8')
    config=json.loads((ROOT/'configs/double_bottom_v3.json').read_text(encoding='utf-8'))
    shutil.copytree(ROOT/'src',out/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(__file__,out/'source/backtest_mainboard.py')
    save_csv(out/'bars.csv',[asdict(b) for b in bars])
    for name,value in [('config',config),('calendar',cal)]:
        (out/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Replay started',flush=True)
    engine=Backtest(config,build_strategies(config['strategies'])).run(bars,dates,set(cal['week_ends']),
        evaluation_start=START,evaluation_end=END,universe=universe)
    for name,data in [('decisions',engine.events),('warmup_decisions',engine.warmup_events),('orders',engine.orders),
                       ('trades',engine.trades),('equity',engine.curve),('entry_audit',engine.entry_audits)]:
        save_csv(out/(name+'.csv'),data)
    summary=engine.summary(); summary['event_counts']=dict(Counter(r['event'] for r in engine.events))
    summary['rejection_counts']=dict(Counter(r.get('reason') for r in engine.events if r['event']=='entry_rejected'))
    manifest=dict(stocks=len(stocks),bar_count=len(bars),start_requested=START,end_requested=END,
        first_session=evaluation[0],last_session=evaluation[-1],sessions=len(evaluation),
        warmup_start=dates[0],universe='historical listed SH/SZ mainboard A shares; dated stock_st exclusion on signal and execution',
        survivorship='includes subsequently delisted stocks',shared_account=True,rule_version='v3',
        limitations=['daily OHLC conservative execution','synthetic total-return factor adjustment',
            'ST after entry does not force sale; stops continue','delisted holdings may retain stale marks; inspect final positions',
            'manual dated phase policy is not part of v3'],
        bars_sha256=hashlib.sha256((out/'bars.csv').read_bytes()).hexdigest())
    for name,value in [('summary',summary),('manifest',manifest),('status',{'status':'complete'})]:
        (out/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>主板非ST双底回测</title><h1>主板非ST双底 v3 全量回测</h1><pre>'+html.escape(json.dumps(dict(manifest=manifest,summary=summary),ensure_ascii=False,indent=2))+'</pre>',encoding='utf-8')
    print(json.dumps(dict(output=str(out),summary=summary),ensure_ascii=True),flush=True)
if __name__=='__main__':
    try: main()
    except Exception as error:
        print('FAILED: '+str(error) if isinstance(error,RuntimeError) else 'FAILED: '+type(error).__name__,flush=True)
        sys.exit(1)
