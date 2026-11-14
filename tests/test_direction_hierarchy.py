"""Schematic-derived cases, not digitized historical prices or profitability tests."""
import unittest
from dataclasses import replace
from test_direction_system import reversal_data, core_data
from trading_system.structure import hierarchy_double_bottom, retest_confirmation, n_structure, rhythm
from trading_system.strategies.direction_double_bottom import DirectionDoubleBottom


class HierarchyTests(unittest.TestCase):
    def test_direction_confirmation_uses_only_completed_prefix(self):
        bars,ends=reversal_data()
        strategy=DirectionDoubleBottom('v5_2',dict(lower_cycle='daily_nested',structure_mode='hierarchy'))
        events=[]
        for i in range(len(bars)):
            _,found=strategy.on_close(bars[:i+1],ends)
            events.extend(found)
            if i<42:
                self.assertNotEqual(strategy.states['X']['direction'],'long')
        confirmed=[x for x in events if x['event']=='upper_direction_confirmed']
        self.assertEqual(len(confirmed),1)
        self.assertEqual(confirmed[0]['date'],bars[42].date)

    def test_enclosing_w_and_first_breakout_only(self):
        bars,_=reversal_data()
        candidate,reason=hierarchy_double_bottom(bars[:39])
        self.assertIsNotNone(candidate,reason)
        self.assertEqual((candidate['first'],candidate['second']),(29,35))
        self.assertIsNone(hierarchy_double_bottom(bars[:40])[0])
        # Volume is not a mandatory definition of the reversal itself.
        self.assertIsNotNone(hierarchy_double_bottom([replace(x,volume=100) for x in bars[:39]])[0])

    def test_horizontal_retest_below_first_upper_wick(self):
        bars,_=reversal_data()
        bars[39]=replace(bars[39],high=14)
        bars[-2]=replace(bars[-2],high=13.1)
        bars[-1]=replace(bars[-1],open=12.65,close=12.8,high=12.9,low=12.7)
        pending=dict(second=35,bottom=10.05,neckline=12.35,retest_start=39)
        result=retest_confirmation(bars,pending)
        self.assertEqual(result['kind'],'horizontal')
        self.assertLess(bars[-1].close,bars[39].high)
        self.assertIsNone(retest_confirmation(bars[:-1],pending))
        falling=bars[:-1]+[replace(bars[-1],close=12.5,low=12.4)]
        self.assertIsNone(retest_confirmation(falling,pending))

    def test_enclosing_w_ignores_minor_internal_trough(self):
        bars,_=reversal_data()
        # Insert a small confirmed zigzag in the right leg. The enclosing bottom
        # remains the original right trough, despite a more recent local low.
        base=bars[:38]
        extra=[replace(bars[38],date=f'2025{i:04d}',open=v-.03,high=v+.05,low=v-.05,close=v)
               for i,v in enumerate([12.1,11.8,11.5,11.8,12.1,13],1)]
        candidate,reason=hierarchy_double_bottom(base+extra)
        self.assertIsNotNone(candidate,reason)
        self.assertEqual(candidate['second'],35)

    def test_plan_precedes_breakout_and_keeps_small_trigger(self):
        bars=core_data()[:19]
        bars[-1]=replace(bars[-1],open=12.9,low=12.9,close=12.95)
        core,_=n_structure(bars)
        small,reason=rhythm(bars,core,planned=True)
        self.assertIsNotNone(small,reason)
        self.assertGreater(small['trigger'],bars[-1].close)
        self.assertIsNone(rhythm(bars,core)[0])
        broken=bars[:-1]+[replace(bars[-1],low=small['stop']-.1)]
        self.assertIsNone(rhythm(broken,core,planned=True)[0])


if __name__=='__main__':unittest.main()
