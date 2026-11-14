import sys,json,csv,copy,shutil
from pathlib import Path
sys.path.insert(0,'src');sys.path.insert(0,'scripts')
from trading_system.domain import Bar,Intent
from trading_system.engine import Backtest
from trading_system.strategies.dynamic_w_exit import DynamicWExit
from trading_system.strategies.qualified_w_retest import QualifiedWRetest
from trading_system.universe import MainboardUniverse
from trading_system.data import save_csv
from backtest_daily_direction import assert_recorded
root=Path('runs/20261024-qualified-w-cohort');out=Path('runs/20261024-dynamic-exit-cohort');out.mkdir()
load=lambda p:json.loads(p.read_text(encoding='utf-8'))
plans=load(root/'plans.json');cal=load(root/'calendar.json');u=load(root/'universe.json')
with (root/'bars.csv').open(encoding='utf-8-sig') as f:bars=[Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}) for r in csv.DictReader(f)]
def run(base,c,label):
 class Replay(base):
  def on_close(self,history,week_ends):
   b=history[-1];ps=[p for p in plans if p['date']==b.date and p['symbol']==b.symbol]
   return [Intent(self.name,p['symbol'],p['date'],p['trigger'],p['stop'],p['target'],p['setup_id'],'direct_w',dict(p)) for p in ps],[]
 s=Replay(c['strategies'][0]['id'],c['strategies'][0]['params'])
 e=Backtest(c,[s]).run(bars,cal['open_dates'],set(cal['week_ends']),evaluation_start='20251009',evaluation_end='20260930',universe=MainboardUniverse(u['stocks'],u['st_by_date']))
 folder=out/label;folder.mkdir()
 for name,records in [('orders',e.orders),('trades',e.trades),('entry_audit',e.entry_audits),('equity',e.curve),('decisions',e.events)]:save_csv(folder/(name+'.csv'),records)
 (folder/'summary.json').write_text(json.dumps(e.summary(),indent=2));return e
old=run(QualifiedWRetest,load(root/'candidate/config.json'),'baseline')
for name,records in [('orders',old.orders),('trades',old.trades),('entry_audit',old.entry_audits),('equity',old.curve)]:assert_recorded(root/'candidate'/(name+'.csv'),records)
assert old.summary()==load(root/'candidate/summary.json')
c=load(Path('configs/experiments/double_bottom_v5_20_dynamic_exit_structure.json'))
new=run(DynamicWExit,c,'candidate')
shutil.copytree('src',out/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
(out/'config.json').write_text(json.dumps(c,indent=2))
result=dict(scope='frozen 99 signal plans on same 62 stocks; shared-account replay, not full-market',baseline_exact=True,baseline=old.summary(),candidate=new.summary())
(out/'comparison.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
