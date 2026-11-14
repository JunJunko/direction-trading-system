import sys
import unittest
from dataclasses import replace
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from plan_hit_rate import evaluate,barrier_hit,summarize
from trading_system.domain import Bar


class PlanHitRateTests(unittest.TestCase):
    def fixture(self,history,observations=None,end='20240105'):
        p=dict(setup_id='id',symbol='X',date='20240101',trigger=10,stop=9,target=12,evidence=dict(factor=1))
        obs=observations if observations is not None else [dict(setup_id='id',date='20240101',trigger=10,stop=9,target=12)]
        first=Bar('X','20240101',9.8,10,9.5,9.9,100)
        return evaluate(p,obs,[first]+history,['20240101','20240102','20240103','20240104','20240105'],dict(slippage=.001),end=end)

    def test_open_orders_barriers_and_intrabar_double_touch_is_unknown(self):
        b=Bar('X','20240103',10,13,8,11,100)
        self.assertEqual(barrier_hit(b,9,12),'ambiguous_exit_bar')
        self.assertEqual(barrier_hit(replace(b,open=12.2),9,12),'target_first')
        self.assertEqual(barrier_hit(replace(b,open=8.8),9,12),'stop_first')

    def test_untriggered_plan_cannot_use_later_unapproved_date(self):
        bars=[Bar('X','20240102',9.7,9.9,9.5,9.8,100),Bar('X','20240103',10,13,9.5,12,100)]
        self.assertEqual(self.fixture(bars)['status'],'not_triggered')

    def test_recorded_renewal_makes_the_next_day_executable(self):
        bars=[Bar('X','20240102',9.7,9.9,9.5,9.8,100),Bar('X','20240103',10,13,9.5,12,100)]
        obs=[dict(setup_id='id',date=d,trigger=10,stop=9,target=12) for d in ('20240101','20240102')]
        r=self.fixture(bars,obs)
        self.assertEqual(r['status'],'target_first');self.assertTrue(r['hit_on_entry_day'])

    def test_entry_bar_stop_and_trigger_is_ambiguous_not_a_win(self):
        r=self.fixture([Bar('X','20240102',10,13,8,12,100)])
        self.assertEqual(r['status'],'ambiguous_entry_bar');self.assertFalse(r['entry_date'])

    def test_factor_changes_preserve_fixed_price_barrier_results(self):
        bars=[Bar('X','20240102',10,10.5,9.5,10.2,100),Bar('X','20240103',11,12.5,10.5,12.2,100)]
        split=[bars[0],replace(bars[1],open=5.5,high=6.25,low=5.25,close=6.1,factor=2)]
        self.assertEqual(self.fixture(bars),self.fixture(split))

    def test_unresolved_and_ambiguous_are_not_counted_as_losses(self):
        bars=[Bar('X','20240102',10,10.5,9.5,10.2,100),Bar('X','20240103',10.2,11,9.5,10.8,100)]
        r=self.fixture(bars);self.assertEqual(r['status'],'unresolved_at_sample_end')
        s=summarize([r]);self.assertIsNone(s['target_first_rate'])

    def test_sample_end_and_suspension_cannot_create_a_future_hit(self):
        bars=[Bar('X','20240102',10,10.5,9.5,10.2,100),Bar('X','20240103',13,13,13,13,0),
              Bar('X','20240104',12,13,11,12.5,100)]
        self.assertEqual(self.fixture(bars,end='20240103')['status'],'unresolved_at_sample_end')


if __name__=='__main__':unittest.main()
