"""Scan every stock independently, then replay all signal stocks in one account.

Only account-independent structural calculations run in worker processes.
Sizing, arbitration, fills, exits and equity use the ordinary Backtest engine.
"""
import argparse
import copy
import csv
import gzip
import hashlib
import html
import json
import os
import shutil
import sys
import time
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor,as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trading_system.data import save_csv,validate
from trading_system.domain import Bar
from trading_system.engine import Backtest
from trading_system.strategies import build_strategies
from trading_system.universe import MainboardUniverse


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(2**20),b''):h.update(block)
    return h.hexdigest()


def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as f:yield from csv.DictReader(f)


def initialize(config,calendar,ends,first,last,output):
    global SETTINGS
    SETTINGS=(config,calendar,ends,first,last,Path(output))


def scan(item):
    symbol,bars=item
    config,calendar,ends,first,last,out=SETTINGS
    s=build_strategies(config['strategies'])[0];s.set_calendar(calendar)
    history=[];begun=False;counts=Counter();warm=Counter();reasons=Counter();plans={}
    def record(events,handle):
        for e in events:
            handle.write(json.dumps(e,ensure_ascii=False,separators=(',',':'))+'\n')
            if e['date']<first:warm[e['event']]+=1
            else:
                counts[e['event']]+=1
                if e.get('reason'):reasons[(e['event'],e['reason'])]+=1
    # Per-symbol tapes contain the full population's warmup and evaluation events.
    with gzip.open(out/'signal-events'/(symbol+'.jsonl.gz'),'wt',encoding='utf-8',compresslevel=1) as f:
        for b in bars:
            if b.date>last:break
            if b.date>=first and not begun:
                record(s.begin_evaluation(first),f)
                s.set_context(dict(allow_same_level=False,allow_cycle_upgrade=False,entry_clock='daily',lower_histories={}))
                begun=True
            history.append(b)
            intents,events=s.on_close(history,ends)
            record(events,f)
            if b.date>=first:
                for intent in intents:plans.setdefault(intent.setup_id,asdict(intent))
        if not begun:record(s.begin_evaluation(first),f)
    return dict(symbol=symbol,bars=len(bars),counts=dict(counts),warmup_counts=dict(warm),
        reasons=[dict(event=e,reason=r,count=n) for (e,r),n in reasons.items()],plans=list(plans.values()))


def account(config,grouped,symbols,calendar,ends,first,last,universe):
    bars=sorted((b for sym in sorted(symbols) for b in grouped[sym]),key=lambda b:(b.date,b.symbol))
    return Backtest(copy.deepcopy(config),build_strategies(config['strategies'])).run(
        bars,calendar,ends,evaluation_start=first,evaluation_end=last,universe=universe)


def assert_recorded(path,actual):
    recorded=list(rows(path))
    assert len(recorded)==len(actual),(path.name,len(recorded),len(actual))
    for i,(a,b) in enumerate(zip(recorded,actual)):
        # CSV serialization from the same engine must preserve every populated field.
        for key,value in a.items():
            assert (str(b.get(key,'')) if b.get(key) is not None else '')==value,(path.name,i,key,value,b.get(key))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',default=str(ROOT/'runs/20261010-104630-mainboard-double_bottom_v5_11_2-structure'))
    parser.add_argument('--config',default=str(ROOT/'configs/experiments/double_bottom_v5_12_daily_direction_structure.json'))
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--output')
    parser.add_argument('--experiment',choices=('direction','support_zone','support_rebound','support_band'),default='direction')
    parser.add_argument('--test-log',default=str(ROOT/'runs/daily-direction-backtest-tests.log'))
    args=parser.parse_args();snapshot=Path(args.snapshot)
    config=json.loads(Path(args.config).read_text(encoding='utf-8'))
    # Projection relies on the fixed AutomaticPolicy's account-independent entry flags.
    assert config.get('research_scope')=='structure_only' and 'automatic_account_policy' in config
    assert len(config['strategies'])==1 and config['strategies'][0]['type']=='autonomous_double_bottom'
    assert config['strategies'][0]['params']['lower_cycle']=='daily_nested'
    assert config['execution'].get('entry_clock','daily')=='daily'
    now=datetime.now(ZoneInfo('Asia/Shanghai'))
    out=Path(args.output) if args.output else ROOT/'runs'/(now.strftime('%Y%m%d-%H%M%S')+'-mainboard-daily-direction')
    out.mkdir();(out/'signal-events').mkdir()
    shutil.copytree(ROOT/'src',out/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(ROOT/'run.py',out/'source/run.py');shutil.copy2(__file__,out/'source/backtest_daily_direction.py')
    shutil.copy2(Path(args.test_log),out/'tests.log')
    for name in ('calendar.json','universe.json','stocks.csv','coverage.csv'):
        if (snapshot/name).exists():shutil.copy2(snapshot/name,out/name)
    os.link(snapshot/'bars.csv',out/'bars.csv')
    dump(out/'config.json',config)
    cal=json.loads((out/'calendar.json').read_text(encoding='utf-8'))
    ud=json.loads((out/'universe.json').read_text(encoding='utf-8'))
    dates=cal['open_dates'];ends=set(cal['week_ends']);first='20251009';last='20260930'
    universe=MainboardUniverse(ud['stocks'],ud['st_by_date'])
    baseline_config=json.loads((snapshot/'config.json').read_text(encoding='utf-8'))
    left=copy.deepcopy(baseline_config);right=copy.deepcopy(config)
    left['strategies'][0].pop('id');right['strategies'][0].pop('id')
    if args.experiment=='direction':
        for key in ('direction_cycle','direction_retest_min','direction_retest_max'):right['strategies'][0]['params'].pop(key,None)
        assert left==right,'Only direction cycle, its explicit default durations and strategy ID may differ'
    elif args.experiment=='support_zone':
        params=right['strategies'][0]['params']
        assert params['support_mode']=='confirmed_trough' and params['stop_buffer']==0
        assert params['support_max_entry_risk']==.02
        for key in ('support_mode','support_max_entry_risk','stop_buffer'):
            params.pop(key)
            if key in left['strategies'][0]['params']:params[key]=left['strategies'][0]['params'][key]
        assert left==right,'Support experiment changes only support mode, fixed 2% entry limit, stop buffer and ID'
    elif args.experiment=='support_rebound':
        params=right['strategies'][0]['params']
        assert params.pop('entry_mode')=='support_rebound'
        assert left['strategies'][0]['params'].get('entry_mode','breakout')=='breakout'
        left['strategies'][0]['params'].pop('entry_mode',None)
        assert left==right,'Support rebound changes only entry timing and strategy ID from v5.13'
    else:
        params=right['strategies'][0]['params'];before=left['strategies'][0]['params']
        assert params.pop('entry_mode')=='support_band_retest'
        assert before.pop('entry_mode','breakout') in ('breakout','support_rebound')
        assert params['support_max_entry_risk']==.01
        params['support_max_entry_risk']=before.get('support_max_entry_risk',.02)
        for key,value in dict(support_band_atr_lookback=14,support_band_atr_fraction=.15,support_band_max_width=.005).items():
            assert params.pop(key)==value
            if key in before:params[key]=before[key]
        assert left==right,'Support band changes only its entry/stop rule, fixed buffer parameters and 1% entry-distance cap'
    data_hash=sha(out/'bars.csv')
    assert data_hash==json.loads((snapshot/'manifest.json').read_text(encoding='utf-8'))['bars_sha256']
    plan=dict(created_at=now.isoformat(),source_snapshot=str(snapshot.resolve()),bar_sha256=data_hash,
        universe_sha256=sha(out/'universe.json'),config_sha256=sha(out/'config.json'),
        evaluation_start=first,evaluation_end=last,workers=args.workers,parameter_tuning=False,experiment=args.experiment,
        population='all input stocks; dated mainboard and ST eligibility at signal and execution',
        method='independent all-stock signal scan; ordinary shared-account replay of every evaluation-signal stock',
        context='AutomaticPolicy entry flags are constant; account risk contraction remains in shared replay',
        diagnostics='signal-events/*.jsonl.gz contains every symbol; decisions.csv contains signal stocks plus account events',
        limitations=['previously studied snapshot, no independent holdout','daily substructures proxy for hourly entry','synthetic total-return factor share adjustment','daily OHLC conservative fills'])
    dump(out/'evaluation-plan.json',plan)
    dump(out/'status.json',dict(status='loading',stocks=3214))
    print(json.dumps(dict(output=str(out),status='loading'),ensure_ascii=True),flush=True)
    grouped=defaultdict(list)
    for r in rows(out/'bars.csv'):
        grouped[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    for history in grouped.values():
        history.sort(key=lambda b:b.date);validate(history)
    assert len(grouped)==3214 and sum(map(len,grouped.values()))==2856672
    # Verify the account projection against the full frozen weekly baseline first.
    weekly_symbols={r['symbol'] for r in rows(snapshot/'decisions.csv') if r['event']=='entry_intent'}
    dump(out/'status.json',dict(status='baseline_replay',stocks=3214,baseline_signal_stocks=len(weekly_symbols)))
    weekly=account(baseline_config,grouped,weekly_symbols,dates,ends,first,last,universe)
    weekly_check={}
    for name,actual in (('orders',weekly.orders),('trades',weekly.trades),('equity',weekly.curve),('entry_audit',weekly.entry_audits)):
        assert_recorded(snapshot/(name+'.csv'),actual);weekly_check[name]=True
    baseline_summary=json.loads((snapshot/'summary.json').read_text(encoding='utf-8'))
    assert weekly.summary()=={k:baseline_summary[k] for k in weekly.summary()}
    dump(out/'baseline-verification.json',dict(account_projection=weekly_check,summary=True,signal_symbols=len(weekly_symbols)))
    print(json.dumps(dict(status='baseline_verified',signal_symbols=len(weekly_symbols))),flush=True)
    totals=Counter();warmup=Counter();reasons=Counter();plans=[];results={};started=time.monotonic()
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize,
            initargs=(config,dates,ends,first,last,str(out))) as pool:
        futures=[pool.submit(scan,item) for item in sorted(grouped.items())]
        for index,future in enumerate(as_completed(futures),1):
            result=future.result();results[result['symbol']]=result
            totals.update(result['counts']);warmup.update(result['warmup_counts']);plans.extend(result['plans'])
            for r in result['reasons']:reasons[(r['event'],r['reason'])]+=r['count']
            if index%25==0 or index==len(grouped):
                state=dict(status='scanning',stocks_done=index,stocks=len(grouped),plans=len(plans),elapsed_seconds=round(time.monotonic()-started))
                dump(out/'status.json',state);print(json.dumps(state),flush=True)
    plans.sort(key=lambda p:(p['date'],p['symbol'],p['setup_id']))
    dump(out/'plans.json',plans)
    dump(out/'signal-counts.json',dict(evaluation=dict(totals),warmup=dict(warmup),
        reasons=[dict(event=e,reason=r,count=n) for (e,r),n in reasons.most_common()]))
    relevant={p['symbol'] for p in plans}
    state=dict(status='account_replay',stocks=len(results),plans=len(plans),signal_stocks=len(relevant))
    dump(out/'status.json',state);print(json.dumps(state),flush=True)
    engine=account(config,grouped,relevant,dates,ends,first,last,universe)
    # Recompute candidate signals in the unmodified shared-account engine.
    actual_plans={e['setup_id']:(e['first_planned_at'],e['trigger'],e['stop'],e['target']) for e in engine.events if e['event']=='entry_intent'}
    # Renewals can be factor adjusted: compare the immutable FIRST observation.
    actual_first={}
    for e in engine.events:
        if e['event']=='entry_intent':actual_first.setdefault(e['setup_id'],(e['date'],e['trigger'],e['stop'],e['target']))
    assert actual_first=={p['setup_id']:(p['date'],p['trigger'],p['stop'],p['target']) for p in plans}
    account_counts=Counter(e['event'] for e in engine.events)
    for sym in relevant:account_counts.subtract(results[sym]['counts'])
    assert all(n>=0 for n in account_counts.values()),account_counts
    summary=engine.summary();summary['event_counts']=dict(totals+account_counts)
    summary['rejection_counts']=dict(Counter(e.get('reason') for e in engine.events if e['event'] in ('plan_rejected','entry_rejected')))
    for name,records in (('decisions',engine.events),('warmup_decisions',engine.warmup_events),('orders',engine.orders),('trades',engine.trades),('equity',engine.curve),('entry_audit',engine.entry_audits)):
        save_csv(out/(name+'.csv'),records)
    dump(out/'summary.json',summary)
    dump(out/'account-verification.json',dict(all_population_scanned=len(results)==3214,bar_count=sum(r['bars'] for r in results.values()),
        signal_stock_count=len(relevant),unique_plans=len(plans),first_plan_id_date_price_match=True,baseline_projection_verified=True))
    digest=hashlib.sha256()
    for p in sorted((out/'source/src').rglob('*.py')):
        digest.update(str(p.relative_to(out/'source/src')).encode());digest.update(p.read_bytes())
    manifest=dict(plan,stocks=len(grouped),bar_count=sum(map(len,grouped.values())),sessions=len(engine.curve),
        first_session=engine.curve[0]['date'],last_session=engine.curve[-1]['date'],rule_version=config['strategies'][0]['id'],
        bars_sha256=data_hash,code_sha256=digest.hexdigest(),production_promoted=False)
    dump(out/'manifest.json',manifest)
    comparison=(dict(weekly=dict(path=str(snapshot),summary=baseline_summary),daily=dict(path=str(out),summary=summary))
                if args.experiment=='direction' else
                dict(baseline=dict(path=str(snapshot),summary=baseline_summary),candidate=dict(path=str(out),summary=summary)))
    dump(out/'comparison.json',comparison)
    dump(out/'status.json',dict(status='complete',stocks=len(results),plans=len(plans),buys=summary['filled_buys']))
    print(json.dumps(dict(status='complete',output=str(out),summary=summary),ensure_ascii=True),flush=True)


if __name__=='__main__':main()
