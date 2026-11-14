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
    previous=load(snapshot/'plans.json');symbols={p['symbol'] for p in previous}
    assert len(previous)==68 and len(symbols)==62
    config=load(ROOT/'configs/experiments/double_bottom_v5_16_stop_only_structure.json')
    baseline=load(snapshot/'config.json')
    a=copy.deepcopy(config);b=copy.deepcopy(baseline)
    a['strategies'][0].pop('id');b['strategies'][0].pop('id')
    assert a['strategies'][0]['params'].pop('entry_mode')=='support_rebound'
    assert a['strategies'][0]['params'].pop('support_tighten') is True
    assert a==b
    out.mkdir();shutil.copytree(ROOT/'src',out/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(__file__,out/'source/verify_support_rebound.py')
    shutil.copy2(ROOT/'scripts/backtest_daily_direction.py',out/'source/backtest_daily_direction.py')
    shutil.copy2(ROOT/'runs/support-rebound-tests.log',out/'tests.log')
    dump(out/'symbols.json',sorted(symbols))
    for name in ('calendar.json','universe.json'):shutil.copy2(snapshot/name,out/name)
    cal=load(snapshot/'calendar.json');u=load(snapshot/'universe.json')
    universe=MainboardUniverse(u['stocks'],u['st_by_date'])
    plan=dict(scope='fixed previous-signal cohort diagnostic; NOT full population',
              full_population_scanned=False,symbols=len(symbols),selection='all 62 symbols from v5.13 first plans; fixed before v5.14 replay',
              evaluation_start='20251009',evaluation_end='20260930',independent_holdout=False,
              changed_rules=['bullish recovery near confirmed support instead of old swing-high breakout',
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
        assert_recorded(snapshot/(name+'.csv'),records)
    expected=load(snapshot/'summary.json');assert old.summary()=={k:expected[k] for k in old.summary()}
    new=run(config,'candidate')
    first=[e for e in new.events if e['event']=='entry_intent']
    assert len({e['setup_id'] for e in first})==len(first)
    for e in first:
        assert e['support_source_date']<e['support_known_at']<=e['rebound_confirmed_at']==e['date']
        assert e['entry_order']=='next_open' and e['trigger']==e['rebound_signal_close']
        assert (e['trigger']-e['stop'])/e['trigger']<=.02+1e-12
    buys=[r for r in new.entry_audits if r['execution_reason']=='filled']
    for r in buys:
        assert r['signal_date']<r['date']
        assert math.isclose(r['fill'],r['open']*1.001,rel_tol=1e-12)
        assert r['support_entry_distance']<=.02+1e-12 and r['net_rr']>3
    assert not any(e['event']=='entry_plan_renewed' for e in new.events)
    dump(out/'plans.json',first)
    metrics=dict(baseline=old.summary(),candidate=new.summary(),first_plans=len(first),
        first_plans_below_old_breakout=sum(e['trigger']<e['breakout_reference'] for e in first),
        actual_fills_below_old_breakout=sum(r['fill']<r['breakout_reference'] for r in buys),
        risk_reasons=dict(Counter(r['risk_reason'] for r in new.entry_audits)),
        execution_reasons=dict(Counter(r['execution_reason'] for r in new.entry_audits)))
    checks=dict(baseline_recorded_account_exactly_reproduced=True,causal_signal_plans=len(first),
        next_open_and_risk_checked_fills=len(buys),no_renewal_or_chase=True,full_population_scanned=False)
    dump(out/'comparison.json',metrics);dump(out/'verification.json',checks)
    digest=hashlib.sha256()
    for path in sorted((out/'source/src').rglob('*.py')):
        digest.update(str(path.relative_to(out/'source/src')).encode());digest.update(path.read_bytes())
    dump(out/'manifest.json',dict(plan,bar_count=len(bars),source_code_sha256=digest.hexdigest(),
        bars_sha256=hashlib.sha256((out/'bars.csv').read_bytes()).hexdigest(),production_promoted=False))
    lines=['# 支撑附近止跌入场：固定样本核验','',
        '本次仅核验上轮 68 个计划对应的 62 只股票，使用同一冻结行情、日历、历史资格和共享账户。不是新策略的全市场回测，样本曾用于研究，不能用来估计稳定收益。','',
        '| 指标 | v5.13 原突破入场 | v5.14 止跌确认入场 |','|---|---:|---:|']
    for key,label in [('filled_buys','买入笔数'),('closed_trades','平仓笔数'),('open_positions','期末持仓'),('total_return','账户收益'),('max_drawdown','最大回撤')]:
        values=[metrics[v][key] for v in ('baseline','candidate')]
        rendered=[f'{x:.2%}' if key in ('total_return','max_drawdown') else str(x) for x in values]
        lines.append('| '+label+' | '+' | '.join(rendered)+' |')
    lines+=['',f"新版本生成 {len(first)} 个首次计划，{metrics['first_plans_below_old_breakout']} 个计划参考价低于原小 N 突破价；{metrics['actual_fills_below_old_breakout']} 笔买入成交价低于其原突破参考价。",'',
        '止跌确认要求已确认回踩低点、下沿未再次触及、当日收阳且收盘高于前收、距下沿不超过 2%。收盘后形成信号，下一交易日开盘执行；跳空重新检查 2% 距离、含费用净盈亏比 > 3、资金和仓位。一次执行失败不延续挂单。','',
        '开盘成交后当天再触及支撑的交易保留，记录 T+1 延后退出。日线数据只能模拟这些执行条件，不能证明秒级成交。','',
        '原 v5.13 委托、平仓、审核、每日净值和汇总精确复现；新计划确认日期、下一交易日开盘成交价和风险门槛逐项核验。','',
        '详细记录见 candidate/decisions.csv、candidate/entry_audit.csv、candidate/trades.csv、plans.json 和 verification.json。']
    (out/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(phase='complete',metrics=metrics,verification=checks),ensure_ascii=True),flush=True)


if __name__=='__main__':main()
