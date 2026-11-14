import sys
import unittest
from pathlib import Path
from dataclasses import replace

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from report_plan_reward_risk import net_values,required_stop,closer_daily_supports
from trading_system.domain import Bar


EX=dict(slippage=.001,commission_rate=.0003,minimum_commission=5,
        sell_tax_after_20230828=.0005,sell_tax_before_20230828=.001)


class PlanRewardRiskTests(unittest.TestCase):
    def test_net_costs_reduce_ratio_and_tighter_stop_increases_it(self):
        base=net_values(10,9,14,1000,'20250101',EX)['net_rr']
        self.assertLess(base,4)
        self.assertGreater(net_values(10,9.5,14,1000,'20250101',EX)['net_rr'],base)

    def test_fee_aware_stop_boundary_and_strict_threshold(self):
        stop=required_stop(10,11,1000,'20250101',EX)
        self.assertGreater(stop,10-1/3)
        self.assertAlmostEqual(net_values(10,stop,11,1000,'20250101',EX)['net_rr'],3)
        self.assertLess(net_values(10,stop-.01,11,1000,'20250101',EX)['net_rr'],3)

    def test_cost_floor_makes_some_targets_impossible_even_at_entry_stop(self):
        self.assertIsNone(required_stop(10,10.01,1000,'20250101',EX))

    def test_unconfirmed_low_and_future_factor_cannot_create_past_support(self):
        bars=[Bar('X',f'2025010{i+1}',c,c+.1,c-.1,c,100) for i,c in enumerate([10,11,10.5,11,12])]
        self.assertEqual(closer_daily_supports(bars,'20250103','20250101',9,12),[])
        known=closer_daily_supports(bars,'20250104','20250101',9,12)
        self.assertEqual(len(known),1)
        self.assertEqual(known[0]['known_at'],'20250104')
        future=replace(bars[-1],date='20250106',factor=100,low=.01)
        self.assertEqual(closer_daily_supports(bars+[future],'20250104','20250101',9,12),known)

    def test_touched_support_is_not_an_intact_tighter_candidate(self):
        bars=[Bar('X',f'2025010{i+1}',c,c+.1,c-.1,c,100) for i,c in enumerate([10,11,10.5,11,12])]
        bars.append(Bar('X','20250106',11,11.1,10.4,10.6,100))
        self.assertEqual(closer_daily_supports(bars,'20250106','20250101',9,12),[])


if __name__=='__main__':unittest.main()
