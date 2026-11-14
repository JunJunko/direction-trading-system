"""Fixed-plan barrier diagnostics, distinct from realized strategy win rate."""
import argparse
import csv
import hashlib
import json
import math
import shutil
import sys
from collections import Counter,defaultdict
from dataclasses import asdict,replace
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Bar
from trading_system.data import save_csv
from trading_system.universe import MainboardUniverse


def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def load(path):return json.loads(path.read_text(encoding='utf-8'))
def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def normalized(bar,factor):
    scale=bar.factor/factor
    return replace(bar,**{k:getattr(bar,k)*scale for k in ('open','high','low','close','up_limit','down_limit')})


def barrier_hit(bar,stop,target):
    """Open is ordered; inside-bar high/low order is unknown."""
    if bar.volume<=0:return None
    if bar.open<=stop:return 'stop_first'
    if bar.open>=target:return 'target_first'
    low=bar.low<=stop;high=bar.high>=target
    if low and high:return 'ambiguous_exit_bar'
    if low:return 'stop_first'
    if high:return 'target_first'
    return None


def evaluate(plan,observations,history,calendar,execution,universe=None,end='20260930'):
    """No assumed admission: historical signal validity plus feasible first touch.

    Capital, proximity and RR gates are deliberately bypassed. Stops/targets
    remain fixed after entry. A price hit is NOT an executed sale or net profit.
    """
    symbol=plan['symbol'];factor=plan['evidence']['factor']
    raw={b.date:b for b in history};bars={d:normalized(b,factor) for d,b in raw.items()}
    dates={d:i for i,d in enumerate(calendar)}
    result=dict(setup_id=plan['setup_id'],symbol=symbol,signal_date=plan['date'],
        trigger=plan['trigger'],stop=plan['stop'],target=plan['target'],
        status='not_triggered',entry_date='',entry_price=None,hit_date='',
        hit_on_entry_day=False,hit_locked_limit=False)
    relevant=[o for o in observations if o['setup_id']==plan['setup_id']]
    eligible_observations=0;execution_eligible=0;entry=None
    for obs in sorted(relevant,key=lambda o:o['date']):
        signal=obs['date']
        assert signal>=plan['date']
        # Recorded renewals carry corporate-action-adjusted levels.
        if signal in raw:
            scale=raw[signal].factor/factor
            for key in ('trigger','stop','target'):
                assert math.isclose(float(obs[key])*scale,plan[key],rel_tol=1e-11,abs_tol=1e-11)
        if universe and not universe.eligible(symbol,signal):continue
        eligible_observations+=1
        index=dates[signal]+1
        if index>=len(calendar) or calendar[index]>end:continue
        date=calendar[index]
        if universe and not universe.eligible(symbol,date):continue
        execution_eligible+=1
        b=bars.get(date)
        if not b or b.volume<=0:continue
        if b.low<=plan['stop']:
            result['status']='ambiguous_entry_bar' if b.high>=plan['trigger'] else 'support_broken_before_trigger'
            result['hit_date']=date
            return result
        if b.high<plan['trigger']:continue
        fill=max(b.open,plan['trigger'])*(1+execution['slippage'])
        if b.up_limit and fill>=b.up_limit-.00001:
            result.update(status='entry_blocked_limit_up',hit_date=date);return result
        if fill>b.high:
            result.update(status='entry_slippage_outside_bar',hit_date=date);return result
        if not plan['stop']<fill<plan['target']:
            result.update(status='entry_gap_exhausted_target',hit_date=date);return result
        entry=b
        result.update(status='unresolved_at_sample_end',entry_date=date,entry_price=fill)
        break
    if entry is None:
        if not eligible_observations:result['status']='signal_universe_ineligible'
        elif not execution_eligible:result['status']='execution_universe_ineligible_or_no_future_session'
        return result
    # Trigger was reached with the entry day's low strictly above the stop.
    # A target hit that day is observable, but T+1 prevents an actual same-day sale.
    for date in sorted(d for d in bars if entry.date<=d<=end):
        b=bars[date]
        outcome=barrier_hit(b,plan['stop'],plan['target'])
        if outcome:
            result.update(status=outcome,hit_date=date,hit_on_entry_day=date==entry.date,
                hit_locked_limit=bool(b.down_limit and b.high<=b.down_limit+.00001)
                if outcome=='stop_first' else bool(b.up_limit and b.low>=b.up_limit-.00001))
            return result
    return result


def summarize(records):
    counts=Counter(r['status'] for r in records)
    wins=counts['target_first'];losses=counts['stop_first'];ambiguous=counts['ambiguous_exit_bar']
    definite=wins+losses;resolved=definite+ambiguous
    entries=sum(bool(r['entry_date']) for r in records)
    return dict(plans=len(records),triggered_executable_entries=entries,status_counts=dict(counts),
        target_first=wins,stop_first=losses,ambiguous_exit=ambiguous,
        determinate_outcomes=definite,target_first_rate=wins/definite if definite else None,
        target_first_fraction_all_plans=wins/len(records) if records else None,
        ambiguous_order_lower_rate=wins/resolved if resolved else None,
        ambiguous_order_upper_rate=(wins+ambiguous)/resolved if resolved else None,
        target_hits_on_entry_day=sum(r['status']=='target_first' and r['hit_on_entry_day'] for r in records),
        hit_blocked_limit_count=sum(r['hit_locked_limit'] for r in records))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args();out=Path(args.output);out.mkdir()
    snapshots=dict(original=ROOT/'runs/20261022-mainboard-daily-direction',
                   support=ROOT/'runs/20261022-mainboard-support-zone')
    plan_sets={key:load(path/'plans.json') for key,path in snapshots.items()}
    assert all(len(p)==68 for p in plan_sets.values())
    identity=lambda p:(p['symbol'],p['date'],p['setup_id'].split(':',1)[1])
    assert {identity(p) for p in plan_sets['original']}=={identity(p) for p in plan_sets['support']}
    symbols={p['symbol'] for p in plan_sets['original']}
    source=snapshots['support'];calendar=load(source/'calendar.json')['open_dates']
    u=load(source/'universe.json');universe=MainboardUniverse(u['stocks'],u['st_by_date'])
    bars=defaultdict(list)
    with (source/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] not in symbols:continue
            bars[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in
                ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    for history in bars.values():history.sort(key=lambda b:b.date)
    protocol=dict(type='counterfactual fixed-plan price-hit diagnostic',population=68,
        entry_validity='only next-session orders after recorded entry_intent or entry_plan_renewed',
        bypassed=['2% proximity filter','minimum RR','capital and portfolio constraints'],
        retained=['historical signal/execution eligibility','first-trigger consumption','buy slippage','limit-up tradability','entry-bar order ambiguity'],
        exit='fixed initial target vs fixed initial stop; no strategy exits or trailing stops',
        denominator='target_first / (target_first + stop_first); ambiguous and unresolved separate',
        end='20260930',prices='future outcomes normalized to the signal-day factor; no future factors used to change past signals',
        not_actual_win_rate=True,same_day_target='counts only a price hit; T+1 sale is not simulated')
    dump(out/'protocol.json',protocol)
    shutil.copy2(__file__,out/'source-plan_hit_rate.py')
    summaries={}
    for key,snapshot in snapshots.items():
        observations=[r for r in read(snapshot/'decisions.csv') if r['event'] in ('entry_intent','entry_plan_renewed')]
        cfg=load(snapshot/'config.json')
        records=[evaluate(p,observations,bars[p['symbol']],calendar,cfg['execution'],universe) for p in plan_sets[key]]
        summaries[key]=summarize(records)
        save_csv(out/(key+'-plans.csv'),records)
        dump(out/(key+'-plans.json'),records)
        assert sum(summaries[key]['status_counts'].values())==68
    dump(out/'summary.json',summaries)
    actual={}
    for label,path in [('original_68_plan_strategy',snapshots['original']),('support_68_plan_strategy',snapshots['support']),
                       ('new_rebound_fixed_cohort',ROOT/'runs/20261023-support-rebound-cohort-verified/candidate')]:
        trades=read(path/'trades.csv');wins=sum(float(r['pnl'])>0 for r in trades)
        actual[label]=dict(closed_trades=len(trades),wins=wins,losses=sum(float(r['pnl'])<0 for r in trades),
                           realized_win_rate=wins/len(trades) if trades else None)
    dump(out/'actual-trade-rates.json',actual)
    lines=['# 68 个结构计划：目标先到率统计','',
        '这是原 68 个突破计划的事后固定目标/止损诊断，暂不应用盈亏比、2% 距离和资金过滤；保留原计划实际有效日期、历史股票资格和可观察入场条件。没有将已知不能入场的机会硬算成亏损或盈利。','',
        '| 指标 | 原 v5.12 止损 | v5.13 支撑下沿止损 |','|---|---:|---:|']
    for field,label in [('plans','首次计划'),('triggered_executable_entries','假设可触发入场'),('target_first','目标先到'),('stop_first','止损先到'),
                        ('ambiguous_exit','同日双触及顺序不明'),('target_first_rate','明确结果中的目标先到率'),('target_hits_on_entry_day','其中入场当日目标触及')]:
        values=[summaries[k][field] for k in ('original','support')]
        rendered=[f'{v:.2%}' if field=='target_first_rate' and v is not None else str(v) for v in values]
        lines.append('| '+label+' | '+' | '.join(rendered)+' |')
    lines+=['','## 全部状态','',json.dumps({k:s['status_counts'] for k,s in summaries.items()},ensure_ascii=False,indent=2),'',
        '目标先到率的分母只含入场后先触及某一边且先后明确的计划；未触发、入场失效、同日顺序不明及期末未决分别列出。它不代表 68 个计划实际成交后的净利润胜率。入场当日目标触及也不代表当日能够卖出；另未模拟持仓结构退出、移动止损、退出滑点和手续费。','',
        '实际账户已平仓胜率：原 v5.12 为 0/1 = 0%；v5.13 零成交，胜率未定义；新 v5.14 固定样本为 3/4 = 75%，对应 9 个新计划，不能作为旧 68 计划的胜率。','',
        '逐项明细见 original-plans.csv、support-plans.csv；全部统计口径见 protocol.json。']
    (out/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    dump(out/'input-hashes.json',{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
        for snapshot in snapshots.values() for path in (snapshot/'plans.json',snapshot/'decisions.csv')})
    print(json.dumps(dict(summary=summaries,actual=actual),ensure_ascii=True))


if __name__=='__main__':main()
