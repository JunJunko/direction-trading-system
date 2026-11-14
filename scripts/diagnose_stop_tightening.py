"""Fixed-entry causal diagnosis; not a new account return backtest."""
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trading_system.analysis import adjusted
from trading_system.domain import Bar
from trading_system.support import support_band_retest
from report_plan_reward_risk import assessment, net_values

def load(p):return json.loads(p.read_text(encoding='utf-8'))
def read(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def main():
    out=ROOT/'runs/20261024-stop-tightening-diagnosis-final';out.mkdir(exist_ok=False)
    cohort=ROOT/'runs/20261023-support-rebound-cohort-verified'
    cfg=load(cohort/'candidate/config.json');plans=load(cohort/'plans.json')
    histories=defaultdict(list)
    for r in read(cohort/'bars.csv'):
        histories[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in
            ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    audits={r['setup_id']:r for r in read(cohort/'candidate/entry_audit.csv')}
    rows=[]
    for p in plans:
        bars=adjusted(sorted((b for b in histories[p['symbol']] if b.date<=p['date']),key=lambda b:b.date))
        c=next(i for i,b in enumerate(bars) if b.date==p['support_source_date'])
        small=dict(c=c,date=p['support_source_date'],stop=bars[c].low,confirmed_date=p['support_known_at'])
        _,reason=support_band_retest(bars,small,.01)
        k=next(i for i,b in enumerate(bars) if b.date==p['support_known_at'])
        atr=sum(max(bars[i].high-bars[i].low,abs(bars[i].high-bars[i-1].close),abs(bars[i].low-bars[i-1].close)) for i in range(k-13,k+1))/14
        stop=max(p['stop'],p['support_upper']-.15*atr)
        audit=audits.get(p['setup_id'])
        # Execution audits are at execution-day factors. Normalize candidate stop too.
        factor_scale=float(audit['stop'])/p['stop'] if audit else 1
        fill=float(audit['fill']) if audit else p['trigger']*1.001
        target=float(audit['target']) if audit else p['target']
        old_stop=p['stop']*factor_scale;new_stop=stop*factor_scale
        q=1000
        old=net_values(fill,old_stop,target,q,p['date'],cfg['execution'])
        new=net_values(fill,new_stop,target,q,p['date'],cfg['execution'])
        assert new['net_rr']>=old['net_rr']-1e-10
        rows.append(dict(symbol=p['symbol'],signal_date=p['date'],known_at=p['support_known_at'],
            old_filled=bool(audit and audit['execution_reason']=='filled'),v15_first_rejection=reason,
            reference_fill=fill,old_stop=old_stop,stop_only_candidate=new_stop,
            old_net_rr_fixed_1000_shares=old['net_rr'],new_net_rr_fixed_1000_shares=new['net_rr'] if new_stop<fill else None,
            valid_stop_below_fill=new_stop<fill,
            new_distance=(fill-new_stop)/fill,passes_1pct=0<(fill-new_stop)/fill<=.01+1e-12,
            passes_2pct=0<(fill-new_stop)/fill<=.02+1e-12,
            band_width=(p['support_upper']-stop)/p['support_upper']))
    base=ROOT/'runs/20261022-mainboard-support-zone'
    oldplans=load(base/'plans.json');basecfg=load(base/'config.json')
    grid=[]
    for fraction in (0,.25,.5,.75):
        passed=0
        for p in oldplans:
            a=assessment(p,basecfg);fill=a['fill'];stop=p['stop']+(fill-p['stop'])*fraction
            r=net_values(fill,stop,p['target'],a['reference_quantity'],p['date'],basecfg['execution'])
            # Negative net reward stays negative as risk shrinks; it cannot pass 3R.
            assert r['expected_loss']<=a['expected_loss']+1e-8
            if a['expected_profit']>=0:assert r['net_rr']>=a['net_rr']-1e-10
            else:assert r['net_rr']<0
            passed+=r['net_rr']>3
        grid.append(dict(risk_distance_reduction=fraction,net_rr_above3=passed))
    assert all(a['net_rr_above3']<=b['net_rr_above3'] for a,b in zip(grid,grid[1:]))
    summary=dict(scope='fixed-entry diagnostic, not account backtest; hypothetical stops are not verified new support',
        prior_plans=len(rows),prior_buys=sum(r['old_filled'] for r in rows),
        rejected_on_first_confirmation=sum(r['v15_first_rejection']=='waiting_after_support_confirmation' for r in rows),
        old_buys_passing_1pct_after_stop_only=sum(r['old_filled'] and r['passes_1pct'] for r in rows),
        old_buys_passing_2pct_after_stop_only=sum(r['old_filled'] and r['passes_2pct'] for r in rows),
        fixed_68_monotonicity=grid)
    for name,obj in [('summary',summary),('prior-9-trace',rows)]:
        (out/(name+'.json')).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    with (out/'prior-9-trace.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    (out/'diagnose_stop_tightening.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps([r for r in rows if r['old_filled']],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
