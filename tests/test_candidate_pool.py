import sys,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.structure import Swing,hierarchy_double_bottom,hierarchy_double_bottom_candidates
from trading_system.strategies.direction_double_bottom import DirectionDoubleBottom
from test_direction_system import reversal_data


class EnumerationTests(unittest.TestCase):
    def test_breakout_before_right_pivot_confirmation_is_observed_once_later(self):
        bars,_=reversal_data()
        bars[36]=replace(bars[36],close=13,high=13.2)
        bars[37]=replace(bars[37],close=12.9,high=13.1,low=12.7)
        self.assertFalse(hierarchy_double_bottom_candidates(bars[:37],allow_delayed=True)[0])
        self.assertIsNone(hierarchy_double_bottom(bars[:38])[0])
        candidates,_=hierarchy_double_bottom_candidates(bars[:38],allow_delayed=True)
        self.assertTrue(candidates)
        c=candidates[0]
        self.assertEqual((c['first_breakout_index'],c['first_observable_index']),(36,37))
        later,_=hierarchy_double_bottom_candidates(bars[:39],allow_delayed=True)
        self.assertFalse(any(x['first']==c['first'] and x['second']==c['second'] for x in later))

    def test_all_valid_pairs_are_returned_before_area_selection(self):
        bars=[Bar('X',str(i),12,14,11,12,100) for i in range(13)]
        for i,high,low,close in [(0,20,19,19),(2,12,10,11),(3,18,11,17),
                                 (4,12,10,11),(6,15,12,14),(10,12,10,11),(12,20,12,19)]:
            bars[i]=replace(bars[i],high=high,low=low,close=close)
        points=[Swing('high',0,2,20),Swing('low',2,4,10),Swing('high',3,5,18),
                Swing('low',4,6,10),Swing('high',6,8,15),Swing('low',10,12,10)]
        with patch('trading_system.structure.swings',return_value=points):
            candidates,_=hierarchy_double_bottom_candidates(bars)
            chosen,_=hierarchy_double_bottom(bars)
        self.assertEqual({(c['first'],c['second']) for c in candidates},{(2,4),(2,10),(4,10)})
        self.assertEqual(chosen['first'],2)

    def test_delayed_observation_can_coincide_with_neck_retest(self):
        bars,_=reversal_data()
        bars[36]=replace(bars[36],close=13,high=13.2)
        bars[37]=replace(bars[37],close=12.1,high=12.25,low=11.8)
        layouts,_=hierarchy_double_bottom_candidates(bars[:38],allow_delayed=True)
        self.assertTrue(layouts)
        candidate=layouts[0]
        self.assertLess(bars[37].close,candidate['neckline'])
        self.assertGreater(bars[37].close,candidate['neckline']*.975)


class CandidatePoolTests(unittest.TestCase):
    def strategy(self):
        return DirectionDoubleBottom('pool',dict(candidate_mode='pool',structure_mode='hierarchy',
            retest_mode='boundary',lower_cycle='daily_nested'))

    def bars(self):
        return [Bar('X',f'202401{i+1:02d}',10.5,12,8,11,100) for i in range(9)]

    def candidate(self,first=1,area=100,bottom=7):
        return dict(first=first,second=4,confirmed=6,neckline=10,bottom=bottom,origin=0,
                    pattern_area=area,prior_area=0,first_breakout_index=6,first_observable_index=6)

    def confirmation(self):
        return dict(kind='sloping',floor=8,correction_duration=3,peak_date='20240105',
            trough_date='20240108',retest_start_date='20240106',correction_range=2,
            recovery_trigger=10,recovery_mode='boundary')

    def test_failed_large_candidate_does_not_hide_confirming_alternative(self):
        bars=self.bars();s=self.strategy();state=dict(direction='unknown',pending=None)
        layouts=[self.candidate(bottom=9),self.candidate(first=2,area=50)]
        with (patch('trading_system.strategies.direction_double_bottom.hierarchy_double_bottom_candidates',return_value=(layouts,'qualified')),
             patch('trading_system.strategies.direction_double_bottom.structured_retest',return_value=(self.confirmation(),{}))):
            events=s.advance_candidate_pool(bars[-1],bars,state)
        self.assertEqual(state['direction'],'long')
        self.assertEqual(state['direction_source']['first'],2)
        self.assertEqual(sum(e['event']=='weekly_reversal_invalidated' for e in events),1)

    def test_waiting_candidate_does_not_block_registration_or_duplicate_identity(self):
        bars=self.bars();s=self.strategy();state=dict(direction='unknown',pending=None)
        with (patch('trading_system.strategies.direction_double_bottom.hierarchy_double_bottom_candidates',return_value=([self.candidate()],'qualified')),
             patch('trading_system.strategies.direction_double_bottom.structured_retest',return_value=(None,dict(reason='adjustment_not_complete')))):
            s.advance_candidate_pool(bars[-1],bars,state)
            s.advance_candidate_pool(bars[-1],bars,state)
        self.assertEqual(len(state['candidates']),1)
        with (patch('trading_system.strategies.direction_double_bottom.hierarchy_double_bottom_candidates',return_value=([self.candidate(first=2)],'qualified')),
             patch('trading_system.strategies.direction_double_bottom.structured_retest',return_value=(None,dict(reason='adjustment_not_complete')))):
            s.advance_candidate_pool(bars[-1],bars,state)
        self.assertEqual(len(state['candidates']),2)

    def test_active_direction_owner_is_not_replaced_by_another_layout(self):
        bars=self.bars();s=self.strategy();state=dict(direction='long',floor=7,
            direction_source={'owner':'original'},pending=None)
        with (patch.object(s,'top_failure',return_value=False),
             patch('trading_system.strategies.direction_double_bottom.hierarchy_double_bottom_candidates',return_value=([self.candidate()],'qualified')),
             patch('trading_system.strategies.direction_double_bottom.structured_retest',return_value=(self.confirmation(),{}))):
            events=s.advance_candidate_pool(bars[-1],bars,state)
        self.assertEqual(state['direction_source'],{'owner':'original'})
        self.assertFalse(any(e['event']=='upper_direction_confirmed' for e in events))

    def test_unsupported_pool_modes_rejected(self):
        with self.assertRaises(ValueError):DirectionDoubleBottom('bad',{'candidate_mode':'pool'})

    def test_factor_change_rescales_each_candidate_once(self):
        s=self.strategy();candidate=self.candidate()
        s.states['X']=dict(direction='unknown',processed='',pending=dict(candidate),
            candidates=[candidate],factor=1)
        bar=Bar('X','20240105',10,12,8,11,100,factor=2)
        with patch.object(s,'advance_candidate_pool',return_value=[]):
            s.on_close([bar],{bar.date})
        self.assertEqual(candidate['neckline'],5)
        self.assertEqual(candidate['bottom'],3.5)
        self.assertEqual(candidate['pattern_area'],50)
        self.assertEqual(s.states['X']['pending']['neckline'],5)

    def test_delayed_neck_retest_is_tracked_until_existing_failure_boundary(self):
        bars,_=reversal_data();s=self.strategy();state=dict(direction='unknown',pending=None)
        bars[36]=replace(bars[36],close=13,high=13.2)
        bars[37]=replace(bars[37],close=12.1,high=12.25,low=11.8)
        s.advance_candidate_pool(bars[37],bars[:38],state)
        self.assertTrue(state['candidates'])
        self.assertEqual(state['direction'],'unknown')
        bars[38]=replace(bars[38],close=11.9,high=12.1,low=11.7)
        events=s.advance_candidate_pool(bars[38],bars[:39],state)
        self.assertFalse(state['candidates'])
        self.assertTrue(any(e['event']=='weekly_reversal_invalidated' and e['reason']=='structure_lost' for e in events))

    def test_delayed_broken_neck_is_not_mistaken_for_valid_candidate(self):
        bars,_=reversal_data();s=self.strategy();state=dict(direction='unknown',pending=None)
        bars[36]=replace(bars[36],close=13,high=13.2)
        bars[37]=replace(bars[37],close=11.9,high=12.25,low=11.8)
        s.advance_candidate_pool(bars[37],bars[:38],state)
        self.assertFalse(state['candidates'])
        self.assertEqual(state['direction'],'unknown')
