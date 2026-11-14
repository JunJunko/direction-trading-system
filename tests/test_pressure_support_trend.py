import json,unittest
from dataclasses import replace
from pathlib import Path
from trading_system.pressure_support_trend import PressureSupportTrend
from trading_system.strategies.pressure_support_ihs import PressureSupportIHS
from trading_system.strategies.breakout_trend_ihs import BreakoutTrendIHS
from trading_system.strategies import build_strategies
from trading_system.engine import Backtest


class PressureSupportTests(unittest.TestCase):
    def setUp(self):
        from test_main_trend import Tests
        f=Tests();f.setUp()
        self.bs,self.cal,self.ends,self.p=f.bars,f.cal,f.ends,f.p

    def manager(self):return PressureSupportTrend('x',self.cal,self.ends)

    def warmed(self):
        m=self.manager()
        for n in range(36,71):m.manage(self.bs[:n],self.p)
        return m

    def shock(self,close=27,high=30,low=19):
        bs=self.bs[:71];bs[-1]=replace(bs[-1],open=20,high=high,low=low,close=close)
        return bs

    def test_seed_only_prior_confirmed_overhead_pressure(self):
        m=self.manager();_,events=m.manage(self.bs[:36],self.p)
        self.assertEqual(m.pressure,20);self.assertEqual(set(m.levels),{20})
        self.assertTrue(all(e['confirmed']<self.bs[35].date for e in events))
        self.assertIsNone(m.protection)

    def test_already_broken_level_below_entry_is_not_seeded(self):
        self.p.entry=21
        m=self.manager();m.manage(self.bs[:36],self.p)
        self.assertIsNone(m.pressure);self.assertIsNone(m.protection)

    def test_pressure_waits_two_right_weeks(self):
        m=self.manager()
        for n in range(36,55):m.manage(self.bs[:n],self.p)
        self.assertNotIn(25,m.levels)
        m.manage(self.bs[:55],self.p);self.assertIn(25,m.levels)

    def test_break_two_levels_holds_and_promotes_highest(self):
        m=self.warmed();self.assertEqual(set(m.levels),{20,25})
        exits,events=m.manage(self.shock(),self.p)
        self.assertFalse(exits);self.assertEqual(m.protection,25);self.assertIsNone(m.pressure)
        e=next(e for e in events if e['event']=='dynamic_pressure_breakout')
        self.assertEqual(e['broken_pressures'],[20,25])
        self.assertEqual(self.p.stop,3)

    def test_break_first_level_keeps_next_known_pressure(self):
        m=self.warmed();m.manage(self.shock(close=22,high=24),self.p)
        self.assertEqual(m.protection,20);self.assertEqual(m.pressure,25)

    def test_intraday_spike_and_marginal_close_do_not_promote(self):
        for close in (19,20.05):
            m=self.warmed();exits,_=m.manage(self.shock(close=close,low=18),self.p)
            self.assertFalse(exits);self.assertEqual(m.protection,8);self.assertEqual(m.pressure,20)

    def test_breakout_day_low_cannot_hit_new_support_retroactively(self):
        m=self.warmed();bs=self.shock(low=10)
        exits,_=m.manage(bs,self.p)
        self.assertFalse(exits);self.assertEqual(m.protection,25)
        bs.append(replace(self.bs[71],open=27,high=28,low=24,close=26))
        self.assertFalse(m.manage(bs,self.p)[0])  # Normal intraday retest, close still holds.

    def test_daily_support_break_next_session_exit_and_gap(self):
        m=self.warmed();bs=self.shock();m.manage(bs,self.p)
        bs.append(replace(self.bs[71],open=26,high=27,low=23,close=24))
        exits,_=m.manage(bs,self.p);self.assertEqual(exits[0].reason,'dynamic_support_daily_break')
        cfg=json.loads(Path('configs/experiments/inverse_head_shoulders_v7_pressure_support.json').read_text())
        e=Backtest(cfg,[]);e.positions['X']=self.p;e.marks['X']=24;e.pending_exits=exits
        b=replace(self.bs[72],open=22,high=24,low=21,close=23)
        e.execute_interval({'X':b},b.date,None,e.cash)
        self.assertAlmostEqual(e.trades[0]['exit'],22*.999)
        self.assertNotEqual(e.trades[0]['exit'],25)  # No guaranteed fill at the support line.
        self.assertFalse(m.manage(bs,self.p)[0])  # No duplicate order while engine owns it.

    def test_missing_week_does_not_disable_active_support_exit(self):
        m=self.warmed();bs=self.shock();m.manage(bs,self.p)
        bs.append(replace(self.bs[74],open=26,high=27,low=23,close=24))
        self.assertTrue(m.manage(bs,self.p)[0])

    def test_no_known_upper_pressure_keeps_trend_open(self):
        m=self.warmed();bs=self.shock();m.manage(bs,self.p)
        self.p.plan['ihs_target']=28
        bs.append(replace(self.bs[71],open=30,high=40,low=29,close=39))
        exits,_=m.manage(bs,self.p)
        self.assertFalse(exits);self.assertEqual(m.protection,25);self.assertIsNone(m.pressure)

    def test_support_does_not_fall_when_later_weekly_low_is_lower(self):
        m=self.manager();m.initialized=True;m.protection=9
        m.manage(self.bs[:70],self.p);self.assertEqual(m.protection,9)

    def test_new_lower_pressure_does_not_move_monitor_down(self):
        bs=[replace(b,high=18) if 40<=i<45 else b for i,b in enumerate(self.bs)]
        m=self.manager()
        for n in range(36,56):m.manage(bs[:n],self.p)
        self.assertEqual(m.pressure,20);self.assertNotIn(18,m.levels)

    def test_economic_levels_are_factor_invariant(self):
        bs=self.shock();scaled=[replace(b,open=b.open/2,high=b.high/2,low=b.low/2,close=b.close/2,factor=2) for b in bs]
        p=replace(self.p,entry=self.p.entry/2,stop=self.p.stop/2,factor=2)
        m=self.manager()
        for n in range(36,len(scaled)+1):m.manage(scaled[:n],p)
        self.assertEqual(m.protection,25);self.assertIsNone(m.pressure)

    def test_future_tail_cannot_change_earlier_state(self):
        def states(bs):
            m=self.manager();out=[]
            for n in range(36,len(bs)+1):
                ex,ev=m.manage(bs[:n],self.p);out.append((m.protection,m.pressure,ex,ev))
            return out
        a=states(self.bs[:70]);future=self.bs[:70]+[replace(b,high=100,low=1) for b in self.bs[70:]]
        self.assertEqual(a,states(future)[:len(a)])

    def test_repeated_close_is_idempotent(self):
        m=self.warmed();bs=self.shock();m.manage(bs,self.p)
        self.assertEqual(m.manage(bs,self.p),([],[]));self.assertEqual(m.protection,25)

    def test_v7_registration_and_identical_entry_signals(self):
        from test_breakout_trend_ihs import BreakoutTests
        cfg=json.loads(Path('configs/experiments/inverse_head_shoulders_v7_pressure_support.json').read_text())
        self.assertIsInstance(build_strategies(cfg['strategies'])[0],PressureSupportIHS)
        bs=BreakoutTests().bars();a=BreakoutTrendIHS('same',{});b=PressureSupportIHS('same',{})
        for n in range(1,len(bs)+1):self.assertEqual(a.on_close(bs[:n],set()),b.on_close(bs[:n],set()))

    def test_strategy_exposes_economic_support_and_pressure(self):
        s=PressureSupportIHS('x',{});s.set_trend_calendar(self.cal,self.ends)
        for n in range(36,71):s.manage_position(self.bs[:n],self.p)
        s.manage_position(self.shock(),self.p)
        self.assertEqual(self.p.plan['dynamic_support_economic'],25)
        self.assertIsNone(self.p.plan['dynamic_pressure_economic'])
        self.assertEqual(s.trailing_stop(self.shock(),self.p),3)

    def test_invalid_breakout_buffer_rejected(self):
        for v in (-1,float('nan'),True):
            with self.assertRaises(ValueError):PressureSupportIHS('x',{'pressure_breakout_atr':v})

if __name__=='__main__':unittest.main()
