"""Reconstruct time gates at a holding timeout, using only its as-of bars."""
import csv,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.analysis import adjusted
from trading_system.structure import active_correction


def main(run):
    p=Path(run)
    with (p/'decisions.csv').open(encoding='utf-8-sig') as f:
        relevant=[e for e in csv.DictReader(f) if e['event'] in ('entry_intent','exit_intent','core_protection_promoted')]
    entries={e['setup_id']:e for e in relevant if e['event']=='entry_intent'}
    exits=[e for e in relevant if e['event']=='exit_intent' and e['reason']=='live_core_adjustment_timeout']
    histories={e['symbol']:[] for e in exits}
    if histories:
        with (p/'bars.csv').open(encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                if r['symbol'] in histories:
                    histories[r['symbol']].append(Bar(r['symbol'],r['date'],*[float(r[k]) for k in
                        ('open','high','low','close','volume','factor','up_limit','down_limit')]))
    config=json.loads((p/'config.json').read_text(encoding='utf-8'))
    right=config['strategies'][0]['params'].get('right',2);result=[]
    for e in exits:
        entry=entries[e['setup_id']]
        if any(r['event']=='core_protection_promoted' and r['setup_id']==e['setup_id'] for r in relevant):continue
        bars=adjusted([b for b in histories[e['symbol']] if b.date<=e['date']])
        owned=config['strategies'][0]['params'].get('holding_scale_mode')=='owned_core'
        anchor_date=entry['core_c'] if owned else entry['small_c'][:8]
        leg=[b for b in bars if b.date>=anchor_date]
        correction=active_correction(leg,leg[0].date)
        reference=float(entry['correction_duration']);impulse=correction['peak']
        deadline=(reference if owned else min(reference,max(3,impulse)))+right
        assert correction['duration']>deadline
        result.append(dict(symbol=e['symbol'],as_of=e['date'],live_anchor=leg[0].date,
            current_peak_date=leg[impulse].date,reference_duration=reference,
            current_impulse_duration=impulse,current_correction_duration=correction['duration'],
            timeout_deadline=deadline,promotion_requires_duration_at_least=reference,
            matching_requires_duration_at_most=impulse,
            promotion_time_constraints_compatible=reference<=impulse,
            scope='Necessary time constraints only, reconstructed with known prices; no stop promotions in this holding. Does not establish a correct alternative rule.'))
    (p/'holding-constraints.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':main(sys.argv[1])
