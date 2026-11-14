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
from trading_system.risk import RiskManager
from trading_system.strategies import build_strategies
from trading_system.support import support_band_retest
from test_support_zone import Fixture
import test_support_rebound as rebound_fixtures


def config():
    return json.loads((ROOT/'configs/experiments/double_bottom_v5_15_support_band_structure.json').read_text(encoding='utf-8'))


def example():
    bars=[Bar('X',f'202501{i+1:02}',10.3,10.4,10.2,10.3,100) for i in range(14)]
    bars.extend([Bar('X','20250115',10,10.15,9.5,10.02,100),
                 Bar('X','20250116',10.02,10.08,10.01,10.04,100),
                 Bar('X','20250117',10.01,10.07,9.99,10.05,100)])
    small=dict(c=14,date='20250115',stop=9.5,confirmed_date='20250116')
    return bars,small


def signal():
    bars,small=example();e,reason=support_band_retest(bars,small,.01)
    assert e,reason
    e['breakout_reference']=10.5
    return Intent('fixture','X','20250117',10.05,e['support_defense_lower'],11,'id','daily_n_rhythm',e)


class SupportBandTests(unittest.TestCase):
    def test_band_is_inside_support_and_uses_a_later_confirmed_retest(self):
        bars,small=example();e,reason=support_band_retest(bars,small,.01)
        self.assertIsNotNone(e,reason)
        self.assertLess(e['support_lower'],e['support_defense_lower'])
        self.assertLess(e['support_defense_lower'],e['support_defense_upper'])
        self.assertEqual(e['support_defense_upper'],e['support_upper'])
        self.assertLessEqual(e['support_defense_width_pct'],.005)
        self.assertLess(e['support_band_known_at'],e['support_retest_date'])
        self.assertEqual(e['support_stand_date'],'20250116')

    def test_support_confirmation_day_cannot_also_be_later_retest(self):
        bars,small=example()
        self.assertEqual(support_band_retest(bars[:-1],small,.01)[1],'waiting_after_support_confirmation')

    def test_frozen_band_does_not_expand_with_confirmation_day_volatility(self):
        bars,small=example();e,_=support_band_retest(bars,small,.01)
        volatile=bars[:-1]+[replace(bars[-1],high=20)]
        changed,_=support_band_retest(volatile,small,.01)
        self.assertEqual(e['support_reference_atr'],changed['support_reference_atr'])
        self.assertEqual(e['support_defense_lower'],changed['support_defense_lower'])

    def test_retest_cannot_be_invented_without_prior_hold_or_touch(self):
        bars,small=example()
        no_stand=bars[:-2]+[replace(bars[-2],low=9.99),bars[-1]]
        self.assertEqual(support_band_retest(no_stand,small,.01)[1],'upper_edge_not_previously_held')
        no_touch=bars[:-1]+[replace(bars[-1],low=10.01)]
        self.assertEqual(support_band_retest(no_touch,small,.01)[1],'no_upper_edge_retest')

    def test_recovered_close_does_not_erase_band_breach(self):
        bars,small=example();e,_=support_band_retest(bars,small,.01)
        failed=bars[:-1]+[replace(bars[-1],low=e['support_defense_lower'])]
        self.assertEqual(support_band_retest(failed,small,.01)[1],'defense_band_breached_during_confirmation')

    def test_width_limit_rejects_without_arbitrary_clipping(self):
        bars,small=example()
        self.assertEqual(support_band_retest(bars,small,.01,max_width=.0001)[1],'support_defense_band_not_narrow')

    def test_risk_uses_narrow_stop_and_keeps_original_floor_as_context(self):
        i=signal();c=config()
        r=RiskManager(c['risk']).assess(i,10.05*1.001,1e6,1e6,{}, {},.0003,.0005,slippage=.001)
        self.assertGreater(r['quantity'],0)
        self.assertLessEqual(r['support_entry_distance'],.01)
        self.assertGreater(r['support_structural_distance'],.05)
        gap=RiskManager(c['risk']).assess(i,10.2,1e6,1e6,{}, {},.0003,.0005,slippage=.001)
        self.assertEqual(gap['risk_reason'],'entry_too_far_from_support')

    def test_fake_stop_inside_no_valid_band_is_rejected(self):
        i=signal();c=config()
        bad=replace(i,evidence=dict(i.evidence,support_defense_lower=9.4))
        r=RiskManager(c['risk']).assess(bad,10.06,1e6,1e6,{}, {},.0003,.0005,slippage=.001)
        self.assertEqual(r['risk_reason'],'invalid_support_defense_band')

    def test_band_must_have_separate_known_stand_and_retest_dates(self):
        i=signal();c=config()
        bad=replace(i,evidence=dict(i.evidence,support_stand_date=i.date))
        r=RiskManager(c['risk']).assess(bad,10.06,1e6,1e6,{}, {},.0003,.0005,slippage=.001)
        self.assertEqual(r['risk_reason'],'invalid_support_defense_confirmation')

    def test_band_breach_sells_even_while_original_support_is_intact(self):
        e=Backtest(config(),[Fixture()]);e.pending=[signal()]
        bars=[Bar('X','20250120',10.04,10.1,10.02,10.08,100),
              Bar('X','20250121',10.03,10.04,9.95,9.98,100)]
        e.run(bars,[b.date for b in bars],set())
        self.assertEqual(e.summary()['filled_buys'],1)
        self.assertEqual(len(e.trades),1)
        self.assertEqual(e.trades[0]['reason'],'support_band_break')
        self.assertGreater(bars[-1].low,9.5)

    def test_same_day_band_breach_latches_without_deleting_open_fill(self):
        e=Backtest(config(),[Fixture()]);e.pending=[signal()]
        bars=[Bar('X','20250120',10.04,10.1,9.95,10.05,100),
              Bar('X','20250121',10.06,10.1,10,10.05,100)]
        e.run(bars,[b.date for b in bars],set())
        self.assertEqual(e.trades[0]['entry_date'],'20250120')
        self.assertEqual(e.trades[0]['exit_date'],'20250121')
        self.assertEqual(e.trades[0]['reason'],'deferred_support_band_break')

    def test_factor_adjustment_scales_all_defense_prices_together(self):
        e=Backtest(config(),[Fixture()]);i=signal();e.pending=[i]
        e.histories['X']=[Bar('X','20250117',10.01,10.07,9.99,10.05,100)]
        e.marks['X']=10.05
        e.adjust_factors({'X':Bar('X','20250120',5.02,5.05,5.01,5.04,100,factor=2)},'20250120')
        new=e.pending[0]
        self.assertAlmostEqual(new.stop,i.stop/2)
        for key in ('support_defense_lower','support_defense_upper','support_reference_atr'):
            self.assertAlmostEqual(new.evidence[key],i.evidence[key]/2)

    def test_strategy_uses_defense_line_in_intent_and_preserves_core_target(self):
        _,bars,core=rebound_fixtures.SupportReboundTests().fixture()
        bars[-1]=replace(bars[-1],open=12.80,high=12.9,low=12.79,close=12.82)
        bars.append(Bar('X','20240126',12.8,12.87,12.77,12.84,100))
        s=build_strategies(config()['strategies'])[0]
        s.states['X']=dict(direction='long',processed=bars[-1].date,pending=None,factor=1,floor=9,
            confirmed_date=bars[0].date,direction_source=dict(second_date=bars[2].date,candidate_id='upper'))
        with patch('trading_system.strategies.direction_double_bottom.WaveHierarchy.get',return_value=(core,'qualified',[])):
            plans,_=s.on_close(bars,set())
        self.assertEqual(len(plans),1)
        i=plans[0]
        self.assertEqual(i.stop,i.evidence['support_defense_lower'])
        self.assertEqual(i.evidence['entry_mode'],'support_band_retest')
        self.assertEqual(i.target,core['target'])

    def test_invalid_band_parameters_fail_closed(self):
        for key,value in (('support_band_atr_lookback',0),('support_band_atr_fraction',0),('support_band_max_width',float('nan'))):
            c=config();c['strategies'][0]['params'][key]=value
            with self.assertRaises(ValueError):build_strategies(c['strategies'])


if __name__=='__main__':unittest.main()
