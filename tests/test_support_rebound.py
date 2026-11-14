import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src')]
from trading_system.domain import Bar,Intent
from trading_system.engine import Backtest
from trading_system.strategies import build_strategies
from trading_system.structure import n_structure,rhythm
from trading_system.support import support_rebound
from test_direction_system import core_data
from test_support_zone import Fixture,evidence


def config():
    return json.loads((ROOT/'configs/experiments/double_bottom_v5_14_support_rebound_structure.json').read_text(encoding='utf-8'))


def intent(date='20240101'):
    e=dict(evidence(),entry_mode='support_rebound',entry_order='next_open',
           rebound_confirmed_at=date,rebound_signal_close=9.95,breakout_reference=10.3)
    return Intent('fixture','X',date,9.95,9.8,11,'id','daily_n_rhythm',e)


class SupportReboundTests(unittest.TestCase):
    def engine(self):return Backtest(config(),[Fixture()])

    def fixture(self,mode='support_rebound'):
        bars=core_data()[:19]
        bars[-1]=replace(bars[-1],open=12.9,high=13,low=12.84,close=12.94)
        core,reason=n_structure(bars,ownership=True)
        self.assertIsNotNone(core,reason)
        c=config();c['strategies'][0]['params']['entry_mode']=mode
        s=build_strategies(c['strategies'])[0]
        s.states['X']=dict(direction='long',processed=bars[-1].date,pending=None,
            factor=1,floor=9,confirmed_date=bars[0].date,
            direction_source=dict(second_date=bars[2].date,candidate_id='upper'))
        return s,bars,core

    def test_signal_before_prior_swing_high_breakout_with_known_support(self):
        s,bars,core=self.fixture()
        with patch('trading_system.strategies.direction_double_bottom.WaveHierarchy.get',return_value=(core,'qualified',[])):
            plans,_=s.on_close(bars,set())
        self.assertEqual(len(plans),1)
        p=plans[0];self.assertEqual(p.trigger,bars[-1].close)
        self.assertLess(p.trigger,p.evidence['breakout_reference'])
        self.assertLessEqual(p.evidence['small_confirmed'],p.date)
        self.assertEqual(p.evidence['entry_order'],'next_open')
        self.assertFalse(s.opportunities)  # One next-session order, no five-day retry.
        old,_,_=self.fixture('breakout')
        with patch('trading_system.strategies.direction_double_bottom.WaveHierarchy.get',return_value=(core,'qualified',[])):
            old_plans,_=old.on_close(bars,set())
        self.assertEqual(len(old_plans),1)
        self.assertGreater(old_plans[0].trigger,p.trigger)

    def test_close_confirmation_cannot_use_unconfirmed_trough(self):
        _,bars,core=self.fixture()
        small,_=rhythm(bars,core,planned=True,ownership=True)
        with self.assertRaises(ValueError):support_rebound(bars[:-1],small,.02)
        signal,reason=support_rebound(bars,small,.02)
        self.assertIsNotNone(signal,reason)
        future=replace(bars[-1],date='20240126',low=10,close=10.1,open=10,high=10.3)
        # The old signal is immutable; later loss of support cannot erase it.
        again,_=support_rebound((bars+[future])[:len(bars)],small,.02)
        self.assertEqual(signal,again)

    def test_red_or_falling_close_is_not_confirmation(self):
        _,bars,core=self.fixture();small,_=rhythm(bars,core,planned=True,ownership=True)
        red=bars[:-1]+[replace(bars[-1],open=12.96)]
        self.assertEqual(support_rebound(red,small,.02)[1],'bullish_recovery_not_confirmed')
        falling=bars[:-1]+[replace(bars[-1],open=12.76,low=12.76,close=12.79)]
        self.assertEqual(support_rebound(falling,small,.02)[1],'bullish_recovery_not_confirmed')

    def test_support_touch_or_distant_confirmation_does_not_plan(self):
        _,bars,core=self.fixture();small,_=rhythm(bars,core,planned=True,ownership=True)
        touched=bars[:-1]+[replace(bars[-1],low=small['stop'])]
        self.assertEqual(support_rebound(touched,small,.02)[1],'support_already_touched')
        far=bars[:-1]+[replace(bars[-1],high=13.4,close=13.3)]
        self.assertEqual(support_rebound(far,small,.02)[1],'confirmation_too_far_from_support')

    def test_next_open_buys_below_signal_close_without_old_breakout(self):
        e=self.engine();e.pending=[intent()]
        bar=Bar('X','20240102',9.9,9.94,9.85,9.92,100)
        e.run([bar],[bar.date],set())
        self.assertEqual(e.summary()['filled_buys'],1)
        self.assertAlmostEqual(e.positions['X'].entry,9.9*1.001)
        self.assertLess(bar.high,intent().trigger)
        self.assertFalse(e.entry_audits[0]['trigger_reached'])
        self.assertEqual(e.entry_audits[0]['entry_order'],'next_open')

    def test_open_gap_above_two_percent_is_rejected(self):
        e=self.engine();e.pending=[intent()]
        bar=Bar('X','20240102',10.1,10.2,9.9,10,100)
        e.run([bar],[bar.date],set())
        self.assertFalse(e.positions)
        self.assertEqual(e.entry_audits[0]['execution_reason'],'entry_too_far_from_support')

    def test_open_below_support_does_not_buy_even_if_close_recovers(self):
        e=self.engine();e.pending=[intent()]
        bar=Bar('X','20240102',9.7,10,9.6,9.95,100)
        e.run([bar],[bar.date],set())
        self.assertFalse(e.positions)
        self.assertEqual(e.entry_audits[0]['execution_reason'],'support_invalidated_at_open')

    def test_same_day_later_break_keeps_losing_open_fill_and_exits_next_day(self):
        e=self.engine();e.pending=[intent()]
        bars=[Bar('X','20240102',9.9,10,9.7,9.75,100),
              Bar('X','20240103',9.6,9.8,9.5,9.7,100)]
        e.run(bars,[b.date for b in bars],set())
        self.assertEqual(e.summary()['filled_buys'],1)
        self.assertEqual(len(e.trades),1)
        self.assertEqual(e.trades[0]['entry_date'],'20240102')
        self.assertEqual(e.trades[0]['exit_date'],'20240103')
        self.assertEqual(e.trades[0]['reason'],'deferred_support_break')
        self.assertLess(e.trades[0]['pnl'],0)

    def test_same_day_or_hourly_execution_is_not_allowed(self):
        for window in (None,dict(bar_end='20240102103000',window_start='20240102093000')):
            e=self.engine();e.pending=[intent('20240102')]
            with self.assertRaisesRegex(ValueError,'completed daily signal'):
                e.execute_interval({},'20240102',None,e.cash,window)

    def test_suspended_next_session_expires_without_chasing_later(self):
        e=self.engine();e.pending=[intent()]
        bars=[Bar('X','20240102',9.9,9.9,9.9,9.9,0),
              Bar('X','20240103',9.9,10,9.85,9.95,100)]
        e.run(bars,[b.date for b in bars],set())
        self.assertFalse(e.positions)
        self.assertEqual(len(e.orders),1)
        self.assertEqual(e.orders[0]['reason'],'expired_suspended')

    def test_factor_adjustment_keeps_signal_prices_comparable(self):
        e=self.engine();e.pending=[intent()]
        e.histories['X']=[Bar('X','20240101',9.9,10,9.85,9.95,100)]
        e.marks['X']=9.95
        bar=Bar('X','20240102',4.95,5,4.925,4.97,100,factor=2)
        e.adjust_factors({'X':bar},bar.date)
        self.assertAlmostEqual(e.pending[0].evidence['rebound_signal_close'],9.95/2)
        self.assertAlmostEqual(e.pending[0].evidence['breakout_reference'],10.3/2)
        self.assertAlmostEqual(e.pending[0].stop,9.8/2)

    def test_bad_mode_and_missing_support_are_rejected(self):
        for params in ({'entry_mode':'unknown'}, {'entry_mode':'support_rebound','support_mode':'none'}):
            c=config();c['strategies'][0]['params'].update(params)
            with self.assertRaises(ValueError):build_strategies(c['strategies'])


if __name__=='__main__':unittest.main()
