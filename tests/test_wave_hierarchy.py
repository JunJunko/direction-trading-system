import unittest
from dataclasses import replace
from datetime import datetime,timedelta
from test_direction_system import core_data
import test_live_leg_protection as live_fixtures
from trading_system.structure import SwingCache
from trading_system.wave_hierarchy import WaveHierarchy,correction_level
from trading_system.strategies.autonomous_double_bottom import AutonomousDoubleBottom


def extend(bars,values):
    result=list(bars);day=datetime.strptime(result[-1].date,'%Y%m%d')
    for v in values:
        day+=timedelta(days=1)
        while day.weekday()>4:day+=timedelta(days=1)
        result.append(replace(result[-1],date=day.strftime('%Y%m%d'),open=v-.02,
                              high=v+.05,low=v-.05,close=v))
    return result


class WaveHierarchyTests(unittest.TestCase):
    def test_consumed_trigger_cannot_revive_after_later_price_retreat(self):
        strategy=AutonomousDoubleBottom('nested',dict(lower_cycle='daily_nested',core_mode='nested',entry_lifecycle='fresh'))
        strategy.states['X']=dict(direction='long',processed='',pending=None,factor=1,floor=9,confirmed_date='20240101')
        bars=core_data()[:20];bars[-1]=replace(bars[-1],close=12.95,high=13.01,low=12.9)
        # The small C at index 17 is confirmed at 18, when price already
        # crosses its peak. Today's close is back below that trigger.
        intents,events=strategy.on_close(bars,set())
        self.assertFalse(intents)
        waits=[e for e in events if e.get('reason')=='trigger_consumed_before_plan']
        self.assertTrue(waits)
        consumed=waits[0]['setup_id'];self.assertIn(consumed,strategy.seen)
        self.assertEqual(waits[0]['first_touch_date'],bars[18].date)
        intents,_=strategy.on_close(extend(bars,[12.96]),set())
        self.assertTrue(all(i.setup_id!=consumed for i in intents))

    def test_strategy_emits_owned_core_without_argument_collision(self):
        strategy=AutonomousDoubleBottom('nested',dict(lower_cycle='daily_nested',core_mode='nested',entry_lifecycle='fresh'))
        strategy.states['X']=dict(direction='long',processed='',pending=None,factor=1,floor=9,confirmed_date='20240101')
        bars=core_data()[:19];bars[-1]=replace(bars[-1],close=12.95,high=13.01,low=12.9)
        intents,events=strategy.on_close(bars,set())
        self.assertEqual(len(intents),1)
        self.assertTrue(any(e['event']=='wave_core_accepted' for e in events))
        self.assertEqual(intents[0].evidence['small_owner'],intents[0].evidence['entry_core_owner'])

    def test_higher_later_trough_cannot_stretch_old_decline(self):
        bars=extend(core_data(),[13.1,12.8,12.3,12.6,12.9,12.5,12.7,13.0])
        # The actual correction floor precedes the later higher trough.
        model=WaveHierarchy()
        self.assertIsNone(model._candidate(bars,12,19,25,27))
    def test_level_boundaries(self):
        self.assertEqual(correction_level(2,1,4,2),'internal')
        self.assertEqual(correction_level(4,2,4,2),'core')
        self.assertEqual(correction_level(5,1,4,2),'unresolved')
        self.assertEqual(correction_level(2,3,4,2),'unresolved')

    def test_internal_trough_preserves_parent_and_has_real_owner(self):
        bars=core_data();model=WaveHierarchy()
        first=model.get(bars[:17])[0]
        core,reason,events=model.get(bars)
        self.assertEqual(core['owner_id'],first['owner_id'])
        self.assertEqual(reason,'qualified')
        children=[e for e in events if e['event']=='wave_correction_classified']
        self.assertEqual(children[-1]['level'],'internal')
        self.assertEqual(children[-1]['owner_id'],core['owner_id'])
        self.assertEqual(core['rhythm_floor_date'],bars[17].date)
        self.assertEqual(model.ledger[core['owner_id']]['state'],'active')

    def test_failed_child_does_not_end_intact_parent(self):
        bars=core_data();model=WaveHierarchy();core=model.get(bars)[0]
        tail=extend(bars,[12.6]);current,reason,_=model.get(tail)
        self.assertIsNone(current)
        self.assertEqual(reason,'wave_child_failed_waiting_for_new_floor')
        self.assertEqual(model.ledger[core['owner_id']]['state'],'active')
        self.assertNotIn(core['owner_id'],model.retired)

    def test_timeout_ends_core_and_never_revives_it(self):
        bars=core_data();model=WaveHierarchy();owner=model.get(bars)[0]['owner_id']
        extended=extend(bars,[13.0]*10);core,_,_=model.get(extended)
        self.assertIsNone(core)
        self.assertIn(owner,model.retired)
        self.assertEqual(model.ledger[owner]['end_reason'],'adjustment_timeout')
        model.get(extend(extended,[13.3,13.4,13.0]))
        self.assertEqual(model.ledger[owner]['state'],'ended')

    def test_rebound_cannot_revive_failed_child_before_new_floor_confirmation(self):
        # Both a recovery through the old trough candle and a new high must
        # leave the failed rhythm unavailable until a new floor is confirmed.
        for value in (13.4,14.0):
            bars=core_data();model=WaveHierarchy();core=model.get(bars)[0]
            owner=core['owner_id'];old_floor=core['rhythm_floor_date']
            bars=extend(bars,[12.6]);model.get(bars)
            bars=extend(bars,[value]);core,reason,_=model.get(bars)
            self.assertIsNone(core)
            self.assertEqual(reason,'wave_child_failed_waiting_for_new_floor')
            self.assertEqual(model.ledger[owner]['state'],'active')
            # The second right-hand candle confirms the NEW low, which may
            # establish a fresh child; this is not reuse of the failed floor.
            bars=extend(bars,[14.1]);core,_,_=model.get(bars)
            self.assertIsNotNone(core)
            self.assertNotEqual(core['rhythm_floor_date'],old_floor)

    def test_fresh_independent_n_after_timeout_remains_allowed(self):
        bars=extend(core_data(),[13.0]*10)
        model=WaveHierarchy();model.get(bars)
        retired=set(model.retired)
        fresh=extend(bars,[12.7,12.3,12,12.5,13,13.5,14,14.5,14.2,13.8,13.5,13.7,14.0])
        core,_,_=model.get(fresh)
        self.assertIsNotNone(core)
        self.assertNotIn(core['owner_id'],retired)
        self.assertEqual(core['relation'],'independent')

    def test_projection_ends_old_space_but_successor_can_form(self):
        bars=extend(core_data()[:13],[13,13.8,14.4,14.9,15.4,15.8,16.1,15.6,15,14.5,13.9,14.2,14.6])
        model=WaveHierarchy();old=model.get(bars[:17])[0]['owner_id']
        core,_,events=model.get(bars)
        self.assertIsNotNone(core)
        self.assertNotEqual(core['owner_id'],old)
        self.assertEqual(core['parent_owner'],old)
        self.assertEqual(core['relation'],'same_level_successor')
        self.assertEqual(model.ledger[old]['end_reason'],'projection_consumed')
        self.assertTrue(any(e['event']=='wave_core_accepted' for e in events))

    def test_floor_failure_cannot_fall_back_to_earlier_n(self):
        bars=core_data();model=WaveHierarchy();old=model.get(bars)[0]['owner_id']
        model.get(extend(bars,[11.5,12,12.5]))
        self.assertEqual(model.ledger[old]['end_reason'],'floor_broken')
        self.assertIsNone(model.core)

    def test_unknown_extrema_are_recorded_with_confirmation(self):
        bars=core_data();bars[15]=replace(bars[15],high=16,low=11.5)
        cache=SwingCache(2,2);cache.get(bars[:17])
        self.assertFalse(cache.ambiguous)
        cache.get(bars[:18]);self.assertEqual(cache.ambiguous[0]['index'],15)
        self.assertEqual(cache.ambiguous[0]['confirmed'],17)
        model=WaveHierarchy();_,_,events=model.get(bars)
        self.assertTrue(any(e['event']=='wave_order_unknown' for e in events))

    def test_stream_and_bootstrap_have_same_ledger_at_every_prefix(self):
        bars=extend(core_data(),[13,12.9,13.2,13.5,13.1,12.8,12.5,12.2,12.4,12.6])
        model=WaveHierarchy()
        for end in range(1,len(bars)+1):
            core,reason,_=model.get(bars[:end]);batch=WaveHierarchy()
            other,other_reason,_=batch.get(bars[:end])
            self.assertEqual(core,other)
            self.assertEqual(reason,other_reason)
            self.assertEqual(model.ledger,batch.ledger)

    def test_repricing_preserves_ownership(self):
        bars=core_data();model=WaveHierarchy();core=model.get(bars)[0]
        scaled=[replace(b,open=b.open*2,high=b.high*2,low=b.low*2,close=b.close*2,factor=2) for b in extend(bars,[13.5])]
        after=model.get(scaled)[0]
        self.assertEqual(after['owner_id'],core['owner_id'])
        self.assertAlmostEqual(after['target'],core['target']*2)

    def test_direction_origin_is_a_real_boundary(self):
        bars=core_data();model=WaveHierarchy()
        self.assertIsNone(model.get(bars,origin_date=bars[4].date)[0])

    def test_holding_uses_same_scale_classification(self):
        for duration,drop,level,promotes in ((4,2,'internal',False),(3,2,'unresolved',False),(3,1,'core',True)):
            s,p,bars=live_fixtures.LiveLegTests().fixture();s.p['core_mode']='nested'
            p.plan.update(correction_duration=duration,correction_range=drop)
            _,events=s.manage_position(bars[:10],p)
            self.assertTrue(any(e.get('level')==level for e in events))
            self.assertEqual(p.stop>9,promotes)

    def test_new_upper_direction_cannot_reassign_existing_position(self):
        s,p,bars=live_fixtures.LiveLegTests().fixture();s.p['core_mode']='nested'
        p.plan['upper_owner_id']='old';s.wave_source_ids['X']='new'
        exits,_=s.manage_position(bars[:10],p)
        self.assertEqual(exits[0].reason,'upper_direction_owner_changed')

    def test_owned_daily_holding_does_not_use_lower_rhythm_clock(self):
        s,p,bars=live_fixtures.LiveLegTests().fixture()
        s.p['core_mode']='nested';s.holding_scale_mode='owned_core'
        p.plan.update(core_c=bars[0].date,small_c=bars[4].date,
                      correction_duration=3,correction_range=.8)
        # Daily C-to-peak has four bars; the lower rhythm C is at that peak.
        # A matched daily correction must remain protectable from daily C.
        exits,events=s.manage_position(bars[:10],p)
        self.assertFalse(exits)
        self.assertTrue(any(e['event']=='core_protection_promoted' for e in events))
        self.assertGreater(p.stop,12)

    def test_owned_core_timeout_uses_same_daily_reference(self):
        s,p,bars=live_fixtures.LiveLegTests().fixture()
        s.p['core_mode']='nested';s.holding_scale_mode='owned_core'
        p.plan.update(core_c=bars[0].date,small_c=bars[4].date,
                      correction_duration=10,correction_range=2)
        tail=extend(bars[:5],[13.8]*8)
        exits,_=s.manage_position(tail,p)
        self.assertFalse(exits)
        self.assertEqual(p.plan['live_anchor_date'],bars[0].date)
        exits,_=s.manage_position(extend(tail,[13.8]*5),p)
        self.assertEqual(exits[0].reason,'live_core_adjustment_timeout')

    def test_holding_later_higher_trough_cannot_stretch_a_fast_decline(self):
        s,p,base=live_fixtures.LiveLegTests().fixture()
        s.p['core_mode']='nested';s.holding_scale_mode='owned_core'
        bars=extend(base[:1],[10+4*i/15 for i in range(1,16)]+
            [13.6,13.2,13.0,13.3,13.6,13.9,13.7,13.5,13.2,13.4,13.6])
        p.plan.update(core_c=bars[0].date,small_c=bars[0].date,
                      correction_duration=8,correction_range=1)
        _,events=s.manage_position(bars,p)
        self.assertEqual(p.stop,9)
        self.assertTrue(any(e['event']=='holding_wave_rejected' and
                            e['reason']=='trough_not_actual_correction_floor' for e in events))


if __name__=='__main__':unittest.main()
