import unittest
from dataclasses import replace
import test_autonomous_system as fixtures
from trading_system.strategies.autonomous_double_bottom import AutonomousDoubleBottom


class LiveLegTests(unittest.TestCase):
    def fixture(self):
        _,p,bars=fixtures.AutonomousTests().fixture()
        p.plan['small_c']=bars[0].date
        s=AutonomousDoubleBottom('auto',dict(lower_cycle='daily_nested',protection_mode='live_leg'))
        s.states['X']=dict(direction='long')
        return s,p,bars

    def test_confirmed_trough_protects_before_new_high(self):
        s,p,bars=self.fixture()
        for i in range(1,10):
            exits,events=s.manage_position(bars[:i+1],p)
            self.assertFalse(exits)
            if i<9:self.assertEqual(p.stop,9)
        self.assertLess(bars[9].close,bars[4].high)
        self.assertGreater(p.stop,12)
        self.assertTrue(events[0]['recovery_below_peak'])
        self.assertEqual(events[0]['confirmed_at'],bars[9].date)

    def test_old_entry_duration_does_not_block_live_correction(self):
        s,p,bars=self.fixture();p.plan['correction_duration']=30
        exits,events=s.manage_position(bars[:10],p)
        self.assertFalse(exits);self.assertGreater(p.stop,12)
        self.assertEqual(p.plan['live_reference_duration'],3)

    def test_future_bar_cannot_confirm_earlier_trough(self):
        s,p,bars=self.fixture()
        s.manage_position(bars[:9],p)
        self.assertEqual(p.stop,9)
        s.manage_position(bars[:10],p)
        self.assertGreater(p.stop,9)

    def test_broken_trough_cannot_promote(self):
        s,p,bars=self.fixture()
        bars[9]=replace(bars[9],low=12.8)
        s.manage_position(bars[:10],p)
        self.assertEqual(p.stop,9)

    def test_hourly_timestamp_maps_to_known_daily_anchor(self):
        s,p,bars=self.fixture();p.plan['small_c']+='140000'
        exits,_=s.manage_position(bars[:10],p)
        self.assertFalse(exits);self.assertGreater(p.stop,9)

    def test_protection_is_monotonic_and_missing_anchor_exits(self):
        s,p,bars=self.fixture();p.stop=13.5
        s.manage_position(bars[:10],p);self.assertEqual(p.stop,13.5)
        s,p,bars=self.fixture();p.plan['small_c']='19990101'
        self.assertEqual(s.manage_position(bars,p)[0][0].reason,'missing_live_anchor')

if __name__=='__main__':unittest.main()
