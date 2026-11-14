"""Enumerate all causal W layouts and quantify single-candidate search losses."""
import csv,json,sys
from pathlib import Path
from collections import Counter,defaultdict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.analysis import weekly
from trading_system.structure import hierarchy_double_bottom_candidates

snapshot=Path(sys.argv[1]);output=Path(sys.argv[2]);output.mkdir(exist_ok=False)
read=lambda path:json.loads(path.read_text(encoding='utf-8'))
calendar=read(snapshot/'calendar.json');manifest=read(snapshot/'manifest.json')
weekly_events=defaultdict(list)
for name in ('warmup_decisions.csv','decisions.csv'):
    with (snapshot/name).open(encoding='utf-8-sig') as stream:
        for event in csv.DictReader(stream):
            if event['event'] in ('weekly_reversal_candidate','weekly_reversal_invalidated',
                                  'upper_direction_confirmed','upper_direction_lost'):
                weekly_events[event['symbol']].append(event)
for events in weekly_events.values():events.sort(key=lambda e:e['date'])
histories=defaultdict(list)
with (snapshot/'bars.csv').open(encoding='utf-8-sig') as stream:
    for row in csv.DictReader(stream):
        factor=float(row['factor'])
        # Constant total-return units use each bar's own factor; no future anchor.
        histories[row['symbol']].append(Bar(row['symbol'],row['date'],
            *[float(row[k])*factor for k in ('open','high','low','close')],float(row['volume'])))
counts=Counter();examples=defaultdict(list)
for number,(symbol,bars) in enumerate(histories.items(),1):
    weeks=weekly(bars,set(calendar['week_ends']))
    events=weekly_events[symbol];event_index=0;pending=False;direction=False
    for end,w in enumerate(weeks):
        while event_index<len(events) and events[event_index]['date']<w.date:
            event=events[event_index]['event'];event_index+=1
            if event=='weekly_reversal_candidate':pending=True
            elif event=='weekly_reversal_invalidated':pending=False
            elif event=='upper_direction_confirmed':direction=True;pending=False
            elif event=='upper_direction_lost':direction=False;pending=False
        if not manifest['first_session']<=w.date<=manifest['last_session']:continue
        normal,_=hierarchy_double_bottom_candidates(weeks[:end+1])
        delayed,_=hierarchy_double_bottom_candidates(weeks[:end+1],allow_delayed=True)
        counts['evaluation_stock_weeks']+=1
        counts['all_first_breakout_layouts']+=len(normal)
        counts['same_week_extra_layouts']+=max(0,len(normal)-1)
        categories=[]
        if len(normal)>1:categories.append('multiple_layouts_same_week')
        if pending and not direction and normal:
            counts['layouts_while_existing_candidate_pending']+=len(normal)
            categories.append('search_blocked_by_pending')
        if direction and normal:counts['layouts_while_direction_already_valid']+=len(normal)
        late=[c for c in delayed if c['first_breakout_index']<end]
        counts['layouts_observable_after_breakout']+=len(late)
        if late:categories.append('right_bottom_confirmed_after_breakout')
        for category in categories:
            selected=late if category=='right_bottom_confirmed_after_breakout' else normal
            if len(examples[category])<30:
                examples[category].append(dict(symbol=symbol,observed_at=w.date,pending_before=pending,
                    direction_before=direction,candidates=[dict(first=weeks[c['first']].date,
                    second=weeks[c['second']].date,breakout=weeks[c['first_breakout_index']].date,
                    bottom_confirmed=weeks[c['confirmed']].date) for c in selected]))
    if number%250==0:print(number,flush=True)
payload=dict(scope='all available mainboard snapshot stocks; algorithm layouts, not independent valid-pattern counts',
             counts=dict(counts),examples=dict(examples))
(output/'audit.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(counts=counts,output=str(output)),ensure_ascii=True),flush=True)
