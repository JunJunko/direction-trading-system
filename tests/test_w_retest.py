import json
import sys
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trading_system.strategies.w_retest import WRetest
from trading_system.domain import Bar
from trading_system.engine import Backtest


class RetestTests(unittest.TestCase):
    def seed(self,params=None):
        s=WRetest('test',params or {})
        bars=[Bar('X',f'202501{i+1:02}',v,v+.2,v-.2,v,100) for i,v in enumerate([12,10,11,10.1,10.5,11.3])]
        w=dict(first=1,second=3,neckline=11.2,bottom=9.8,first_breakout_index=5,pattern_area=5)
        with patch('trading_system.strategies.direct_double_bottom.hierarchy_double_bottom_candidates',return_value=([w],'qualified')):
            intents,events=s.on_close(bars,set())
        self.assertFalse(intents);self.assertEqual(events[-1]['event'],'w_retest_registered')
        return s,bars

    def advance(self,s,bars,bar):
        bars.append(bar)
        with patch('trading_system.strategies.direct_double_bottom.hierarchy_double_bottom_candidates',return_value=([],'none')):
            return s.on_close(bars,set())

    def signal(self):
        s,bars=self.seed()
        self.advance(s,bars,Bar('X','20250107',11.35,11.4,11.1,11.15,100))
        intents,_=self.advance(s,bars,Bar('X','20250108',11.15,11.4,11.12,11.3,100))
        return s,bars,intents[0]

    def test_local_stop_keeps_W_floor_and_target(self):
        s,bars,i=self.signal()
        self.assertEqual(i.stop,11.1);self.assertEqual(i.evidence['w_floor'],9.8)
        self.assertAlmostEqual(i.target,12.6)
        self.assertEqual(i.evidence['w_known_at'],'20250106')
        self.assertEqual(i.evidence['w_retest_low_date'],'20250107')
        self.assertEqual(s.on_close(bars,set()),([],[]))
        self.assertFalse(s.waiting['X'])

    def test_no_touch_no_trade(self):
        s,bars=self.seed()
        intents,_=self.advance(s,bars,Bar('X','20250107',11.4,11.6,11.35,11.5,100))
        self.assertFalse(intents)

    def test_failed_retest_cannot_be_revived(self):
        s,bars=self.seed()
        intents,events=self.advance(s,bars,Bar('X','20250107',11.3,11.5,10.8,11.4,100))
        self.assertFalse(intents);self.assertEqual(events[0]['reason'],'neckline_retest_failed')
        intents,_=self.advance(s,bars,Bar('X','20250108',11.2,11.5,11.1,11.4,100))
        self.assertFalse(intents)

    def test_target_touched_before_entry_cancels(self):
        s,bars=self.seed()
        intents,events=self.advance(s,bars,Bar('X','20250107',11.3,12.7,11.1,11.4,100))
        self.assertFalse(intents);self.assertEqual(events[0]['reason'],'target_already_touched')

    def test_expiry(self):
        s,bars=self.seed({'retest_sessions':1})
        self.advance(s,bars,Bar('X','20250107',11.4,11.6,11.35,11.5,100))
        intents,events=self.advance(s,bars,Bar('X','20250108',11.2,11.5,11.1,11.4,100))
        self.assertFalse(intents);self.assertEqual(events[0]['reason'],'expired')

    def test_same_day_loss_keeps_open_fill_and_defers_sale(self):
        s,bars,i=self.signal()
        c=json.loads((ROOT/'configs/experiments/double_bottom_v5_18_w_retest_structure.json').read_text())
        e=Backtest(c,[s]);e.pending=[i]
        e.execute_interval({'X':Bar('X','20250109',11.3,11.4,11.05,11.2,100)},'20250109',None,1e6)
        self.assertIn('X',e.positions)
        self.assertEqual(e.positions['X'].plan['t1_stop_breached_at'],'20250109')
        e.execute_interval({'X':Bar('X','20250110',11.3,11.4,11.2,11.3,100)},'20250110',None,e.cash)
        self.assertNotIn('X',e.positions);self.assertEqual(e.trades[0]['reason'],'deferred_support_break')

    def test_gap_invalidates_or_reaudits_distance(self):
        s,bars,i=self.signal()
        c=json.loads((ROOT/'configs/experiments/double_bottom_v5_18_w_retest_structure.json').read_text())
        for price,reason in [(11.05,'support_invalidated_at_open'),(11.5,'entry_too_far_from_W_retest')]:
            e=Backtest(c,[s]);e.pending=[i]
            e.execute_interval({'X':Bar('X','20250109',price,price+.1,price-.1,price,100)},'20250109',None,1e6)
            self.assertFalse(e.positions);self.assertEqual(e.entry_audits[-1]['execution_reason'],reason)

    def test_factor_change_during_wait_preserves_geometry(self):
        s,bars=self.seed()
        self.advance(s,bars,Bar('X','20250107',5.675,5.7,5.55,5.575,100,factor=2))
        intents,_=self.advance(s,bars,Bar('X','20250108',5.575,5.7,5.56,5.65,100,factor=2))
        self.assertAlmostEqual(intents[0].stop,5.55)
        self.assertAlmostEqual(intents[0].evidence['w_floor'],4.9)
        self.assertAlmostEqual(intents[0].target,6.3)

    def test_invalid_parameters(self):
        for p in ({'retest_sessions':True},{'touch_tolerance':float('nan')},{'max_entry_risk':0}):
            with self.assertRaises(ValueError):WRetest('x',p)
