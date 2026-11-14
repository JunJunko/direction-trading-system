"""Frozen daily-proxy diagnosis and one preregistered causal entry contrast.

No invented intraday bars; no production changes. Selected-stock cohort is fixed
by previous structural plans, not their realized returns. Baseline account must
reproduce the completed experiment before interpreting the diagnostic contrast.
"""
import argparse
import copy
import csv
import hashlib
import json
import statistics
import sys
import time
from collections import Counter,defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from ablation_rules import FrozenUpper,bind_entry,bind_replay,entry_method,holding_method
from run_rule_ablation import equal_rows
from audit_reward_risk import cash_flows,sha,dump,read_json


def recovery_candidate(bars, small):
    """A causal alternative, not an equivalence claim about the book's rhythm.

    Same qualified A/B/C and floor. Observe recovery through the previous bar,
    then submit a next-session stop buy above the completed recovery bar's high.
    Use only if this trigger is below the original small-B trigger. No right=0.
    """
    if small is None or len(bars)<2:return None
    last,previous=bars[-1],bars[-2]
    if (last.close>previous.high and last.close>last.open
            and last.low>=previous.low and last.high<small['trigger']):
        return dict(small,trigger=last.high)
    return None


def plan_metrics(p, raw, config, risk_class):
    e=p['evidence'];known=[x for x in raw if x.date<=p['date']]
    index={x.date:i for i,x in enumerate(known)};factor=known[-1].factor
    def price(date,key):
        b=known[index[date]];return getattr(b,key)*b.factor/factor
    a,b,c=[price(e[k],key) for k,key in [('core_a','low'),('core_b','high'),('core_c','low')]]
    sb,sc=price(e['small_b'],'high'),price(e['small_c'],'low')
    rr=(p['target']-p['trigger'])/(p['trigger']-p['stop'])
    slip=config['execution']['slippage']
    from trading_system.domain import Intent
    assessment=risk_class(config['risk']).assess(Intent(**p),p['trigger']*(1+slip),
        config['initial_cash'],config['initial_cash'],{}, {},
        config['execution']['commission_rate'],config['execution']['sell_tax_after_20230828'],slippage=slip)
    newer=[]
    # Confirmed after selected C, intact through this decision. Never use lows
    # from the future or raise a stop to a prior low already violated.
    from trading_system.structure import swings
    from trading_system.analysis import adjusted
    adjusted_bars=adjusted(known)
    for low in swings(adjusted_bars,1,1):
        if (known[low.index].date>e['small_c'] and low.price>sc
                and min(x.low for x in adjusted_bars[low.index:])>=low.price):
            newer.append(dict(date=known[low.index].date,confirmed=known[low.confirmed].date,price=low.price))
    confirmation=index[e['small_confirmed']];ci=index[e['small_c']]
    impulse=b-a
    return dict(setup_id=p['setup_id'],symbol=p['symbol'],plan_date=p['date'],
        core_a=e['core_a'],core_b=e['core_b'],core_c=e['core_c'],core_accepted=e['core_accepted_at'],
        small_a=e['small_a'],small_b=e['small_b'],small_c=e['small_c'],small_confirmed=e['small_confirmed'],
        pivot_confirmation_bars=confirmation-ci,post_confirmation_wait_bars=len(known)-1-confirmation,
        core_accept_after_confirmation_bars=index[e['core_accepted_at']]-index[e['core_c_confirmed']],
        core_c_to_small_c_bars=ci-index[e['core_c']],
        trigger=p['trigger'],stop=p['stop'],target=p['target'],gross_rr=rr,
        standalone_net_rr=assessment.get('net_rr'),standalone_risk_reason=assessment['risk_reason'],
        standalone_quantity=assessment['quantity'],core_c_price=c,core_b_price=b,
        small_b_price=sb,small_c_price=sc,
        small_to_core_correction_range=(sb-sc)/(b-c),
        small_to_core_correction_duration=(ci-index[e['small_b']])/e['correction_duration'],
        stop_distance_pct=(p['trigger']-p['stop'])/p['trigger'],
        consumed_projection_fraction=(p['trigger']-c)/impulse,
        uncapped_remaining_fraction=(e['symmetry_target']-p['trigger'])/impulse,
        required_stop_for_gross_3=p['trigger']-(p['target']-p['trigger'])/3,
        higher_confirmed_intact_floors=newer)


def summary_metrics(rows):
    return dict(plans=len(rows),gross_rr_above_3=sum(r['gross_rr']>3 for r in rows),
        standalone_net_rr_approved=sum(r['standalone_quantity']>0 for r in rows),
        pivot_confirmation_bars=dict(Counter(r['pivot_confirmation_bars'] for r in rows)),
        post_confirmation_wait_bars=dict(Counter(r['post_confirmation_wait_bars'] for r in rows)),
        core_accept_lag_bars=dict(Counter(r['core_accept_after_confirmation_bars'] for r in rows)),
        median_small_to_core_range=statistics.median(r['small_to_core_correction_range'] for r in rows),
        median_small_to_core_duration=statistics.median(r['small_to_core_correction_duration'] for r in rows),
        median_stop_distance_pct=statistics.median(r['stop_distance_pct'] for r in rows),
        median_consumed_projection=statistics.median(r['consumed_projection_fraction'] for r in rows),
        plans_with_newer_known_floor=sum(bool(r['higher_confirmed_intact_floors']) for r in rows))


def main(experiment,output):
    experiment,output=experiment.resolve(),output.resolve()
    if output==experiment or experiment in output.parents:raise ValueError('Output overlaps frozen inputs')
    output.mkdir(parents=True,exist_ok=False)
    frozen=experiment/'frozen-baseline'
    sys.path.insert(0,str(frozen/'source/src'))
    from trading_system.strategies import direction_double_bottom as dm,autonomous_double_bottom as am
    from trading_system import wave_hierarchy as wm
    from trading_system.analysis import AdjustedCache
    from trading_system.structure import SwingCache
    from trading_system.domain import Bar
    from trading_system.risk import RiskManager
    from trading_system.engine import Backtest
    from trading_system.data import save_csv
    from trading_system.universe import MainboardUniverse
    config=read_json(frozen/'config.json');cal=read_json(frozen/'calendar.json')
    ud=read_json(frozen/'universe.json');comparison=read_json(experiment/'comparison.json')
    all_plans={v:read_json(experiment/v/'plans.json') for v in ('baseline','E01','E03')}
    # Includes every baseline stock plus all stocks restored by these two
    # pre-existing structural ablations, regardless of subsequent returns.
    cohort={p['symbol'] for ps in all_plans.values() for p in ps}
    plan=dict(created_at=datetime.now().isoformat(),experiment=str(experiment),cohort=sorted(cohort),
        selection='All stocks with a structural plan in frozen baseline, E01 or E03; no return-based selection',
        diagnosis=['C confirmation lag','additional post-confirmation/core wait','stop scale','projection consumed'],
        contrast='D01: same qualified ABC, close recovers prior high, nonfalling low, bullish recovery; next-session break above recovery-bar high only when below original B',
        fixed=['weekly tape','core and small N qualification','confirmation delays','C stop and buffers',
               'target/pressure formula','risk and execution','holding management','calendar/universe'],
        rejection_lifecycle='Identical single-use setup ID and plan-before-fill conventions',
        limitations=['Previously studied, selected-stock cohort; not a new full-market evaluation',
                     'D01 changes entry meaning; cannot prove hourly superiority',
                     'No actual intraday data in frozen snapshot; no fabricated hourly bars'],
        production_promoted=False)
    dump(output/'evaluation-plan.json',plan)
    inputs=[frozen/'bars.csv',frozen/'config.json',frozen/'calendar.json',frozen/'universe.json',
            frozen/'decisions.csv',frozen/'warmup_decisions.csv']
    inputs += [experiment/v/'plans.json' for v in all_plans]
    before={str(p.relative_to(experiment)):sha(p) for p in inputs}
    dump(output/'input-hashes.json',before)
    grouped=defaultdict(list);count=0
    with (frozen/'bars.csv').open(encoding='utf-8-sig',newline='') as stream:
        for r in csv.DictReader(stream):
            count+=1
            if r['symbol'] in cohort:
                grouped[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in
                    ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    for history in grouped.values():history.sort(key=lambda b:b.date)
    dates=cal['open_dates'];ends=set(cal['week_ends']);first=next(d for d in dates if d>='20251008')
    upper_events=defaultdict(list)
    for name in ('decisions.csv','warmup_decisions.csv'):
        with (frozen/name).open(encoding='utf-8-sig',newline='') as stream:
            for r in csv.DictReader(stream):
                if r['symbol'] in cohort and r['event'] in ('upper_direction_confirmed','upper_direction_lost'):
                    upper_events[r['symbol'],r['date']].append({k:v for k,v in r.items() if v!=''})
    upper=FrozenUpper(upper_events)
    params=config['strategies'][0]['params'];name=config['strategies'][0]['id']
    tapes={v:{} for v in ('baseline','D01')};plans={v:{} for v in tapes}
    trace=[];methods={v:entry_method(dm,wm,None) for v in tapes}
    # The baseline callback only observes and returns the original object.
    for vid,method in methods.items():
        original=method.__globals__['rhythm']
        def observer(bars,core,*args,_original=original,_vid=vid,**kwargs):
            small,reason=_original(bars,core,*args,**kwargs)
            if small and bars[-1].date>=first:
                trace.append(dict(variant=_vid,symbol=bars[-1].symbol,date=bars[-1].date,
                    core_owner=core['owner_id'],small_a=small['a_date'],small_b=small['b_date'],
                    small_c=small['date'],small_confirmed=small['confirmed_date'],
                    original_trigger=small['trigger'],stop_floor=small['stop'],
                    recovery_qualified=recovery_candidate(bars,small) is not None))
            if _vid=='D01':
                recovered=recovery_candidate(bars,small)
                return recovered,reason if recovered else 'diagnostic_recovery_bar_wait'
            return small,reason
        method.__globals__['rhythm']=observer
    start=time.monotonic()
    for index,symbol in enumerate(sorted(cohort)):
        shared_daily={symbol:AdjustedCache()};shared_core={symbol:SwingCache(2,2)};shared_small={symbol:SwingCache(1,1)}
        strategies={}
        for vid in tapes:
            s=am.AutonomousDoubleBottom(name,params);s.set_calendar(dates)
            s.set_context(dict(allow_same_level=False,allow_cycle_upgrade=False,lower_histories={}))
            s.daily_caches=shared_daily;s.core_swings=shared_core;s.rhythm_swings=shared_small
            strategies[vid]=bind_entry(s,methods[vid],upper)
        history=[];begun=False
        for bar in grouped[symbol]:
            if bar.date>'20261007':break
            if bar.date>=first and not begun:
                for vid,s in strategies.items():
                    tapes[vid].setdefault(('BEGIN',first),([],[]))[1].extend(s.begin_evaluation(first))
                begun=True
            history.append(bar)
            for vid,s in strategies.items():
                new,events=s.on_close(history,ends)
                if bar.date<first:continue
                if new:
                    if vid=='D01':
                        for intent in new:intent.evidence.update(diagnostic_entry_rule='recovery_bar_high',
                            recovery_date=intent.evidence['first_planned_at'])
                    tapes[vid][symbol,bar.date]=(copy.deepcopy(new),copy.deepcopy(events))
                    for intent in new:plans[vid].setdefault(intent.setup_id,asdict(intent))
        if index%10==0 or index+1==len(cohort):
            progress=dict(status='generating',stocks_done=index+1,cohort_size=len(cohort),
                elapsed_seconds=round(time.monotonic()-start),plans={v:len(p) for v,p in plans.items()})
            dump(output/'status.json',progress);print(json.dumps(progress),flush=True)
    expected={p['setup_id']:p for p in all_plans['baseline']}
    assert set(expected)==set(plans['baseline']),('Baseline setup mismatch',len(expected),len(plans['baseline']))
    for sid,p in expected.items():
        for key in ('date','trigger','stop','target','evidence'):
            assert p[key]==plans['baseline'][sid][key],(sid,key)
    results={};holding=holding_method(am,None)
    for vid in tapes:
        folder=output/vid;folder.mkdir();dump(folder/'plans.json',list(plans[vid].values()))
        strategy=bind_replay(am.AutonomousDoubleBottom(name,params),tapes[vid],upper,holding)
        engine=Backtest(copy.deepcopy(config),[strategy]).run(
            [b for history in grouped.values() for b in history],dates,ends,
            evaluation_start='20251008',evaluation_end='20261007',universe=MainboardUniverse(ud['stocks'],ud['st_by_date']))
        if vid=='baseline':
            for label,actual in [('orders',engine.orders),('trades',engine.trades),('equity',engine.curve),('entry_audit',engine.entry_audits)]:
                equal_rows(experiment/'baseline'/(label+'.csv'),actual,label)
        for label,actual in [('orders',engine.orders),('trades',engine.trades),('equity',engine.curve),('entry_audit',engine.entry_audits),('decisions',engine.events)]:
            save_csv(folder/(label+'.csv'),actual)
        metrics=[plan_metrics(p,grouped[p['symbol']],config,RiskManager) for p in plans[vid].values()]
        dump(folder/'plan-metrics.json',metrics)
        account=engine.summary();dump(folder/'summary.json',account)
        results[vid]=dict(**summary_metrics(metrics),account=account,
            net_pnl=account['final_equity']-account['initial_cash'])
        print(vid,json.dumps(results[vid],ensure_ascii=False),flush=True)
    # Existing restored plans are an audit population, not another optimized rule.
    metrics={v:[plan_metrics(p,grouped[p['symbol']],config,RiskManager) for p in ps] for v,ps in all_plans.items()}
    dump(output/'prior-plan-metrics.json',metrics);dump(output/'causal-observations.json',trace)
    by_identity=defaultdict(list)
    for r in trace:
        if r['variant']=='baseline':by_identity[r['symbol'],r['core_owner'],r['small_a'],r['small_b'],r['small_c']].append(r)
    timing=[]
    for p in all_plans['baseline']:
        e=p['evidence'];observed=by_identity[p['symbol'],e['entry_core_owner'],e['small_a'],e['small_b'],e['small_c']]
        earlier=[r for r in observed if r['date']<=p['date']]
        assert earlier,(p['setup_id'],'No causal selected-core observation')
        timing.append(dict(setup_id=p['setup_id'],symbol=p['symbol'],plan_date=p['date'],
            first_same_abc_with_selected_core=min(r['date'] for r in earlier),
            observed_before_plan=any(r['date']<p['date'] for r in earlier)))
    dump(output/'causal-timing.json',timing)
    common=set(plans['baseline'])&set(plans['D01'])
    paired=[]
    for sid in sorted(common):
        a,b=plans['baseline'][sid],plans['D01'][sid]
        scale=a['evidence']['factor']/b['evidence']['factor']
        paired.append(dict(setup_id=sid,symbol=a['symbol'],baseline_date=a['date'],recovery_date=b['date'],
            earlier=b['date']<a['date'],same_date=b['date']==a['date'],
            baseline_trigger_at_recovery_factor=a['trigger']*scale,recovery_trigger=b['trigger'],
            baseline_stop_at_recovery_factor=a['stop']*scale,recovery_stop=b['stop'],
            baseline_gross=(a['target']-a['trigger'])/(a['trigger']-a['stop']),
            recovery_gross=(b['target']-b['trigger'])/(b['trigger']-b['stop'])))
    dump(output/'paired-plans.json',paired)
    final=dict(results=results,prior_metrics={v:summary_metrics(ms) for v,ms in metrics.items()},
        selected_core_observed_before_plan=sum(r['observed_before_plan'] for r in timing),
        paired_count=len(paired),paired_earlier=sum(p['earlier'] for p in paired),
        paired_same_day=sum(p['same_date'] for p in paired),baseline_equivalence=True,
        bar_population_scanned=count,cohort_size=len(cohort),real_hourly_validation=False,
        production_promoted=False,diagnostic_only=True)
    after={str(p.relative_to(experiment)):sha(p) for p in inputs}
    assert before==after,'Frozen inputs changed'
    final['input_hashes_unchanged']=True
    dump(output/'result.json',final)
    dump(output/'status.json',dict(status='complete',output=str(output)))
    print('OUTPUT',output,flush=True)
    return final


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('experiment',type=Path);parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    main(args.experiment,args.output or Path('runs')/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-daily-proxy-verification'))
