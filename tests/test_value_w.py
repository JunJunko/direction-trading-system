import json
from pathlib import Path
import unittest
import test_w_retest as fixtures
from trading_system.strategies.value_w import ValueW
from trading_system.domain import Bar,Position
from trading_system.engine import Backtest

class ValueWTests(unittest.TestCase):
    def test_limit_fill_never_exceeds_cap_and_keeps_same_day_loss(self):
        _,_,i=fixtures.RetestTests().signal()
        s=ValueW('test',{'limit_entry_distance':.0125});i=s.price_intent(i)
        c=json.loads((Path(__file__).resolve().parents[1]/'configs/experiments/double_bottom_v5_21_value_w_structure.json').read_text())
        e=Backtest(c,[s]);e.pending=[i]
        e.execute_interval({'X':Bar('X','20250109',11.3,11.4,11.05,11.2,100)},'20250109',None,e.cash)
        self.assertEqual(e.positions['X'].entry,i.trigger)
        self.assertEqual(e.positions['X'].plan['t1_stop_breached_at'],'20250109')

    def test_no_touch_expires_without_chasing(self):
        _,_,i=fixtures.RetestTests().signal();s=ValueW('test',{'limit_entry_distance':.0125});i=s.price_intent(i)
        c=json.loads((Path(__file__).resolve().parents[1]/'configs/experiments/double_bottom_v5_21_value_w_structure.json').read_text())
        e=Backtest(c,[s]);e.pending=[i]
        e.execute_interval({'X':Bar('X','20250109',11.3,11.4,11.25,11.35,100)},'20250109',None,e.cash)
        self.assertFalse(e.positions);self.assertEqual(e.entry_audits[-1]['execution_reason'],'limit_entry_not_touched')

    def test_limit_up_still_raises_support_for_next_session(self):
        s=ValueW('test',{});p=Position('test','X','20250101',10,100,9,100,5,'id',1,dict(w_target=11),10)
        exits,events=s.manage_position([Bar('X','20250102',12,12,12,12,100,up_limit=12)],p)
        self.assertFalse(exits);self.assertEqual(p.stop,11)
        self.assertEqual(events[0]['event'],'dynamic_support_raised')
