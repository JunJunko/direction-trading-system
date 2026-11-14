"""Frozen-input single-rule experiment; no production defaults are changed."""
import sys,json,csv,os,shutil,hashlib,pickle,copy,time,math
from pathlib import Path
from datetime import datetime
from collections import defaultdict,Counter
from dataclasses import asdict

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'runs/20261010-104630-mainboard-double_bottom_v5_11_2-structure'
from ablation_rules import VARIANTS,FrozenUpper,entry_method,holding_method,bind_entry,bind_replay

def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(2**20),b''):h.update(block)
    return h.hexdigest()
def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as f:yield from csv.DictReader(f)
def account_output(out,variant,locked):
    target=out/variant
    if target.resolve().is_relative_to(locked.resolve()):
        raise ValueError('Account outputs must never overlap frozen inputs')
    target.mkdir(exist_ok=True)
    return target
def freeze():
    out=ROOT/'runs'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-double-bottom-rule-ablation')
    out.mkdir();locked=out/'frozen-baseline';locked.mkdir()
    shutil.copytree(BASE/'source/src',locked/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('config.json','calendar.json','universe.json','summary.json','manifest.json',
                 'orders.csv','trades.csv','equity.csv','entry_audit.csv','decisions.csv','warmup_decisions.csv','bars.csv'):
        os.link(BASE/name,locked/name) if name=='bars.csv' else shutil.copy2(BASE/name,locked/name)
    assert sha(locked/'bars.csv')=='03bad3718f464328a32ba8287457acde466828b5df9875a4ddda613cc9cb2334'
    for p in (locked/'source/src').rglob('*.py'):
        assert p.read_bytes()==(ROOT/'src'/p.relative_to(locked/'source/src')).read_bytes(),str(p)
    plan=dict(baseline=str(BASE),variants=VARIANTS,seed=20261010,blind_sample_per_rule=4,
        fixed=['price/universe/calendar','weekly direction/retest event tape','all numeric parameters',
               'RR/cost/risk/T+1/account policy','warmup and evaluation dates'],
        scope='single-rule ablation on an already studied sample; no optimization or promotion',
        required_baseline_check=['unique first plans','orders','trades','all daily equity'],
        validity=['causal dates and geometry/floor consistency','supported candidate pending independent review',
                  'ambiguous daily ordering / ownership / target','stale under explicit engineering freshness convention'],
        validity_uses_outcomes=False,production_promoted=False,
        event_tape_limit='Weekly candidate diagnostics are not replayed; confirmation/loss is immutable.',
        projection='Account retains all histories for every symbol emitting evaluation intents; zero-intent symbols have no account effect. Baseline equality must prove this projection.')
    dump(out/'evaluation-plan.json',plan)
    dump(out/'frozen-inputs.json',{str(p.relative_to(locked)):sha(p) for p in locked.rglob('*') if p.is_file()})
    (out/'source').mkdir()
    for name in ('ablation_rules.py','run_rule_ablation.py'):shutil.copy2(ROOT/'scripts'/name,out/'source'/name)
    dump(out/'status.json',dict(status='frozen',output=str(out)))
    print('OUTPUT '+str(out),flush=True)
    return out

def equal_rows(recorded,actual,name):
    original=list(rows(recorded))
    assert len(original)==len(actual),(name,len(original),len(actual))
    for index,(a,b) in enumerate(zip(original,actual)):
        for k,v in a.items():
            w=b.get(k,'')
            if v=='':assert w in ('',None),(name,index,k,v,w)
            else:
                try:assert math.isclose(float(v),float(w),rel_tol=1e-11,abs_tol=1e-6),(name,index,k,v,w)
                except (ValueError,TypeError):assert str(w)==v,(name,index,k,v,w)

def main(out=None):
    out=Path(out) if out else freeze();locked=out/'frozen-baseline'
    sys.path.insert(0,str(locked/'source/src'))
    from trading_system.strategies import direction_double_bottom as dm,autonomous_double_bottom as am
    from trading_system import wave_hierarchy as wm
    from trading_system.domain import Bar
    from trading_system.analysis import AdjustedCache
    from trading_system.structure import SwingCache
    from trading_system.engine import Backtest
    from trading_system.universe import MainboardUniverse
    from trading_system.data import save_csv
    config=json.loads((locked/'config.json').read_text(encoding='utf-8'))
    cal=json.loads((locked/'calendar.json').read_text(encoding='utf-8'))
    ud=json.loads((locked/'universe.json').read_text(encoding='utf-8'))
    ends=set(cal['week_ends']);dates=cal['open_dates'];first=next(d for d in dates if d>='20251008')
    params=config['strategies'][0]['params'];name=config['strategies'][0]['id']
    methods={v['id']:entry_method(dm,wm,v['rule']) for v in VARIANTS if v['group']!='holding'}
    holding={v['id']:holding_method(am,v['rule']) for v in VARIANTS}
    upper_events=defaultdict(list)
    for file in ('warmup_decisions.csv','decisions.csv'):
        for r in rows(locked/file):
            if r['event'] in ('upper_direction_confirmed','upper_direction_lost'):
                upper_events[(r['symbol'],r['date'])].append({k:v for k,v in r.items() if v!=''})
    upper=FrozenUpper(upper_events);symbols={k[0] for k in upper_events}
    grouped=defaultdict(list);count=0
    print('Loading full immutable population; weekly-confirmed symbols '+str(len(symbols)),flush=True)
    for r in rows(locked/'bars.csv'):
        count+=1
        if r['symbol'] in symbols:
            grouped[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in
                ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    assert count==2856672,count
    for history in grouped.values():history.sort(key=lambda b:b.date)
    variants=[v for v in VARIANTS if v['group']!='holding']
    tapes={v['id']:{} for v in variants};plans={v['id']:{} for v in variants}
    counters={v['id']:Counter() for v in variants};frames={}
    status=lambda **kw:dump(out/'status.json',kw)
    start=time.monotonic()
    for index,symbol in enumerate(sorted(grouped)):
        shared_daily={symbol:AdjustedCache()};shared_core={symbol:SwingCache(2,2)};shared_small={symbol:SwingCache(1,1)}
        strategies={}
        for v in variants:
            s=am.AutonomousDoubleBottom(name,params);s.set_calendar(dates)
            s.set_context(dict(allow_same_level=False,allow_cycle_upgrade=False,lower_histories={}))
            s.daily_caches=shared_daily;s.core_swings=shared_core;s.rhythm_swings=shared_small
            strategies[v['id']]=bind_entry(s,methods[v['id']],upper)
        history=[];begun=False
        for b in grouped[symbol]:
            if b.date>'20261007':break
            if b.date>=first and not begun:
                for vid,s in strategies.items():
                    es=s.begin_evaluation(first)
                    tapes[vid].setdefault(('BEGIN',first),([],[]))[1].extend(es)
                begun=True
            history.append(b)
            for vid,s in strategies.items():
                new,events=s.on_close(history,ends)
                if b.date<first:continue
                counters[vid].update((e['event']+':'+str(e.get('reason',''))) for e in events)
                if vid=='baseline':
                    frames[(symbol,b.date)]=[dict(event=e['event'],reason=e.get('reason'),
                        first_touch_date=e.get('first_touch_date'),setup_id=e.get('setup_id')) for e in events]
                if new:
                    tapes[vid][(symbol,b.date)]=(copy.deepcopy(new),copy.deepcopy(events))
                    for intent in new:plans[vid].setdefault(intent.setup_id,asdict(intent))
        if index%10==0 or index+1==len(grouped):
            state=dict(status='generating',symbols_done=index+1,symbols=len(grouped),
                elapsed_seconds=round(time.monotonic()-start),plans={k:len(v) for k,v in plans.items()})
            status(**state);print(json.dumps(state),flush=True)
    with (out/'signal-cache.pkl').open('wb') as f:pickle.dump(dict(tapes=tapes,plans=plans,frames=frames,upper_events=dict(upper_events)),f)
    dump(out/'generation-counts.json',{k:dict(v) for k,v in counters.items()})
    baseline_events={r['setup_id']:r for r in rows(locked/'decisions.csv') if r['event']=='entry_intent'}
    assert set(baseline_events)==set(plans['baseline']),('baseline plan identities',len(baseline_events),len(plans['baseline']))
    for sid,p in plans['baseline'].items():
        r=baseline_events[sid]
        for field in ('trigger','stop','target'):assert math.isclose(float(r[field]),p[field],rel_tol=1e-11), (sid,field)
        # The CSV may contain renewals; the evidence records the immutable first planning date.
        assert r['first_planned_at']==p['evidence']['first_planned_at'],sid
    comparison=[]
    for v in VARIANTS:
        vid=v['id'];source='baseline' if v['group']=='holding' else vid;tape=tapes[source];plan=plans[source]
        target=account_output(out,vid,locked)
        dump(target/'rule.json',v);dump(target/'plans.json',list(plan.values()))
        relevant={p['symbol'] for p in plan.values()}
        s=bind_replay(am.AutonomousDoubleBottom(name,params),tape,upper,holding[vid])
        engine=Backtest(copy.deepcopy(config),[s])
        print('Account '+vid+' / '+str(len(plan))+' plans',flush=True)
        engine.run([b for sym in relevant for b in grouped[sym]],dates,ends,
            evaluation_start='20251008',evaluation_end='20261007',universe=MainboardUniverse(ud['stocks'],ud['st_by_date']))
        if vid=='baseline':
            for label,actual in [('orders',engine.orders),('trades',engine.trades),('equity',engine.curve),('entry_audit',engine.entry_audits)]:
                equal_rows(locked/(label+'.csv'),actual,label)
            dump(out/'baseline-equivalence.json',dict(passed=True,unique_plans=len(plan),closed_trades=len(engine.trades),
                daily_equity_rows=len(engine.curve),checked=['plan identities/levels/first date','every order','every trade','daily equity','entry audit'],
                excluded_stream='Unchanged weekly candidate diagnostics; only direction transitions replayed'))
        for label,actual in [('orders',engine.orders),('trades',engine.trades),('equity',engine.curve),('entry_audit',engine.entry_audits),('decisions',engine.events)]:
            save_csv(target/(label+'.csv'),actual)
        summary=engine.summary();dump(target/'summary.json',summary)
        base=plans['baseline'];restored=set(plan)-set(base);lost=set(base)-set(plan)
        changed=[sid for sid in set(plan)&set(base) if plan[sid]['date']!=base[sid]['date']]
        result=dict(**v,plans=len(plan),restored=len(restored),lost=len(lost),rescheduled=len(changed),
            buys=sum(o['side']=='buy' and o['status']=='filled' for o in engine.orders),
            net_pnl=summary['final_equity']-summary['initial_cash'],summary=summary,
            rejection_counts=dict(Counter(o.get('reason') for o in engine.orders if o['status']=='rejected')),
            restored_ids=sorted(restored),lost_ids=sorted(lost),rescheduled_ids=sorted(changed))
        comparison.append(result);dump(out/'comparison.json',comparison)
        status(status='accounts',variants_done=len(comparison),variants=len(VARIANTS))
        print(json.dumps({k:result[k] for k in ('id','plans','restored','lost','rescheduled','buys','net_pnl')},ensure_ascii=False),flush=True)
    dump(out/'population.json',dict(bar_count=count,universe_count=len(ud['stocks']),weekly_transition_symbols=len(grouped),
        input_population_complete=True,calendar_first=first,calendar_last=engine.curve[-1]['date']))
    status(status='comparisons_complete',output=str(out),production_promoted=False)
    print('COMPLETED '+str(out),flush=True)

if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else None)
