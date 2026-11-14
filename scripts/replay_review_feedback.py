"""Causal strategy replay of the frozen review stocks, not portfolio returns."""
import csv,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.strategies.direction_double_bottom import DirectionDoubleBottom

pack=Path(sys.argv[1]);output=Path(sys.argv[2])
read=lambda f:json.loads(f.read_text(encoding='utf-8-sig'))
manifest=read(pack/'manifest.json');cases=read(pack/'cases-private.json')
cal=read(pack/'calendar.json');ends=set(cal['week_ends'])
history={c['symbol']:[] for c in cases}
with (Path(manifest['snapshot'])/'bars.csv').open(encoding='utf-8-sig') as stream:
    for row in csv.DictReader(stream):
        if row['symbol'] in history:
            history[row['symbol']].append(Bar(row['symbol'],row['date'],
                *[float(row[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')]))
records={}
for case in cases:
    if case['repeat_of']:continue
    bars=[b for b in history[case['symbol']] if b.date<=case['as_of']]
    records[case['id']]={}
    for mode in ('structured','boundary','pool'):
        strategy=DirectionDoubleBottom('audit_'+mode,dict(lower_cycle='daily_nested',
            structure_mode='hierarchy',exit_mode='active_correction',entry_lifecycle='fresh',
            retest_mode='boundary' if mode=='pool' else mode,candidate_mode='pool' if mode=='pool' else 'single'))
        strategy.set_calendar(cal['open_dates']);events=[]
        for end in range(len(bars)):
            _, observed=strategy.on_close(bars[:end+1],ends)
            events.extend(e for e in observed if e['event'] in
                ('upper_direction_confirmed','upper_direction_lost','weekly_reversal_invalidated'))
        state=strategy.states[case['symbol']]
        records[case['id']][mode]=dict(direction=state['direction'],pending=bool(state['pending']),
            confirmed_date=state.get('confirmed_date') if state['direction']=='long' else None,
            source=state.get('direction_source'),pending_count=len(state.get('candidates',[])),events=events)
    print(case['id'],flush=True)
output.write_text(json.dumps(dict(scope='24 frozen review stocks; no portfolio performance',records=records),
                            ensure_ascii=False,indent=2),encoding='utf-8')
