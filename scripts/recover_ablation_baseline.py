"""Recover a collided log only when the recovered bytes match its pre-run SHA.

Daily/weekly detector source is identical in the prior immutable run. Its
detector rows are combined with the new account's already-verified rows;
holding/account events from the prior run are excluded. Never accept a
reconstruction just because its event counts look plausible.
"""
import csv,json,hashlib,sys
from pathlib import Path
from collections import defaultdict

def main(run):
    out=Path(run);root=out.resolve().parents[1]
    old=root/'runs/20261010-101409-mainboard-double_bottom_v5_11_1-structure'
    actual=out/'baseline';expected=json.loads((out/'frozen-inputs.json').read_text(encoding='utf-8'))['decisions.csv']
    for name in ('strategies/direction_double_bottom.py','wave_hierarchy.py','structure.py','analysis.py'):
        assert (old/'source/src/trading_system'/name).read_bytes()==(actual/'source/src/trading_system'/name).read_bytes()
    old_id=json.loads((old/'config.json').read_text(encoding='utf-8'))['strategies'][0]['id']
    new_id=json.loads((actual/'config.json').read_text(encoding='utf-8'))['strategies'][0]['id']
    account={'phase_policy','plan_rejected','plan_approved','expired_not_triggered','ambiguous_or_invalidated_entry_bar',
        'filled','holding_wave_classified','holding_wave_rejected','holding_exit','exit_intent','structural_exit_filled',
        'entry_rejected','position_closed','stop_raised','core_protection_promoted','corporate_action',
        'limit_up_buy_blocked','slippage_exceeds_daily_high','expired_suspended'}
    source=defaultdict(lambda:defaultdict(list));current=defaultdict(list)
    with (old/'decisions.csv').open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f);header=reader.fieldnames
        for row in reader:
            if row['event'] in account or row['reason']=='warmup_plan_not_executable':continue
            row={k:v.replace(old_id,new_id) for k,v in row.items()}
            source[row['date']][row['symbol']].append(row)
    with (actual/'decisions.csv').open(encoding='utf-8-sig',newline='') as f:
        for row in csv.DictReader(f):current[row['date']].append(row)
    target=out/'recovered-decisions.csv';count=0
    with target.open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=header);writer.writeheader()
        for date in sorted(current):
            day=current[date];phase=next(i for i,r in enumerate(day) if r['event']=='phase_policy')
            prefix=day[:phase+1];writer.writerows(prefix);count+=len(prefix)
            suffix=defaultdict(list)
            for row in day[phase+1:]:
                if row['event'] in account:suffix[row['symbol']].append(row)
            for symbol in sorted(set(source[date])|set(suffix)):
                writer.writerows(source[date][symbol]);writer.writerows(suffix[symbol])
                count+=len(source[date][symbol])+len(suffix[symbol])
    recovered=hashlib.sha256(target.read_bytes()).hexdigest()
    payload=dict(expected_sha256=expected,recovered_sha256=recovered,exact_bytes_match=recovered==expected,rows=count,
        source_detector_code_identical=True,account_from_verified_baseline=True)
    (out/'recovery-verification.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
    print(json.dumps(payload))
    if recovered!=expected:raise RuntimeError('Recovery is not byte-identical; original is not restored.')

if __name__=='__main__':main(sys.argv[1])
