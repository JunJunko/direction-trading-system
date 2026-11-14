import unittest
from dataclasses import replace
from test_direction_system import core_data
from trading_system.domain import Position
from trading_system.structure import active_correction,correction_measure
from trading_system.strategies.direction_double_bottom import DirectionDoubleBottom


class ProfitHoldingTests(unittest.TestCase):
    def test_future_high_cannot_reset_an_earlier_adjustment(self):
        bars=core_data()
        earlier=active_correction(bars[:-1],bars[0].date)
        self.assertIsNotNone(earlier)
        bars[-1]=replace(bars[-1],high=15,close=14.8)
        self.assertEqual(active_correction(bars[:-1],bars[0].date),earlier)
        self.assertIsNone(active_correction(bars,bars[0].date))

    def test_new_unconfirmed_high_ends_old_correction(self):
        bars=core_data()
        bars[-1]=replace(bars[-1],high=15,close=14.8)
        self.assertIsNone(active_correction(bars,bars[0].date))
        strategy=DirectionDoubleBottom('new',dict(exit_mode='active_correction'))
        strategy.states['X']=dict(direction='long')
        p=Position('new','X',bars[0].date,10,100,9,100,5,'id',1,
                   dict(correction_area=.1,correction_duration=1,correction_range=.1))
        self.assertFalse(strategy.manage_position(bars,p)[0])

    def test_adjustment_clock_restarts_after_new_high(self):
        bars=core_data()
        bars[-2]=replace(bars[-2],high=15,low=13,close=14.8)
        bars[-1]=replace(bars[-1],high=14.9,low=14,close=14.5)
        measured=active_correction(bars,bars[0].date)
        self.assertEqual(measured['peak'],len(bars)-2)
        self.assertEqual(measured['duration'],1)
        self.assertEqual(measured['range'],1)

    def test_invalid_reference_cannot_force_an_exit(self):
        current=dict(duration=2,area=6.93,range=2.31)
        plan=dict(correction_duration=8,correction_area=26.82,correction_range=-.3)
        self.assertFalse(DirectionDoubleBottom.correction_expanded(current,plan))

    def test_valid_expansion_still_exits(self):
        plan=dict(correction_duration=3,correction_area=4,correction_range=2)
        self.assertTrue(DirectionDoubleBottom.correction_expanded(dict(duration=4,area=5,range=1),plan))
        self.assertTrue(DirectionDoubleBottom.correction_expanded(dict(duration=1,area=3,range=3),plan))
        self.assertFalse(DirectionDoubleBottom.correction_expanded(None,plan))

    def test_peak_bar_low_is_not_assumed_to_follow_its_high(self):
        bars=core_data()[:2]
        bars[0]=replace(bars[0],high=15,low=8)
        bars[1]=replace(bars[1],high=14,low=13)
        self.assertEqual(correction_measure(bars,0,1)['range'],2)
        self.assertIsNone(correction_measure(bars,1,1))

    def test_reference_update_cannot_be_negative(self):
        bars=core_data()
        strategy=DirectionDoubleBottom('new',dict(exit_mode='active_correction'))
        strategy.states['X']=dict(direction='long')
        p=Position('new','X',bars[0].date,10,100,9,100,5,'id',1,
                   dict(correction_area=100,correction_duration=100,correction_range=100))
        for i in range(1,len(bars)):
            strategy.manage_position(bars[:i+1],p)
            self.assertGreater(p.plan['correction_range'],0)
            self.assertGreaterEqual(strategy.trailing_stop(bars[:i+1],p),p.stop)


if __name__=='__main__':unittest.main()
