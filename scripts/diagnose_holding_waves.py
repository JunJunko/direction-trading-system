"""Summarize recorded holding classifications; never infer unlogged gates."""
import csv,json,sys
from collections import Counter
from pathlib import Path


def main(run):
    p=Path(run)
    with (p/'trades.csv').open(encoding='utf-8-sig') as f:
        trades=list(csv.DictReader(f))
    observed={t['setup_id']:[] for t in trades};entries={}
    kinds={'holding_wave_classified','holding_wave_rejected','core_protection_promoted','holding_exit'}
    fields=('date','event','level','trough_date','peak_date','duration','drop','reason','old_stop','new_stop')
    with (p/'decisions.csv').open(encoding='utf-8-sig') as f:
        for e in csv.DictReader(f):
            if e['event']=='entry_intent' and e.get('setup_id') in observed:
                entries.setdefault(e['setup_id'],e)
            if e['event'] in kinds and e.get('setup_id') in observed:
                observed[e['setup_id']].append({k:e[k] for k in fields if e.get(k)})
    params=json.loads((p/'config.json').read_text(encoding='utf-8'))['strategies'][0]['params']
    histories={t['symbol']:[] for t in trades} if params.get('holding_scale_mode')=='owned_core' else {}
    if histories:
        with (p/'bars.csv').open(encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                if r['symbol'] in histories:
                    histories[r['symbol']].append((r['date'],float(r['high']),float(r['factor'])))
    result=[]
    for t in trades:
        events=observed[t['setup_id']]
        item=dict(symbol=t['symbol'],entry_date=t['entry_date'],exit_date=t['exit_date'],
            classification_counts=dict(Counter(e['level'] for e in events if e['event']=='holding_wave_classified')),
            rejected_floor_count=sum(e['event']=='holding_wave_rejected' for e in events),
            promoted_stop_count=sum(e['event']=='core_protection_promoted' for e in events),events=events)
        if histories and not item['promoted_stop_count']:
            entry=entries[t['setup_id']];bars=histories[t['symbol']]
            factors={d:f for d,h,f in bars};exit_factor=factors[t['exit_date']]
            scale=factors[entry['first_planned_at']]/exit_factor
            peak=max((r for r in bars if entry['core_c']<=r[0]<t['exit_date']),key=lambda r:r[1]*r[2])
            peak_price=peak[1]*peak[2]/exit_factor
            reference=float(entry['correction_range'])*scale;initial_stop=float(entry['stop'])*scale
            buffer=float(params.get('stop_buffer',.005))
            # A core correction requires peak-low >= reference. Therefore its
            # candidate stop <= (peak-reference)*(1-buffer), before other gates.
            bound=(peak_price-reference)*(1-buffer)
            item['initial_core_stop_upper_bound']=dict(observed_peak_date=peak[0],observed_peak_high=peak_price,
                reference_drop=reference,initial_stop=initial_stop,max_candidate_stop=bound,
                raising_stop_impossible_under_observed_peaks=bound<=initial_stop,
                peak_required_to_raise=initial_stop/(1-buffer)+reference,
                scope='Necessary range gate only, all prices normalized to exit factor. No promotions in this holding. Uses observed peaks before exit, never a proposed executable exit.')
        result.append(item)
    payload=dict(scope='Recorded holding events for closed trades only. Classification is not promotion; unlogged eligibility failures cannot be counted as observed causes.',trades=result)
    (p/'holding-waves.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{k:v for k,v in t.items() if k!='events'} for t in result],ensure_ascii=True))


if __name__=='__main__':main(sys.argv[1])
