import sys,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.strategies.dynamic_w_exit import DynamicWExit
from trading_system.domain import Position,Bar,ExitIntent
from trading_system.engine import Backtest
class DynamicExitTests(unittest.TestCase):
 def fixture(self):
  s=DynamicWExit('x',{});p=Position('x','X','20250101',10,100,9,100,5,'id',1,dict(w_target=11),10);return s,p
 def test_limit_up_promotes_target_without_selling(self):
  s,p=self.fixture();exits,events=s.manage_position([Bar('X','20250102',12,12,12,12,100,up_limit=12)],p)
  self.assertFalse(exits);self.assertEqual(p.plan['broken_pressure'],11);self.assertIsNone(p.plan['dynamic_pressure'])
 def test_breakout_failure_requests_next_open_exit(self):
  s,p=self.fixture();p.plan.update(broken_pressure=11,dynamic_pressure=None)
  exits,_=s.manage_position([Bar('X','20250103',11,11.1,10.7,10.8,100)],p)
  self.assertEqual(exits[0].reason,'broken_pressure_failed')
 def test_pending_profit_exit_cancelled_at_limit_up_open(self):
  s,p=self.fixture();p.plan['hold_limit_up_profit']=True
  c=json.loads((Path(__file__).resolve().parents[1]/'configs/experiments/double_bottom_v5_20_dynamic_exit_structure.json').read_text())
  e=Backtest(c,[s]);e.positions['X']=p;e.marks['X']=10;e.pending_exits=[ExitIntent('x','X','20250101','id','broken_pressure_failed')]
  e.execute_interval({'X':Bar('X','20250102',12,12,12,12,100,up_limit=12)},'20250102',None,e.cash)
  self.assertIn('X',e.positions);self.assertFalse(e.trades);self.assertFalse(e.pending_exits)
