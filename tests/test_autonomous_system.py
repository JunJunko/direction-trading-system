import json,unittest
from pathlib import Path
from dataclasses import replace
from test_direction_system import core_data
from trading_system.account import AutomaticPolicy
from trading_system.engine import Backtest
from trading_system.domain import Position
from trading_system.strategies import build_strategies
from trading_system.strategies.autonomous_double_bottom import AutonomousDoubleBottom


class AutonomousTests(unittest.TestCase):
    def fixture(self):
        bars=core_data()[:11]
        values=[10,11,12,13,14,13.8,13.5,13,13.3,13.7,14.2]
        bars=[replace(b,open=v-.02,high=v+.05,low=v-.05,close=v) for b,v in zip(bars,values)]
        p=Position('auto','X',bars[0].date,10,100,9,100,5,'id',1,
            dict(core_a='20231201',core_b='20231210',core_c='20231215',
                 correction_duration=3,correction_range=2,correction_area=8))
        s=AutonomousDoubleBottom('auto',dict(lower_cycle='daily_nested'))
        s.states['X']=dict(direction='long')
        return s,p,bars

    def test_automatic_policy_contraction_is_sticky_and_never_expands(self):
        p=AutomaticPolicy({})
        self.assertEqual(p.observe('20240101',100)['multiplier'],1)
        self.assertEqual(p.observe('20240102',96)['contraction_steps'],1)
        self.assertEqual(p.observe('20240103',110)['contraction_steps'],1)
        self.assertFalse(p.observe('20240104',120)['allow_cycle_upgrade'])
        self.assertFalse(p.observe('20240105',130)['win_expansion'])

    def test_production_needs_automatic_policy_and_real_hourly_mode(self):
        root=Path(__file__).resolve().parents[1]
        c=json.loads((root/'configs/experiments/double_bottom_v5_4.json').read_text())
        Backtest(c,build_strategies(c['strategies']))
        c['strategies'][0]['params']['lower_cycle']='daily_nested'
        with self.assertRaises(ValueError):Backtest(c,build_strategies(c['strategies']))
        c['research_scope']='structure_only'
        c.pop('automatic_account_policy')
        with self.assertRaises(ValueError):Backtest(c,build_strategies(c['strategies']))

    def test_small_local_lows_cannot_change_core_stop(self):
        s,p,bars=self.fixture()
        p.plan['correction_duration']=8
        s.manage_position(bars,p)
        self.assertEqual(p.stop,9)
        self.assertEqual(p.plan['core_reference_duration'],8)
        self.assertEqual(s.trailing_stop(bars,p),9)

    def test_core_promotion_is_confirmed_and_never_lowers_stop(self):
        s,p,bars=self.fixture()
        for i in range(1,len(bars)):
            exits,_=s.manage_position(bars[:i+1],p)
            self.assertFalse(exits)
            if i<10:self.assertEqual(p.stop,9)
        self.assertGreater(p.stop,12)
        self.assertEqual(p.plan['holding_state'],'core_trend')
        self.assertEqual(p.plan['core_owner'],'id')
        old=p.stop;s.manage_position(bars,p)
        self.assertEqual(p.stop,old)

    def test_adjustment_wait_has_explicit_deadline(self):
        s,p,bars=self.fixture()
        bars[-1]=replace(bars[-1],high=13.9,close=13.8,open=13.7,low=13.6)
        exits,_=s.manage_position(bars,p)
        self.assertEqual(exits[0].reason,'owned_core_adjustment_timeout')
        self.assertEqual(p.plan['holding_state'],'exit_pending')

    def test_missing_core_and_lost_direction_exit(self):
        s,p,bars=self.fixture();p.plan={}
        self.assertEqual(s.manage_position(bars,p)[0][0].reason,'missing_core_record')
        s.states['X']['direction']='unknown'
        self.assertEqual(s.manage_position(bars,p)[0][0].reason,'upper_direction_lost')

    def test_foreign_core_cannot_manage_this_position(self):
        s,p,bars=self.fixture();p.plan['core_owner']='another-trade'
        self.assertEqual(s.manage_position(bars,p)[0][0].reason,'mismatched_core_owner')

    def test_missing_hourly_data_cannot_emit_production_entry(self):
        s=AutonomousDoubleBottom('auto',{})
        bars=core_data()
        s.states['X']=dict(direction='long',processed='',pending=None,factor=1,floor=9,confirmed_date='20240101')
        intents,events=s.on_close(bars,set())
        self.assertFalse(intents)
        self.assertTrue(any(e.get('reason')=='missing_current_completed_hourly_session' for e in events))

if __name__=='__main__':unittest.main()
