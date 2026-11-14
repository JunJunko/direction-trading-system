"""Fixed previous-signal cohort comparison; not a new full-market backtest."""
import argparse
import copy
import csv
import hashlib
import json
import math
import shutil
import sys
from collections import Counter,defaultdict
from dataclasses import asdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Bar
from trading_system.data import save_csv,validate
from trading_system.engine import Backtest
from trading_system.strategies import build_strategies
from trading_system.universe import MainboardUniverse
from backtest_daily_direction import assert_recorded


def load(p):return json.loads(p.read_text(encoding='utf-8'))
def dump(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',default=str(ROOT/'runs/20261022-mainboard-support-zone'))
    parser.add_argument('--output',required=True)
    args=parser.parse_args();snapshot=Path(args.snapshot);out=Path(args.output)
    cohort=ROOT/'runs/20261023-support-rebound-cohort-verified'
    previous=load(snapshot/'plans.json');symbols={p['symbol'] for p in previous}
    assert len(previous)==68 and len(symbols)==62
    config=load(ROOT/'configs/experiments/double_bottom_v5_17_direct_w_structure.json')
    baseline=load(cohort/'candidate/config.json')
    out.mkdir();shutil.copytree(ROOT/'src',out/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(__file__,out/'source/verify_direct_w.py')
    shutil.copy2(ROOT/'scripts/backtest_daily_direction.py',out/'source/backtest_daily_direction.py')
    shutil.copy2(ROOT/'runs/direct-w-tests.log',out/'tests.log')
    dump(out/'symbols.json',sorted(symbols))
    for name in ('calendar.json','universe.json'):shutil.copy2(snapshot/name,out/name)
    cal=load(snapshot/'calendar.json');u=load(snapshot/'universe.json')
    universe=MainboardUniverse(u['stocks'],u['st_by_date'])
    plan=dict(scope='fixed previous-signal cohort diagnostic; NOT full population',
              full_population_scanned=False,symbols=len(symbols),selection='all 62 symbols from v5.13 first plans; fixed before v5.14 replay',
              evaluation_start='20251009',evaluation_end='20260930',independent_holdout=False,
              changed_rules=['one W closing neckline breakout; structural W floor; measured W target',
                             'single next-session open order, re-audited at executable price'],
              same_day_stop='keep actual next-open entry; latch subsequent support touch and defer sale under T+1')
    dump(out/'evaluation-plan.json',plan)
    print(json.dumps(dict(phase='loading',symbols=len(symbols))),flush=True)
    grouped=defaultdict(list)
    with (snapshot/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):
            if row['symbol'] not in symbols:continue
            grouped[row['symbol']].append(Bar(row['symbol'],row['date'],**{k:float(row[k]) for k in
                ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    assert set(grouped)==symbols
    for bars in grouped.values():bars.sort(key=lambda b:b.date);validate(bars)
    bars=sorted((bar for group in grouped.values() for bar in group),key=lambda b:(b.date,b.symbol))
    save_csv(out/'bars.csv',[asdict(bar) for bar in bars])
    def run(c,label):
        folder=out/label;folder.mkdir();dump(folder/'config.json',c)
        def progress(state):
            if state['session']%100==0:print(json.dumps(dict(phase=label,**state)),flush=True)
        e=Backtest(copy.deepcopy(c),build_strategies(c['strategies'])).run(bars,cal['open_dates'],set(cal['week_ends']),
            evaluation_start=plan['evaluation_start'],evaluation_end=plan['evaluation_end'],universe=universe,progress=progress)
        for name,records in (('decisions',e.events),('orders',e.orders),('trades',e.trades),('entry_audit',e.entry_audits),('equity',e.curve)):
            save_csv(folder/(name+'.csv'),records)
        dump(folder/'summary.json',e.summary())
        return e
    old=run(baseline,'baseline')
    for name,records in (('orders',old.orders),('trades',old.trades),('entry_audit',old.entry_audits),('equity',old.curve)):
        assert_recorded(cohort/'candidate'/(name+'.csv'),records)
    expected=load(cohort/'candidate/summary.json');assert old.summary()=={k:expected[k] for k in old.summary()}
    new=run(config,'candidate')
    first=[e for e in new.events if e['event']=='entry_intent']
    assert len({e['setup_id'] for e in first})==len(first)
    dump(out/'plans.json',first)
    dump(out/'comparison.json',dict(baseline=old.summary(),candidate=new.summary(),first_plans=len(first),
        risk_reasons=dict(Counter(r['risk_reason'] for r in new.entry_audits))))
    print(json.dumps(dict(phase='complete',baseline=old.summary(),candidate=new.summary(),plans=len(first))))


if __name__=='__main__':main()
