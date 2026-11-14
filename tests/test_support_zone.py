import json
import math
import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Bar,Intent,Position
from trading_system.engine import Backtest
from trading_system.risk import RiskManager
from trading_system.strategies import build_strategies
from trading_system.support import confirmed_trough_zone


def config():
    return json.loads((ROOT/'configs/experiments/double_bottom_v5_13_support_zone_structure.json').read_text(encoding='utf-8'))


def evidence():
    return dict(support_mode='confirmed_trough',support_lower=9.8,support_upper=9.9,
                support_max_entry_risk=.02,support_exit_on_touch=True)


class Fixture:
    name='fixture'
    def on_close(self,*args):return [],[]
    def trailing_stop(self,h,p):return p.stop


class SupportZoneTests(unittest.TestCase):
    def engine(self):
        return Backtest(config(),[Fixture()])

    def position(self,e,entry_date='20240101'):
        p=Position('fixture','X',entry_date,10,100,9.8,25,5,'id',1,evidence())
        e.positions['X']=p;e.marks['X']=10
        return p

    def test_zone_requires_confirmation_and_cannot_use_future_candle(self):
        bars=[Bar('X','20240102',10,10.1,9.8,9.9,100),
              Bar('X','20240103',10,10.2,9.9,10.1,100)]
        small=dict(c=0,date='20240102',stop=9.8,confirmed_date='20240103')
        with self.assertRaises(ValueError):confirmed_trough_zone(bars[:1],small,'20240102',.02)
        zone=confirmed_trough_zone(bars,small,'20240103',.02)
        self.assertEqual((zone['support_lower'],zone['support_upper']),(9.8,9.9))
        # Appending unseen observations cannot alter an already fixed support.
        future=Bar('X','20240104',9,10,8,9,100)
        self.assertEqual(zone,confirmed_trough_zone(bars+[future],small,'20240103',.02))
        with self.assertRaises(ValueError):confirmed_trough_zone(bars,dict(small,stop=9.7),'20240103',.02)

    def test_two_percent_limit_and_net_rr_both_apply(self):
        risk=RiskManager(config()['risk'])
        intent=Intent('fixture','X','20240101',10,9.8,11,'id','daily_n_rhythm',evidence())
        def assess(fill,i=intent):return risk.assess(i,fill,1e6,1e6,{}, {},.0003,.0005,slippage=.001)
        self.assertGreater(assess(10)['quantity'],0)
        self.assertEqual(assess(10.001)['risk_reason'],'entry_too_far_from_support')
        self.assertEqual(assess(10,replace(intent,target=10.3))['risk_reason'],'net_rr_not_above_threshold')
        self.assertEqual(assess(10,replace(intent,evidence=dict(evidence(),support_lower=9.7)))['risk_reason'],'invalid_support_zone')

    def test_gap_is_checked_at_executable_price(self):
        e=self.engine()
        e.pending=[Intent('fixture','X','20240101',10,9.8,12,'id','daily_n_rhythm',evidence())]
        e.run([Bar('X','20240102',10.1,10.3,9.9,10.2,100)],['20240102'],set())
        self.assertFalse(e.positions)
        self.assertEqual(e.entry_audits[0]['execution_reason'],'entry_too_far_from_support')

    def test_entry_bar_touch_is_rejected_when_order_of_prices_is_unknown(self):
        e=self.engine()
        e.pending=[Intent('fixture','X','20240101',10,9.8,12,'id','daily_n_rhythm',evidence())]
        e.run([Bar('X','20240102',9.9,10.2,9.8,10.1,100)],['20240102'],set())
        self.assertFalse(e.positions)
        self.assertEqual(e.entry_audits[0]['execution_reason'],'ambiguous_or_invalidated_entry_bar')

    def test_intraday_touch_exits_despite_close_recovery(self):
        e=self.engine();self.position(e)
        e.run([Bar('X','20240102',10,10.2,9.7,10.1,100)],['20240102'],set())
        self.assertFalse(e.positions)
        self.assertEqual(e.trades[0]['reason'],'support_break')
        self.assertAlmostEqual(e.trades[0]['exit'],9.8*.999)

    def test_gap_below_support_fills_at_open_less_slippage(self):
        e=self.engine();self.position(e)
        e.run([Bar('X','20240102',9.5,9.6,9.3,9.4,100)],['20240102'],set())
        self.assertAlmostEqual(e.trades[0]['exit'],9.5*.999)

    def test_limit_down_breach_is_latched_even_if_next_day_recovers(self):
        e=self.engine();self.position(e)
        bars=[Bar('X','20240102',9.7,9.7,9.7,9.7,100,down_limit=9.7),
              Bar('X','20240103',10.1,10.2,10,10.1,100)]
        e.run(bars,[b.date for b in bars],set())
        self.assertEqual(e.trades[0]['exit_date'],'20240103')
        self.assertEqual(e.trades[0]['reason'],'deferred_support_break')
        self.assertAlmostEqual(e.trades[0]['exit'],10.1*.999)

    def test_same_day_sell_is_deferred_without_losing_breach(self):
        e=self.engine();p=self.position(e,'20240102')
        e.execute_interval({'X':Bar('X','20240102',10,10.2,9.7,10.1,100)},'20240102',None,e.cash)
        self.assertIn('X',e.positions)
        self.assertEqual(p.plan['t1_stop_breached_at'],'20240102')
        e.execute_interval({'X':Bar('X','20240103',10.1,10.2,10,10.1,100)},'20240103',None,e.cash)
        self.assertEqual(e.trades[0]['reason'],'deferred_support_break')

    def test_factor_adjustment_scales_support_for_positions_and_plans(self):
        e=self.engine();p=self.position(e)
        e.histories['X']=[Bar('X','20240101',10,10.1,9.9,10,100)]
        e.pending=[Intent('fixture','X','20240101',10,9.8,12,'id2','daily_n_rhythm',evidence())]
        e.adjust_factors({'X':Bar('X','20240102',5,5.1,4.9,5,100,factor=2)},'20240102')
        for plan in (p.plan,e.pending[0].evidence):
            self.assertAlmostEqual(plan['support_lower'],4.9)
            self.assertAlmostEqual(plan['support_upper'],4.95)
        self.assertAlmostEqual(p.stop,4.9)
        self.assertAlmostEqual(e.pending[0].stop,4.9)

    def test_configuration_rejects_hidden_buffer_and_unsupported_hourly_zone(self):
        c=config();build_strategies(c['strategies'])
        for key,value in (('stop_buffer',.005),('lower_cycle','hourly'),('support_max_entry_risk',0)):
            changed=config();changed['strategies'][0]['params'][key]=value
            with self.assertRaises(ValueError):build_strategies(changed['strategies'])

    def test_new_support_is_promoted_only_after_confirmed_higher_correction(self):
        from test_live_leg_protection import LiveLegTests
        s,p,bars=LiveLegTests().fixture()
        s.p['stop_buffer']=0
        p.plan.update(support_mode='confirmed_trough',support_lower=p.stop,support_upper=p.stop+.1)
        s.manage_position(bars[:9],p)
        self.assertEqual(p.plan['support_lower'],9)
        s.manage_position(bars[:10],p)
        self.assertGreater(p.stop,12)
        self.assertEqual(p.plan['support_lower'],p.stop)
        self.assertEqual(p.plan['support_known_at'],bars[9].date)
        candle=next(b for b in bars if b.date==p.plan['support_source_date'])
        self.assertEqual(p.plan['support_upper'],min(candle.open,candle.close))


if __name__=='__main__':unittest.main()
