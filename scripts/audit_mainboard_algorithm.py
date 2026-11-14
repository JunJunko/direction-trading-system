"""Explain the frozen v3 funnel and independently verify its RR arithmetic.

This is a diagnostic, not a new strategy or a counterfactual return estimate.
"""
import csv,json,sys,math,statistics
from pathlib import Path
from collections import Counter,defaultdict

def read(p):
    with p.open(encoding='utf-8-sig') as f: return list(csv.DictReader(f))

def main(run):
    run=Path(run); out=run/'algorithm_audit';out.mkdir(exist_ok=True)
    events=read(run/'decisions.csv');audits=read(run/'entry_audit.csv')
    config=json.loads((run/'config.json').read_text(encoding='utf-8'))
    ex=config['execution'];slip=ex['slippage'];commission=ex['commission_rate']
    independently_checked=0
    for row in audits:
        if not row.get('net_rr'): continue
        q=float(row['candidate_quantity']);fill=float(row['fill'])
        stop=float(row['stop'])*(1-slip);target=float(row['target'])*(1-slip)
        tax=ex['sell_tax_after_20230828'] if row['date']>='20230828' else ex['sell_tax_before_20230828']
        buy_fee=max(ex['minimum_commission'],q*fill*commission)
        profit=q*(target-fill)-buy_fee-max(ex['minimum_commission'],q*target*commission)-q*target*tax
        loss=q*(fill-stop)+buy_fee+max(ex['minimum_commission'],q*stop*commission)+q*stop*tax
        assert math.isclose(profit/loss,float(row['net_rr']),rel_tol=1e-12,abs_tol=1e-12)
        independently_checked+=1
    intents=[e for e in events if e['event']=='entry_intent']
    setup={e['setup_id']:e for e in events if e['event']=='double_bottom_breakout'}
    retest={e['setup_id']:e for e in events if e['event']=='retest_observed'}
    required={r['symbol'] for r in intents};history=defaultdict(list)
    with (run/'bars.csv').open(encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in required:
                history[r['symbol']].append((r['date'],float(r['close']),float(r['factor'])))
    indices={s:{r[0]:i for i,r in enumerate(rows)} for s,rows in history.items()}
    pullbacks=[]
    for e in intents:
        if e['setup_id'] not in setup: continue # A setup may have been identified during warmup.
        origin=setup[e['setup_id']];rows=history[e['symbol']];lookup=indices[e['symbol']]
        start,end=lookup[origin['date']],lookup[e['date']];anchor=rows[end][2]
        first=next((i for i in range(start+1,end+1)
                    if rows[i][1]*rows[i][2]/anchor<rows[i-1][1]*rows[i-1][2]/anchor),None)
        duration=end-first if first is not None else 0
        pullbacks.append(dict(symbol=e['symbol'],signal_date=e['date'],setup_id=e['setup_id'],
            breakout_date=origin['date'],first_pullback_date=rows[first][0] if first is not None else '',
            completed_pullback_observations=duration,v4_min_duration_met=first is not None and duration>=3))
    planned=[float(r['planned_gross_rr']) for r in audits]
    eligible=[r for r in audits if r.get('net_rr') and float(r['net_rr'])>3]
    reasons=Counter(r['execution_reason'] for r in audits)
    result=dict(signal_intents=len(intents),signal_universe_exclusions=sum(e['event']=='entry_rejected' and e['reason']=='universe_ineligible_signal' for e in events),
        next_session_audits=len(audits),execution_reasons=dict(reasons),
        economic_before_execution=dict(target_not_above_trigger=sum(x<=0 for x in planned),
            planned_gross_rr_above_3=sum(x>3 for x in planned),next_session_hypothetical_net_rr_above_3=len(eligible),
            gross_rr_buckets=dict(Counter('<=0' if x<=0 else '(0,1]' if x<=1 else '(1,2]' if x<=2 else '(2,3]' if x<=3 else '>3' for x in planned))),
        independently_verified_net_rr_rows=independently_checked,
        risk_cap_rejections=sum(v for k,v in reasons.items() if k in ('max_positions','insufficient_budget_or_cash','symbol_already_owned')),
        invalidations=dict(Counter(e['reason'] for e in events if e['event']=='setup_invalidated')),
        pullback_diagnostic=dict(evaluation_origin_signals=len(pullbacks),fewer_than_three_observations=sum(not r['v4_min_duration_met'] for r in pullbacks)),
        eligible_candidates=[{k:r[k] for k in ('symbol','signal_date','date','trigger','stop','target','net_rr','execution_reason')} for r in eligible],
        limitations=['hypothetical net RR can be computed on an unfilled or ambiguous bar; it is not a fill',
            'pullback diagnostic uses v4 first-down-close convention; not proof of complete N structure',
            'diagnostic does not change target, stop, timing or risk threshold'])
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    with (out/'pullback_diagnostic.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(pullbacks[0]));writer.writeheader();writer.writerows(pullbacks)
    print(json.dumps(result,ensure_ascii=True))

if __name__=='__main__':main(sys.argv[1])
