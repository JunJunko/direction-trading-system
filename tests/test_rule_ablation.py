"""Research harness guards: causal inputs, equivalent extraction, isolated edits."""
import sys,unittest,copy,tempfile
from pathlib import Path
from dataclasses import asdict,replace
from types import MethodType
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ablation_rules import VARIANTS,FrozenUpper,entry_method,holding_method,bind_entry,bind_replay,edit
from trading_system.strategies import direction_double_bottom as dm,autonomous_double_bottom as am
from trading_system import wave_hierarchy as wm
from test_direction_system import core_data
import test_autonomous_system as fixtures


class RuleAblationTests(unittest.TestCase):
    def test_account_outputs_cannot_overwrite_a_frozen_log(self):
        from run_rule_ablation import account_output
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);locked=out/'frozen-baseline';locked.mkdir()
            original=locked/'decisions.csv';original.write_text('immutable log',encoding='utf-8')
            for variant in ('frozen-baseline','frozen-baseline/child'):
                with self.assertRaises(ValueError):account_output(out,variant,locked)
            target=account_output(out,'baseline',locked)
            (target/'decisions.csv').write_text('research output',encoding='utf-8')
            self.assertEqual(original.read_text(encoding='utf-8'),'immutable log')

    def test_all_frozen_anchors_compile_and_drift_fails_closed(self):
        self.assertEqual(len({v['id'] for v in VARIANTS}),len(VARIANTS))
        for v in VARIANTS:
            entry_method(dm,wm,v['rule']);holding_method(am,v['rule'])
        with self.assertRaises(ValueError):edit('changed code','missing anchor','replacement')

    def test_extracted_baseline_matches_incremental_original_with_factor_change(self):
        bars=core_data()
        bars[18]=replace(bars[18],close=12.95,high=13.01,low=12.9)
        # A known corporate-action factor changes the entire as-of price basis.
        bars.extend([replace(bars[-1],date='20240201',factor=1.02),
                     replace(bars[-1],date='20240202',factor=1.02)])
        params=dict(lower_cycle='daily_nested',core_mode='nested',entry_lifecycle='fresh')
        original=am.AutonomousDoubleBottom('fixed',params)
        replay=bind_entry(am.AutonomousDoubleBottom('fixed',params),entry_method(dm,wm,None),FrozenUpper({}))
        for s in (original,replay):
            s.states['X']=dict(direction='long',processed='',pending=None,factor=1,floor=9,confirmed_date='20240101')
        for i in range(len(bars)):
            a,ae=original.on_close(bars[:i+1],set());b,be=replay.on_close(bars[:i+1],set())
            self.assertEqual([asdict(x) for x in a],[asdict(x) for x in b])
            relevant=lambda es:[e for e in es if not e['event'].startswith('weekly_')]
            self.assertEqual(relevant(ae),relevant(be))
            self.assertEqual(original.seen,replay.seen)

    def test_upper_events_cannot_leak_backwards_and_same_day_replacement_is_ordered(self):
        bars=core_data();day=bars[2].date
        events={('X',day):[dict(date=day,event='upper_direction_lost'),
            dict(date=day,event='upper_direction_confirmed',floor=8,candidate_id='new')]}
        upper=FrozenUpper(events);s=am.AutonomousDoubleBottom('fixed',dict(lower_cycle='daily_nested'))
        upper.apply(s,bars[0]);self.assertEqual(s.states['X']['direction'],'unknown')
        upper.apply(s,bars[2]);self.assertEqual(s.states['X']['direction'],'long')
        self.assertEqual(s.states['X']['direction_source']['candidate_id'],'new')
        upper.apply(s,replace(bars[3],factor=2));self.assertEqual(s.states['X']['floor'],4)
        self.assertEqual(events[('X',day)][1]['floor'],8)

    def test_cached_intent_evidence_is_not_mutated_between_accounts(self):
        from trading_system.domain import Intent
        bars=core_data();bar=bars[0]
        intent=Intent('fixed','X',bar.date,12,10,20,'id','test',dict(flag=['original']))
        tape={('X',bar.date):([intent],[dict(event='test',date=bar.date)])}
        s=bind_replay(am.AutonomousDoubleBottom('fixed',dict(lower_cycle='daily_nested')),tape,FrozenUpper({}),holding_method(am,None))
        got,_=s.on_close([bar],set());got[0].evidence['flag'].append('account one')
        again,_=s.on_close([bar],set())
        self.assertEqual(again[0].evidence['flag'],['original'])

    def test_duration_and_range_gates_interact_on_a_real_confirmed_correction(self):
        # Same valid, known matched N; time short vs 30, width shallow vs 2.
        # Removing either subgate alone still leaves the other rejecting it.
        observed={}
        for rule in (None,'holding_level','holding_range','holding_duration'):
            _,p,bars=fixtures.AutonomousTests().fixture()
            p.plan.update(core_c=bars[0].date,small_c=bars[0].date,correction_duration=30)
            s=am.AutonomousDoubleBottom('auto',dict(lower_cycle='daily_nested',core_mode='nested',
                protection_mode='live_leg',holding_scale_mode='owned_core'))
            s.states['X']=dict(direction='long')
            s.manage_live_leg=MethodType(holding_method(am,rule),s)
            s.manage_position(bars[:10],p);observed[rule]=p.stop
        self.assertEqual(observed[None],9)
        self.assertEqual(observed['holding_range'],9)
        self.assertEqual(observed['holding_duration'],9)
        self.assertGreater(observed['holding_level'],12)

    def test_structural_audit_ignores_future_and_identifies_false_correction_floor(self):
        from audit_rule_ablation import audit_plan
        from trading_system.analysis import adjusted
        from trading_system.structure import SwingCache
        bars=core_data()[:19];bars[-1]=replace(bars[-1],close=12.95,high=13.01,low=12.9)
        s=am.AutonomousDoubleBottom('fixed',dict(lower_cycle='daily_nested',core_mode='nested',entry_lifecycle='fresh'))
        s.states['X']=dict(direction='long',processed='',pending=None,factor=1,floor=9,confirmed_date='20240101')
        p=asdict(s.on_close(bars,set())[0][0])
        original=audit_plan(p,bars,adjusted,SwingCache)
        future=replace(bars[-1],date='20990101',high=1000,close=900,open=900,low=800,factor=100)
        self.assertEqual(original,audit_plan(p,bars+[future],adjusted,SwingCache))
        changed=list(bars);changed[10]=replace(changed[10],low=11.8)
        bad=audit_plan(p,changed,adjusted,SwingCache)
        self.assertTrue(any('核心C不是' in x for x in bad['errors']))

if __name__=='__main__':unittest.main()
