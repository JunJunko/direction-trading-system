"""Separate weak entries, positive excursions and trading frictions in two W accounts."""
import math
from statistics import mean,median
from audit_pattern_trade_paths import ROOT,history,load,rows,dump,save

OUT=ROOT/'runs/20261110-w-expectancy-diagnosis'
CASES={'baseline':ROOT/'runs/20261110-quality-entry/W_baseline_cost1',
       'no_gap_up':ROOT/'runs/20261110-quality-entry/W_no_gap_up_cost1'}

def main():
    OUT.mkdir(exist_ok=True)
    buys={k:[a for a in rows(p/'entry_audit.csv') if a['execution_reason']=='filled'] for k,p in CASES.items()}
    hist=history({a['symbol'] for items in buys.values() for a in items});result={};records=[]
    calendar=load(ROOT/'runs/20261110-quality-entry/calendar.json')['open_dates'];ci={d:i for i,d in enumerate(calendar)}
    for name,path in CASES.items():
        trades={t['setup_id']:t for t in rows(path/'trades.csv')};cfg=load(path/'config.json')['execution'];summary=load(path/'summary.json');own=[]
        for a in buys[name]:
            h=hist[a['symbol']];by={b.date:b for b in h};entry=by[a['date']];t=trades.get(a['setup_id']);exit=t['exit_date'] if t else '20260930'
            held=[b for b in h if a['date']<=b.date<=exit and (not t or b.date<exit)]
            q=float(a['filled_quantity']);fill=float(a['fill']);fee=float(a['entry_fee']);risk=float(a['expected_loss'])
            def net(price):
                value=price*(1-cfg['slippage'])*q
                return value-fill*q-fee-max(cfg['minimum_commission'],value*cfg['commission_rate'])-value*cfg['sell_tax_after_20230828']
            peak=max(b.close*b.factor/entry.factor for b in held);peak_net=net(peak)
            pnl=float(t['pnl']) if t else (by[exit].close*by[exit].factor/entry.factor-fill)*q-fee
            record=dict(case=name,symbol=a['symbol'],setup_id=a['setup_id'],entry=a['date'],exit=t['exit_date'] if t else '',closed=bool(t),pnl=pnl,
                held_sessions=ci[exit]-ci[a['date']],entry_day_touch=entry.low<=float(a['stop']),
                peak_close_gain=peak/fill-1,peak_close_net=peak_net,peak_net_R=peak_net/risk,final_R=pnl/risk,
                giveback_from_positive_close=max(peak_net,0)-pnl,reason=t['reason'] if t else 'open')
            own.append(record);records.append(record)
        assert math.isclose(sum(r['pnl'] for r in own),summary['final_equity']-1e6,abs_tol=1e-5)
        closed=[r for r in own if r['closed']];wins=[r for r in closed if r['pnl']>0];losses=[r for r in closed if r['pnl']<0]
        aw=mean(r['pnl'] for r in wins);al=-mean(r['pnl'] for r in losses)
        groups={
            'loss_peak_net_nonpositive':[r for r in losses if r['peak_close_net']<=0],
            'loss_peak_net_positive_lt1R':[r for r in losses if 0<r['peak_net_R']<1],
            'loss_peak_1R_to2R':[r for r in losses if 1<=r['peak_net_R']<2],
            'loss_peak_ge2R':[r for r in losses if r['peak_net_R']>=2],
            'loss_peak_gain_lt3pct':[r for r in losses if r['peak_close_gain']<.03],
            'loss_peak_gain_ge5pct':[r for r in losses if r['peak_close_gain']>=.05],
            'loss_next_exchange_session':[r for r in losses if r['held_sessions']==1]}
        fees=sum(float(o['fee']) for o in rows(path/'orders.csv') if o['status']=='filled')
        result[name]=dict(buys=len(own),closed=len(closed),wins=len(wins),losses=len(losses),total_return=summary['total_return'],
            realized_pnl=sum(r['pnl'] for r in closed),open_pnl=sum(r['pnl'] for r in own if not r['closed']),
            gross_winner_sum=sum(r['pnl'] for r in wins),gross_loser_sum=sum(r['pnl'] for r in losses),
            average_win=aw,average_loss=al,payoff_ratio=aw/al,breakeven_win_rate=al/(aw+al),actual_win_rate=len(wins)/len(closed),
            expectancy_per_closed_trade=mean(r['pnl'] for r in closed),mean_realized_R=mean(r['final_R'] for r in closed),
            entry_day_stop_touches=sum(r['entry_day_touch'] for r in own),commission_and_tax=fees,
            total_pnl_before_commission_and_tax=summary['final_equity']-1e6+fees,
            groups={k:dict(count=len(v),loss_pnl=sum(r['pnl'] for r in v),peak_positive_net_sum=sum(max(0,r['peak_close_net']) for r in v)) for k,v in groups.items()})
    save(OUT/'trade-diagnosis.csv',records)
    dump(OUT/'summary.json',result)
    dump(OUT/'method.json',dict(cases={k:str(p) for k,p in CASES.items()},peak='Maximum adjusted close from entry session through session BEFORE actual sale; no exit-day or post-exit hindsight. Hypothetical after-fee liquidation benchmark only; not an executable exit strategy. T+1 means entry-day close profits may be unsellable.',
        groups='Four net-R groups partition losses; percentage and next-session groups overlap. Fees are recorded commission/tax only, excluding slippage. Before-fee total is same fixed trades, not a new account simulation.',
        interpretation='Empirical realized expectancy in a previously studied historical interval; no random/time-matched control for alpha, no independent holdout claim.'))
    print(result)

if __name__=='__main__':main()
