"""Describe pre-entry features of the fixed baseline, not a threshold search."""
from backtest_reentry_daily_protection import ROOT,load,rows,dump
from audit_pattern_trade_paths import history,save
from trading_system.ihs_entry_quality_research import entry_features,extra_pass,RULES
from trading_system.domain import Intent

OUT=ROOT/'runs/20261110-ihs-entry-quality'
BASE=ROOT/'runs/20261110-quality-entry'

def main():
    OUT.mkdir(exist_ok=True);folder=BASE/'IHS_no_gap_up_cost1'
    fills=[a for a in rows(folder/'entry_audit.csv') if a['execution_reason']=='filled']
    plans={e['setup_id']:e for e in rows(folder/'decisions.csv') if e['event']=='entry_intent'}
    trades={t['setup_id']:t for t in rows(folder/'trades.csv')};hist=history({a['symbol'] for a in fills});records=[]
    for a in fills:
        h=hist[a['symbol']];b=next(b for b in h if b.date==a['date']);p=plans[a['setup_id']]
        intent=Intent(a['strategy'],a['symbol'],p['date'],float(p['trigger']),float(p['stop']),float(p['target']),a['setup_id'],'inverse_head_shoulders',p)
        f=entry_features(intent,h,a['date'],b.factor,b.open);t=trades.get(a['setup_id'])
        records.append(dict(symbol=a['symbol'],setup_id=a['setup_id'],signal=p['date'],entry=a['date'],closed=bool(t),pnl=float(t['pnl']) if t else '',**f,**{rule:extra_pass(rule,f) for rule in sorted(RULES)}))
    save(OUT/'baseline-preentry-features.csv',records)
    stats={rule:{str(passed):dict(count=sum(r[rule]==passed for r in records),closed_pnl=sum(r['pnl'] for r in records if r[rule]==passed and r['closed'])) for passed in (True,False)} for rule in sorted(RULES)}
    dump(OUT/'baseline-profile.json',stats);print(stats)

if __name__=='__main__':main()
