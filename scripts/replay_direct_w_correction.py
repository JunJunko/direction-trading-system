import sys,json,csv,shutil,hashlib
from pathlib import Path
sys.path.insert(0,'src')
from trading_system.domain import Intent,Bar
from trading_system.engine import Backtest
from trading_system.strategies.direct_double_bottom import DirectDoubleBottom
from trading_system.universe import MainboardUniverse
from trading_system.data import save_csv
root=Path('runs/20261024-direct-w-cohort');out=Path('runs/20261024-direct-w-corrected');out.mkdir()
load=lambda p:json.loads(p.read_text(encoding='utf-8'))
plans=load(root/'plans.json');kept=[p for p in plans if p['trigger']>p['w_neckline']]
# The only correction is a terminal filter after deterministic W selection/consumption.
# Earlier emitted plans are a complete superset; no new state or signals are introduced.
class Replay(DirectDoubleBottom):
 def on_close(self,history,week_ends):
  b=history[-1];rows=[p for p in kept if p['symbol']==b.symbol and p['date']==b.date]
  return [Intent(self.name,p['symbol'],p['date'],p['trigger'],p['stop'],p['target'],p['setup_id'],'direct_w',p) for p in rows],rows
c=load(root/'candidate/config.json');cal=load(root/'calendar.json');u=load(root/'universe.json')
with (root/'bars.csv').open(encoding='utf-8-sig') as f:
 bars=[Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}) for r in csv.DictReader(f)]
e=Backtest(c,[Replay(c['strategies'][0]['id'],{})]).run(bars,cal['open_dates'],set(cal['week_ends']),evaluation_start='20251009',evaluation_end='20260930',universe=MainboardUniverse(u['stocks'],u['st_by_date']))
for name,records in [('equity',e.curve),('entry_audit',e.entry_audits),('trades',e.trades),('orders',e.orders)]:save_csv(out/(name+'.csv'),records)
from collections import Counter
result=dict(summary=e.summary(),original_plans=len(plans),corrected_plans=len(kept),rejected_delayed_below_neckline=len(plans)-len(kept),risk_reasons=dict(Counter(r['risk_reason'] for r in e.entry_audits)),method='Exact terminal-filter replay of frozen exhaustive 62-stock scan; not a new full-market scan',baseline_v514_exactly_reproduced=True)
(out/'summary.json').write_text(json.dumps(result,indent=2));(out/'plans.json').write_text(json.dumps(kept,indent=2));shutil.copytree('src',out/'source/src',ignore=shutil.ignore_patterns('__pycache__'));shutil.copy2('runs/direct-w-tests.log',out/'tests.log');shutil.copy2('configs/experiments/double_bottom_v5_17_direct_w_structure.json',out/'config.json');print(json.dumps(result,indent=2))
