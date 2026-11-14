"""Observe all holding gates together without changing any trading decision."""
import sys,json,csv,pickle,inspect,textwrap,copy
from pathlib import Path
from types import MethodType
from collections import Counter
from ablation_rules import FrozenUpper,bind_replay,edit
from run_rule_ablation import equal_rows,dump

def main(run):
    out=Path(run);sys.path.insert(0,str(out/'frozen-baseline/source/src'))
    from trading_system.strategies import autonomous_double_bottom as am
    from trading_system.domain import Bar
    from trading_system.engine import Backtest
    from trading_system.universe import MainboardUniverse
    from trading_system.data import save_csv
    config=json.loads((out/'frozen-baseline/config.json').read_text(encoding='utf-8'))
    cal=json.loads((out/'frozen-baseline/calendar.json').read_text(encoding='utf-8'))
    ud=json.loads((out/'frozen-baseline/universe.json').read_text(encoding='utf-8'))
    cache=pickle.loads((out/'signal-cache.pkl').read_bytes());plan=cache['plans']['baseline']
    symbols={p['symbol'] for p in plan.values()};bars=[]
    with (out/'frozen-baseline/bars.csv').open(encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in symbols:bars.append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in
                ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    source=textwrap.dedent(inspect.getsource(am.AutonomousDoubleBottom.manage_live_leg))
    anchor="        if (self.holding_scale_mode=='owned_core' and measured"
    observation='''        if measured:
            ambiguities=[bars[r['index']].date for r in holding_swings.ambiguous if anchor<=r['index']<=low.index] if nested else []
            checks=dict(actual_floor=min(x.low for x in bars[peak+1:low.index+1])>=low.price,
                duration_gate=measured['duration']>=plan['live_reference_duration'],
                range_gate=measured['range']>=plan['live_reference_range'],order_clear=not ambiguities,
                impulse_positive=impulse_time>0 and impulse>0,minimum_duration=measured['duration']>=3,
                time_matched=measured['duration']<=impulse_time,range_matched=measured['range']<impulse,
                speed_matched=impulse_time>0 and measured['range']/measured['duration']<impulse/impulse_time,
                floor_intact=min(x.low for x in bars[low.index:])>=low.price,
                recovery=b.close>bars[low.index].high,
                raises_stop=low.price*(1-self.p['stop_buffer'])>position.stop)
            events.append(self.event(b,'holding_gate_observation',setup_id=position.setup_id,
                anchor_date=bars[anchor].date,peak_date=bars[peak].date,trough_date=bars[low.index].date,
                duration=measured['duration'],drop=measured['range'],impulse_time=impulse_time,impulse=impulse,
                reference_duration=plan['live_reference_duration'],reference_range=plan['live_reference_range'],
                ambiguous_dates=ambiguities,checks=checks))
'''
    source=edit(source,anchor,observation+anchor)
    ns=dict(vars(am));exec(compile(source,'<frozen-holding-observations>','exec'),ns)
    s=bind_replay(am.AutonomousDoubleBottom(config['strategies'][0]['id'],config['strategies'][0]['params']),
        cache['tapes']['baseline'],FrozenUpper(cache['upper_events']),ns['manage_live_leg'])
    engine=Backtest(config,[s]);engine.run(bars,cal['open_dates'],set(cal['week_ends']),
        evaluation_start='20251008',evaluation_end='20261007',universe=MainboardUniverse(ud['stocks'],ud['st_by_date']))
    for label,actual in [('orders',engine.orders),('trades',engine.trades),('equity',engine.curve)]:
        equal_rows(out/'frozen-baseline'/(label+'.csv'),actual,label)
    observed=[e for e in engine.events if e['event']=='holding_gate_observation'];first={}
    for e in observed:first.setdefault((e['setup_id'],e['trough_date']),e)
    dump(out/'holding-gate-observations.json',dict(baseline_account_unchanged=True,observations=observed,
        first_observations=list(first.values()),failure_counts=dict(Counter(k for e in observed for k,v in e['checks'].items() if not v))))
    save_csv(out/'holding-gate-observations.csv',[dict(**{k:v for k,v in e.items() if k not in ('checks','ambiguous_dates')},
        ambiguous_dates=';'.join(e['ambiguous_dates']),**e['checks']) for e in observed])
    print(json.dumps([dict(symbol=e['symbol'],date=e['date'],trough_date=e['trough_date'],
        failed=[k for k,v in e['checks'].items() if not v]) for e in first.values()]))

if __name__=='__main__':main(sys.argv[1])
