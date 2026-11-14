import unittest
from dataclasses import replace
from test_direction_system import core_data
from trading_system.structure import n_structure, effective_pressures, Swing, rhythm
from trading_system.strategies.autonomous_double_bottom import AutonomousDoubleBottom


class CoreOwnershipTests(unittest.TestCase):
    def test_holding_owner_does_not_overwrite_entry_owner_on_renewal(self):
        s=AutonomousDoubleBottom('owned',dict(lower_cycle='daily_nested',core_mode='owned',
                                            entry_lifecycle='fresh',right=3))
        s.states['X']=dict(direction='long',processed='',pending=None,factor=1,
                           floor=9,confirmed_date='20240101')
        bars=core_data()[:19]
        bars[-1]=replace(bars[-1],close=12.95,high=13.01,low=12.9)
        intents,_=s.on_close(bars,set())
        self.assertEqual(len(intents),1)
        intent=intents[0]
        self.assertEqual(intent.evidence['entry_core_owner'],intent.evidence['small_owner'])
        self.assertEqual(intent.evidence['core_owner'],intent.setup_id)
        next_bar=replace(bars[-1],date=core_data()[19].date)
        renewed,events=s.on_close(bars+[next_bar],set())
        self.assertEqual(renewed[0].setup_id,intent.setup_id)
        self.assertFalse(any(e.get('reason')=='core_owner_changed' for e in events))
        final_bar=replace(next_bar,date='20240129')
        intents,events=s.on_close(bars+[next_bar,final_bar],set())
        self.assertFalse(intents)
        self.assertTrue(any(e.get('reason')=='core_owner_changed' for e in events))

    def test_new_failed_correction_does_not_resurrect_old_core(self):
        bars=core_data()
        # Explicit causal pivots: old N qualifies, newer N has a lower low.
        points=[Swing('low',0,2,5),Swing('high',4,6,12),Swing('low',7,9,9),
                Swing('high',10,12,13),Swing('low',13,15,8)]
        bars=[replace(b,low=10,high=13) for b in bars]
        self.assertIsNotNone(n_structure(bars,points=points)[0])
        core,reason=n_structure(bars,points=points,ownership=True)
        self.assertIsNone(core)
        self.assertEqual(reason,'latest_core_not_qualified')

    def test_direction_origin_and_owner_dates(self):
        bars=[replace(b,low=10,high=13) for b in core_data()]
        points=[Swing('low',0,2,5),Swing('high',4,6,12),Swing('low',7,9,9)]
        core,_=n_structure(bars,points=points,ownership=True)
        self.assertEqual(core['owner_id'],':'.join(bars[i].date for i in (0,4,7)))
        self.assertIsNone(n_structure(bars,points=points,ownership=True,
                                     origin_date=bars[1].date)[0])

    def test_pressure_scale_and_consumption(self):
        bars=[replace(b,close=11,high=12,low=10) for b in core_data()]
        core=dict(a=10,b=12,c=15,correction_duration=3)
        points=[Swing('high',1,3,15),Swing('low',5,7,10),
                Swing('high',6,8,14),Swing('low',7,9,13)]
        levels,audit=effective_pressures(bars,points,core,12)
        self.assertEqual(levels,[15])
        self.assertEqual(audit[1]['reason'],'smaller_than_core_correction')
        crossed=list(bars);crossed[8]=replace(crossed[8],close=15.1)
        levels,audit=effective_pressures(crossed,points,core,12)
        self.assertEqual(levels,[])
        self.assertEqual(audit[0]['reason'],'previously_broken')

    def test_small_structure_cannot_belong_before_core_floor(self):
        bars=core_data()
        core=dict(c=10,correction_duration=5,correction_area=100, b=7,
                  owner_id='current')
        points=[Swing('low',1,2,10),Swing('high',4,5,14),Swing('low',6,7,12)]
        self.assertEqual(rhythm(bars,core,points=points,planned=True,
                                ownership=True)[1],'no_small_n')

    def test_peak_declining_to_core_origin_is_still_resistance(self):
        bars=[replace(b,close=11,high=12,low=10) for b in core_data()]
        core=dict(a=10,b=12,c=15,correction_duration=3)
        points=[Swing('high',1,3,15),Swing('low',10,12,10)]
        self.assertEqual(effective_pressures(bars,points,core,12)[0],[15])

    def test_invalid_small_geometry_is_discarded(self):
        bars=core_data()
        core=dict(c=0,correction_duration=5,correction_area=100,b=0,owner_id='current')
        points=[Swing('low',1,2,10),Swing('high',4,5,9),Swing('low',6,7,11)]
        self.assertEqual(rhythm(bars,core,points=points,planned=True,
                                ownership=True)[1],'small_n_invalid_geometry')


if __name__=='__main__':unittest.main()
