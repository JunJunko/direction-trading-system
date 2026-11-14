"""Descriptive trade-path audit; post-exit observations are not executable returns."""
import csv,json,statistics,html
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v2'
STUDY=ROOT/'runs/20261025-ihs-causal-exits'
OUT=ROOT/'audits/20261025-ihs-win-rate'
def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    trades=rows(STUDY/'paired/C0/trades.csv')
    buys={r['setup_id']:r for r in rows(STUDY/'buy-position-audit.csv') if r['arm']=='C0'}
    syms={r['symbol'] for r in trades};data=defaultdict(list)
    with (BASE/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in syms:data[r['symbol']].append(r)
    result=[]
    for t in trades:
        a=buys[t['setup_id']];bars=sorted(data[t['symbol']],key=lambda r:r['date'])
        ix={r['date']:i for i,r in enumerate(bars)};start=ix[t['entry_date']]
        anchor=float(bars[start]['factor']);price=lambda r,k:float(r[k])*float(r['factor'])/anchor
        entry=float(t['entry']);stop=float(t['initial_stop']);target=float(a['target']);neck=float(a['neckline'])
        end=ix[t['exit_date']] if t['exit_date'] else len(bars)
        held=bars[start:end] # exclude exit day: cannot infer intraday order
        next5=held[:5]
        pre=bars[:ix[a['signal_date']]+1]
        tr=[max(price(pre[i],'high')-price(pre[i],'low'),abs(price(pre[i],'high')-price(pre[i-1],'close')),abs(price(pre[i],'low')-price(pre[i-1],'close'))) for i in range(len(pre)-15,len(pre)-1)]
        atr=statistics.mean(tr)
        after=bars[end+1:end+21] if t['exit_date'] else []
        r=dict(symbol=t['symbol'],setup_id=t['setup_id'],entry_date=t['entry_date'],exit_date=t['exit_date'],
            reason=t['reason'],pnl=float(t['net_pnl']),closed=bool(t['exit_date']),
            below_neck=entry<neck,entry_premium=entry/neck-1,stop_distance=(entry-stop)/entry,
            stop_distance_atr=(entry-stop)/atr,target_distance_atr=(target-entry)/atr,
            pattern_days=int(a['days_left_to_head'])+int(a['days_head_to_right']),asymmetry=float(a['temporal_asymmetry']),
            held_bars=int(t['held_bars']),mfe_R=float(t['MFE'])/float(t['initial_risk']),
            close_below_neck_first5_held=any(price(b,'close')<neck for b in next5),
            high_touched_target_before_exit=any(price(b,'high')>=target for b in held),
            close_reached_target_before_exit=any(price(b,'close')>=target for b in held),
            post_exit_bars=len(after),post_exit_full20=len(after)==20,
            post_exit_close_recovered_entry=any(price(b,'close')>=entry for b in after),
            post_exit_close_recovered_neck=any(price(b,'close')>=neck for b in after),
            post_exit_high_reached_target=any(price(b,'high')>=target for b in after))
        result.append(r)
    closed=[r for r in result if r['closed']];loss=[r for r in closed if r['pnl']<0];wins=[r for r in closed if r['pnl']>0]
    describe=lambda rr:dict(n=len(rr),wins=sum(r['pnl']>0 for r in rr),pnl=sum(r['pnl'] for r in rr),
        mean_stop_atr=statistics.mean(r['stop_distance_atr'] for r in rr) if rr else None,
        median_pattern_days=statistics.median(r['pattern_days'] for r in rr) if rr else None)
    avgwin=statistics.mean(r['pnl'] for r in wins);avgloss=-statistics.mean(r['pnl'] for r in loss)
    stats=dict(closed=describe(closed),wins=describe(wins),losses=describe(loss),
        open=describe([r for r in result if not r['closed']]),win_rate=len(wins)/len(closed),
        mean_win=avgwin,mean_loss=avgloss,realized_payoff=avgwin/avgloss,
        break_even_win_rate_at_observed_payoff=avgloss/(avgwin+avgloss),
        closed_below_neck=describe([r for r in closed if r['below_neck']]),
        closed_at_or_above_neck=describe([r for r in closed if not r['below_neck']]),
        losses_mfe_less_1R=sum(r['mfe_R']<1 for r in loss),losses_mfe_at_least_1R=sum(r['mfe_R']>=1 for r in loss),
        losses_mfe_at_least_2R=sum(r['mfe_R']>=2 for r in loss),
        losses_within_5_held_bars=sum(r['held_bars']<=5 for r in loss),
        losses_close_below_neck_first5=sum(r['close_below_neck_first5_held'] for r in loss),
        wins_close_below_neck_first5=sum(r['close_below_neck_first5_held'] for r in wins),
        losses_intraday_target_touch=sum(r['high_touched_target_before_exit'] for r in loss),
        losses_close_target=sum(r['close_reached_target_before_exit'] for r in loss),
        losers_full20_after_exit=sum(r['post_exit_full20'] for r in loss),
        losers_full20_recover_entry=sum(r['post_exit_full20'] and r['post_exit_close_recovered_entry'] for r in loss),
        losers_full20_reach_target=sum(r['post_exit_full20'] and r['post_exit_high_reached_target'] for r in loss),
        full20_postexit_cases=[r for r in loss if r['post_exit_full20'] and r['post_exit_close_recovered_entry']],
        losses_under_1ATR_stop=sum(r['stop_distance_atr']<1 for r in loss),
        losses_target_over_10ATR=sum(r['target_distance_atr']>10 for r in loss),
        short_pattern_closed=describe([r for r in closed if r['pattern_days']<=120]),
        long_pattern_closed=describe([r for r in closed if r['pattern_days']>365]))
    (OUT/'summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    with (OUT/'trade-path-audit.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(result[0]));w.writeheader();w.writerows(result)
    print(json.dumps({k:v for k,v in stats.items() if k!='full20_postexit_cases'},ensure_ascii=False,indent=2))
    (OUT/'source.py').write_bytes(Path(__file__).read_bytes())
if __name__=='__main__':main()
