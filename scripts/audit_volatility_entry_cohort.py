"""Classify unchanged v7 fills by pre-entry ATR; no reallocation in this diagnostic."""
import csv,json,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/20261026-volatility-entry-filter'
BASE=ROOT/'runs/20261026-c2-full-comparable/combined_v7'
sys.path.insert(0,str(OUT/'source/src'))
from trading_system.domain import Bar
from trading_system.volatility_entry_research import prior_atr
def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def save(p,data):
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
def main():
    fills=[a for a in rows(BASE/'entry_audit.csv') if a['execution_reason']=='filled']
    needed={a['symbol'] for a in fills};histories=defaultdict(list)
    with (OUT/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in needed:
                histories[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    for h in histories.values():h.sort(key=lambda b:b.date)
    factors={(b.symbol,b.date):b.factor for h in histories.values() for b in h}
    trades={(t['setup_id'],t['entry_date']):t for t in rows(BASE/'trades.csv')}
    data=[]
    for a in fills:
        atr,known=prior_atr(histories[a['symbol']],a['date'],factors[a['symbol'],a['date']])
        assert atr and known<a['date']
        trade=trades.get((a['setup_id'],a['date']))
        data.append(dict(symbol=a['symbol'],setup_id=a['setup_id'],entry_date=a['date'],family='W' if 'double_bottom' in a['strategy'] else 'IHS',
            fill=float(a['fill']),stop=float(a['stop']),stop_pct=(float(a['fill'])-float(a['stop']))/float(a['fill'])*100,
            atr=atr,atr_known_at=known,stop_atr=(float(a['fill'])-float(a['stop']))/atr,
            closed=bool(trade),pnl=float(trade['pnl']) if trade else None,exit_reason=trade['reason'] if trade else None))
    save(OUT/'baseline-entry-volatility.csv',data)
    comparison=[]
    for label,scope,k in [('W_ATR025','W',.25),('W_ATR050','W',.5),('W_ATR100','W',1.),('both_ATR050','both',.5)]:
        removed=[r for r in data if (scope=='both' or r['family']=='W') and r['stop_atr']+1e-12<k]
        closed=[r for r in removed if r['closed']];wins=[r for r in closed if r['pnl']>0];losses=[r for r in closed if r['pnl']<0]
        comparison.append(dict(case=label,baseline_entries_filtered=len(removed),closed_filtered=len(closed),
            winners_filtered=len(wins),losers_filtered=len(losses),winning_pnl_removed=sum(r['pnl'] for r in wins),
            losing_pnl_avoided=-sum(r['pnl'] for r in losses),removed_net_pnl=sum(r['pnl'] for r in closed),
            open_entries_filtered=len(removed)-len(closed)))
    save(OUT/'fixed-entry-filter-diagnostic.csv',comparison)
    print(json.dumps(dict(fixed_entries=comparison,example=[r for r in data if r['symbol']=='002234.SZ']),ensure_ascii=False),flush=True)
if __name__=='__main__':main()
