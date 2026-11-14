"""Check search lifecycle identities and entry chronology from a completed run."""
import csv,json,sys
from collections import Counter
from pathlib import Path

path=Path(sys.argv[1]);registered={};confirmed={};intent_dates={};entry_rows=[]
counts=Counter();max_pending=0
for name in ('warmup_decisions.csv','decisions.csv'):
    with (path/name).open(encoding='utf-8-sig') as stream:
        for row in csv.DictReader(stream):
            event=row['event'];identity=row.get('candidate_id')
            if event=='weekly_reversal_candidate':
                if not identity:raise ValueError('Missing pool candidate identity')
                if identity in registered:raise ValueError('Duplicate registration: '+identity)
                if row['date']!=row['first_observed_date']:raise ValueError('Backdated observation')
                if row['breakout_date']>row['first_observed_date']:raise ValueError('Future breakout')
                registered[identity]=row
                if name=='decisions.csv':
                    counts['registered_layouts']+=1
                    counts['delayed_registrations']+=row['breakout_date']<row['first_observed_date']
            elif event=='upper_direction_confirmed':
                source=registered[identity]
                if row['date']<source['first_observed_date']:raise ValueError('Confirmation before observation')
                if row['breakout_date']!=source['breakout_date']:raise ValueError('Breakout identity changed')
                confirmed[(row['symbol'],row['date'])]=row
                if name=='decisions.csv':counts['direction_confirmations']+=1
            elif event=='weekly_candidate_pool':
                max_pending=max(max_pending,int(row['pending_count']))
                if name=='decisions.csv' and int(row['pending_count'])>1:counts['stock_weeks_with_multiple_pending']+=1
            elif event=='entry_intent':
                direction=confirmed[(row['symbol'],row['direction_confirmed'])]
                if row['date']<direction['date']:raise ValueError('Entry before direction confirmation')
                if row['direction_first']!=direction['first_date'] or row['direction_second']!=direction['second_date']:
                    raise ValueError('Entry direction ownership changed')
                intent_dates[row['setup_id']]=row['date']
                entry_rows.append(dict(row=row,direction=direction))
with (path/'trades.csv').open(encoding='utf-8-sig') as stream:
    trades=list(csv.DictReader(stream))
for trade in trades:
    if trade['entry_date']<=intent_dates[trade['setup_id']]:raise ValueError('Non-forward trade fill')
payload=dict(counts=dict(counts),max_simultaneously_pending=max_pending,
    candidate_identities_checked=len(registered),entry_intents_checked=len(entry_rows),
    closed_trades_checked=len(trades),chronology_and_ownership_verified=True)
(path/'search-lifecycle-verification.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
print(json.dumps(payload))
