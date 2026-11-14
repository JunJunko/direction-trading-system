"""Shared-account recheck and execution-cost stress; fixed signals, variable fills."""
import sys,json,csv,copy
from pathlib import Path
from collections import defaultdict
sys.path.insert(0,'src');sys.path.insert(0,'scripts')
from trading_system.domain import Bar,Intent
from trading_system.engine import Backtest
from trading_system.strategies.causal_target_w import CausalTargetW
from trading_system.data import save_csv
from trading_system.universe import MainboardUniverse
from backtest_daily_direction import assert_recorded
ROOT=Path('runs/20261024-qualified-w-cohort');OUT=Path(sys.argv[1] if len(sys.argv)>1 else 'runs/20261024-causal-account-verified')
load=lambda p:json.loads(p.read_text(encoding='utf-8'))
def run():
    OUT.mkdir();config=load(ROOT/'candidate/config.json');plans=load(ROOT/'plans.json');cal=load(ROOT/'calendar.json');u=load(ROOT/'universe.json')
    with (ROOT/'bars.csv').open(encoding='utf-8-sig') as f:bars=[Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}) for r in csv.DictReader(f)]
    by_day=defaultdict(list)
    for p in plans:by_day[(p['symbol'],p['date'])].append(p)
    class Replay(CausalTargetW):
        def on_close(self,history,week_ends):
            b=history[-1]
            return [Intent(self.name,p['symbol'],p['date'],p['trigger'],p['stop'],p['target'],p['setup_id'],'direct_w',dict(p)) for p in by_day[(b.symbol,b.date)]],[]
    records=[]
    for scenario,commission,slip in [('base',1,1),('cost_1_5x',1.5,1.5),('cost_2x',2,2)]:
        for arm in ('C0','C1','C2','C3','C4'):
            c=copy.deepcopy(config);c['execution']['commission_rate']*=commission;c['execution']['slippage']*=slip
            params=dict(c['strategies'][0]['params'],target_arm=arm,minimum_price_tick=.01)
            s=Replay(c['strategies'][0]['id'],params)
            e=Backtest(c,[s]).run(bars,cal['open_dates'],set(cal['week_ends']),evaluation_start='20251009',evaluation_end='20260930',universe=MainboardUniverse(u['stocks'],u['st_by_date']))
            if arm=='C0' and scenario=='base':
                for name,data in [('orders',e.orders),('trades',e.trades),('entry_audit',e.entry_audits),('equity',e.curve)]:assert_recorded(ROOT/'candidate'/(name+'.csv'),data)
            folder=OUT/scenario/arm;folder.mkdir(parents=True)
            for name,data in [('orders',e.orders),('trades',e.trades),('entry_audit',e.entry_audits),('equity',e.curve)]:save_csv(folder/(name+'.csv'),data)
            with (folder/'events.jsonl').open('w',encoding='utf-8') as f:
                for event in e.events:f.write(json.dumps(event,ensure_ascii=False)+'\n')
            c['strategies'][0].update(type='causal_target_w',params=params)
            (folder/'config.json').write_text(json.dumps(c,indent=2),encoding='utf-8')
            summary=e.summary();(folder/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
            pnl=[t['pnl'] for t in e.trades]
            rec=dict(scenario=scenario,arm=arm,net_pnl=e.curve[-1]['equity']-c['initial_cash'],
                return_pct=(e.curve[-1]['equity']/c['initial_cash']-1)*100,max_drawdown_pct=-min(x['drawdown'] for x in e.curve)*100,
                trades=len(pnl),open_positions=len(e.positions),mean_net_pnl=sum(pnl)/len(pnl) if pnl else None,
                worst_trade=min(pnl) if pnl else None,win_rate=sum(p>0 for p in pnl)/len(pnl) if pnl else None,
                total_fees=sum(o.get('fee',0) for o in e.orders),min_cash=min(x['cash'] for x in e.curve),
                max_positions=max(x['positions'] for x in e.curve),max_gross_weight=max(x['gross_weight'] for x in e.curve))
            records.append(rec);print(json.dumps(rec),flush=True)
    save_csv(OUT/'comparison.csv',records)
    (OUT/'protocol.json').write_text(json.dumps(dict(signals=99,pool=62,baseline_exact=True,
        shared_account=True,automatic_risk_policy_unchanged=True,
        cost_stress='commission rate and slippage multiplied; min commission and sell tax unchanged; actual fills and entry risk gates recomputed',
        scope='fixed original 99 signal tape, shared account; not an all-market account test; no new orders without original signals',
        live_trading=False),indent=2),encoding='utf-8')
if __name__=='__main__':run()
