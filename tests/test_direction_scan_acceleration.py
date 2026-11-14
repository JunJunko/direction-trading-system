import random
import sys
import unittest
from dataclasses import replace
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.analysis import adjusted
from trading_system.domain import Bar
from trading_system.structure import SwingCache,hierarchy_double_bottom_candidates
from trading_system.structure import swings
from trading_system.strategies.direction_double_bottom import DirectionDoubleBottom
from fixtures.double_bottom_candidates_reference import hierarchy_double_bottom_candidates as reference
from test_direction_system import reversal_data


class DirectionScanAccelerationTests(unittest.TestCase):
    def test_cached_pruned_scan_matches_frozen_reference_on_every_prefix(self):
        for left,right in ((1,1),(2,2),(3,2)):
            rng=random.Random(20261022)
            cache=SwingCache(left,right);bars=[];price=10
            for i in range(130):
                price=max(2,price+rng.choice((-.7,-.2,0,.2,.7)))
                # Repeated prices and outside bars exercise ambiguous/flat pivots.
                width=rng.choice((.1,.1,.7,1.2))
                factor=1 if i<45 else 2 if i<100 else 3
                bars.append(Bar('X',f'{i:08d}',price,price+width,price-width,price,100,factor))
                observed=adjusted(bars);points=cache.get(observed)
                for delayed in (False,True):
                    self.assertEqual(
                        hierarchy_double_bottom_candidates(observed,left,right,allow_delayed=delayed,points=points),
                        reference(observed,left,right,allow_delayed=delayed))
            # A shortened history forces the same cache to rebuild.
            observed=adjusted(bars[:70])
            self.assertEqual(hierarchy_double_bottom_candidates(observed,left,right,allow_delayed=True,points=cache.get(observed)),
                             reference(observed,left,right,allow_delayed=True))

    def test_newly_confirmed_trough_keeps_delayed_neck_retest_candidate(self):
        bars,_=reversal_data()
        bars[36]=replace(bars[36],close=13,high=13.2)
        bars[37]=replace(bars[37],close=12.1,high=12.25,low=11.8)
        cache=SwingCache()
        for end in range(1,40):
            observed=bars[:end]
            actual=hierarchy_double_bottom_candidates(observed,allow_delayed=True,points=cache.get(observed))
            self.assertEqual(actual,reference(observed,allow_delayed=True))
            if end==38:self.assertTrue(actual[0])

    def test_weekly_suspended_close_rescales_cached_swings_on_factor_change(self):
        bars,ends=reversal_data();bars=bars[:20]
        last=datetime.strptime(bars[-1].date,'%Y%m%d')
        thursday=(last+timedelta(days=6)).strftime('%Y%m%d')
        monday=(last+timedelta(days=10)).strftime('%Y%m%d')
        bars.append(replace(bars[-1],date=thursday))
        bars.append(replace(bars[-1],date=monday,factor=2))
        s=DirectionDoubleBottom('weekly',dict(candidate_mode='pool',structure_mode='hierarchy',retest_mode='boundary'))
        observed=[]
        def candidates(weeks,left,right,*args,**kwargs):
            observed.append((list(kwargs['points']),swings(weeks,left,right)))
            return [],'no_enclosing_w_breakout'
        with patch('trading_system.strategies.direction_double_bottom.hierarchy_double_bottom_candidates',side_effect=candidates):
            for end in range(1,len(bars)+1):s.on_close(bars[:end],ends)
        self.assertTrue(observed[-1][1])
        self.assertEqual(observed[-1][0],observed[-1][1])


if __name__=='__main__':unittest.main()
