"""Read-only audit of entry, initial stop, theoretical target and realized protection."""
import math
from statistics import median
from collections import Counter
from audit_pattern_trade_paths import ROOT,load,rows,save,dump,history
from trading_system.ihs_geometry import neckline_at
from trading_system.main_trend import completed_weeks
from trading_system.confirmed_support_trend import confirmed_weekly_points

OUT=ROOT/'runs/20261110-ihs-price-lines'
BASE=ROOT/'runs/20261110-quality-entry/IHS_no_gap_up_cost1'

def main():
    OUT.mkdir(exist_ok=True)
    fills=[a for a in rows(BASE/'entry_audit.csv') if a['execution_reason']=='filled']
    events=rows(BASE/'decisions.csv');plans={e['setup_id']:e for e in events if e['event']=='entry_intent'}
    trades={t['setup_id']:t for t in rows(BASE/'trades.csv')};hist=history({a['symbol'] for a in fills});records=[]
    cal=load(ROOT/'runs/20261110-quality-entry/calendar.json')['open_dates']
    for a in fills:
        pid=a['setup_id'];p=plans[pid];t=trades.get(pid);h=hist[a['symbol']];by={b.date:b for b in h};entry=by[a['date']];sig=by[p['date']]
        factor=entry.factor;scale=sig.factor/factor;buy,stop,target=[float(a[k]) for k in ('fill','stop','target')]
        right=float(p['ihs_right_low'])*scale;atr=float(p['ihs_entry_atr'])*scale
        assert math.isclose(stop,right-.5*atr,abs_tol=1e-8)
        anchors={k:(float(p[k])*scale if k.endswith('_price') else p[k]) for k in ('ihs_peak1_date','ihs_peak2_date','ihs_peak1_price','ihs_peak2_price')}
        theoretical=neckline_at(anchors,p['date'])+neckline_at(anchors,p['ihs_head_date'])-float(p['ihs_floor'])*scale
        assert math.isclose(target,theoretical,abs_tol=1e-8)
        neck=neckline_at(anchors,a['date']);assert buy/(1.001)>neck and buy<=neck+atr+1e-8
        end=t['exit_date'] if t else '20260930';held=[b for b in h if a['date']<=b.date<=end and (not t or b.date<end)]
        peak=max(held,key=lambda b:b.close*b.factor);peakprice=peak.close*peak.factor/factor
        points=confirmed_weekly_points(completed_weeks([b for b in h if b.date<a['date']],cal))
        pressures=[q for q in points if q['kind']=='H' and q['price']>buy*factor]
        nearest=min(pressures,key=lambda q:q['price']) if pressures else None
        raises=[e for e in events if e['setup_id']==pid and e['event']=='main_protection_raised']
        break_even=[e for e in raises if float(e['new'])>buy*factor]
        below=[];streak=0;two=None
        for b in held:
            is_below=b.close*b.factor/factor<neckline_at(anchors,b.date)
            if is_below:below.append(b.date)
            streak=streak+1 if is_below else 0
            if streak>=2 and two is None:two=b.date
        q=float(a['filled_quantity']);fee=float(a['entry_fee']);peakvalue=peakprice*.999*q
        peaknet=peakvalue-buy*q-fee-max(5,peakvalue*.0003)-peakvalue*.0005
        pnl=float(t['pnl']) if t else (by[end].close*by[end].factor/factor-buy)*q-fee
        records.append(dict(symbol=a['symbol'],setup_id=pid,signal=p['date'],entry=a['date'],exit=t['exit_date'] if t else '',closed=bool(t),pnl=pnl,
            buy=buy,entry_neckline=neck,right_low=right,signal_atr=atr,initial_stop=stop,stop_pct=(buy-stop)/buy,stop_atr=(buy-stop)/atr,
            buffer_share_of_stop_distance=.5*atr/(buy-stop),entry_neck_atr=(buy-neck)/atr,target=target,target_upside=target/buy-1,planned_net_rr=float(a['net_rr']),
            nearest_pressure=nearest['price']/factor if nearest else None,nearest_pressure_confirmed=nearest['confirmed'] if nearest else '',
            nearest_pressure_gross_R=(nearest['price']/factor-buy)/(buy-stop) if nearest else None,
            target_touched_before_exit=any(b.high*b.factor/factor>=target for b in held),target_closed_above_before_exit=any(b.close*b.factor/factor>=target for b in held),
            peak_close_date=peak.date,peak_close_gain=peakprice/buy-1,peak_net_R=peaknet/float(a['expected_loss']),final_R=pnl/float(a['expected_loss']),
            protection_raise_count=len(raises),first_protection_date=raises[0]['date'] if raises else '',first_protection_above_buy=break_even[0]['date'] if break_even else '',
            below_neckline_close_count=len(below),first_below_neckline=below[0] if below else '',two_closes_below_neckline=two or '',
            reason=t['reason'] if t else 'open',exit_price_entry_basis=float(t['exit'])*by[end].factor/factor if t else None))
    summary=dict(buys=len(records),closed=sum(r['closed'] for r in records),checks_passed=True,exit_reasons=dict(Counter(r['reason'] for r in records)),
        metrics={k:dict(min=min(r[k] for r in records),median=median(r[k] for r in records),max=max(r[k] for r in records)) for k in ('stop_pct','stop_atr','buffer_share_of_stop_distance','entry_neck_atr','target_upside','planned_net_rr')},
        target_touched=sum(r['target_touched_before_exit'] for r in records),target_closed_above=sum(r['target_closed_above_before_exit'] for r in records),
        known_overhead_pressure=sum(r['nearest_pressure'] is not None for r in records),pressure_lt1R=sum(r['nearest_pressure_gross_R'] is not None and r['nearest_pressure_gross_R']<1 for r in records),
        pressure_lt3R=sum(r['nearest_pressure_gross_R'] is not None and r['nearest_pressure_gross_R']<3 for r in records),
        no_support_raised=sum(not r['first_protection_date'] for r in records),
        two_neckline_closes={kind:dict(count=sum(bool(r['two_closes_below_neckline']) for r in records if r['closed'] and (r['pnl']>0)==(kind=='winner')),total=sum(r['closed'] and (r['pnl']>0)==(kind=='winner') for r in records)) for kind in ('winner','loser')})
    save(OUT/'price-lines.csv',records);dump(OUT/'summary.json',summary)
    dump(OUT/'method.json',dict(source=str(BASE),kind='diagnosis only; no new exit or entry backtest',target='theoretical neckline plus head depth, reference only; touch measured before exit day, includes unsellable entry day',
        pressure='nearest weekly high confirmed before entry, above buy; gross distance/R is an obstacle diagnostic, not forecast or realized reward',
        neckline='frozen two-anchor sloped neckline at each calendar date; two closes is observed path, not simulated achievable improvement',
        protections='first raised dates are confirmation dates, effective next stock session; above-buy is gross break-even, not fee-aware break-even'))
    print(summary)

if __name__=='__main__':main()
