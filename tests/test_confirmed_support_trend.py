import copy,json,unittest
from dataclasses import replace
from pathlib import Path
from trading_system.confirmed_support_trend import ConfirmedSupportTrend,confirmed_weekly_points
from trading_system.main_trend import MainTrend,completed_weeks
from trading_system.strategies.breakout_trend_ihs import BreakoutTrendIHS
from trading_system.strategies.confirmed_support_ihs import ConfirmedSupportIHS
from trading_system.engine import Backtest


class ConfirmedSupportTests(unittest.TestCase):
    def setUp(self):
        from test_main_trend import Tests
        f=Tests();f.setUp()
        self.bs,self.cal,self.ends,self.p=f.bars,f.cal,f.ends,f.p

    def manager(self,**kwargs):return ConfirmedSupportTrend('x',self.cal,self.ends,**kwargs)

    def test_two_right_complete_weeks_required(self):
        m=self.manager()
        self.assertFalse(m.manage(self.bs[:69],self.p)[1]);self.assertIsNone(m.protection)
        m.manage(self.bs[:70],self.p);self.assertEqual(m.protection,8)

    def test_lower_high_does_not_veto_higher_support(self):
        bs=[replace(b,high=18) if 40<=i<45 else b for i,b in enumerate(self.bs)]
        old=MainTrend('x',self.cal,self.ends);old.manage(bs[:70],self.p)
        new=self.manager();new.manage(bs[:70],self.p)
        self.assertIsNone(old.protection);self.assertEqual(new.protection,8)

    def test_higher_trough_without_intervening_peak_is_kept(self):
        bs=[replace(b,high=15) for b in self.bs]
        m=self.manager();m.manage(bs[:70],self.p);self.assertEqual(m.protection,8)

    def test_monotonic_and_initial_stop_unchanged(self):
        m=self.manager();m.protection=9
        _,events=m.manage(self.bs[:70],self.p)
        self.assertEqual(m.protection,9);self.assertEqual(self.p.stop,3)
        self.assertEqual(events[-1]['event'],'main_support_not_raised')

    def test_trough_week_must_start_after_entry(self):
        self.p.entry_date=self.cal[56]
        m=self.manager();m.manage(self.bs[:70],self.p);self.assertIsNone(m.protection)

    def test_daily_break_and_weekly_ablation(self):
        bs=self.bs[:71];bs[-1]=replace(bs[-1],open=9,high=12,low=6,close=7)
        daily=self.manager();daily.protection=8
        weekly=self.manager(exit_clock='weekly');weekly.protection=8
        self.assertEqual(daily.manage(bs,self.p)[0][0].reason,'confirmed_support_daily_break')
        self.assertFalse(weekly.manage(bs,self.p)[0])
        self.assertFalse(daily.manage(bs,self.p)[0])  # Pending order is engine-owned.

    def test_intraday_touch_is_not_close_confirmation(self):
        bs=self.bs[:71];bs[-1]=replace(bs[-1],open=9,high=12,low=6,close=9)
        m=self.manager();m.protection=8;self.assertFalse(m.manage(bs,self.p)[0])

    def test_factor_invariance(self):
        m=self.manager();bs=[replace(b,open=b.open/2,high=b.high/2,low=b.low/2,close=b.close/2,factor=2) for b in self.bs]
        self.p.stop=1.5;self.p.factor=2
        m.manage(bs[:70],self.p);self.assertEqual(m.protection,8)

    def test_future_prices_cannot_change_confirmed_points(self):
        a=confirmed_weekly_points(completed_weeks(self.bs[:70],self.cal))
        tail=list(self.bs);tail[-1]=replace(tail[-1],high=100,low=1)
        b=confirmed_weekly_points(completed_weeks(tail,self.cal))
        self.assertEqual(a,[p for p in b if p['confirmed']<=self.ends[13]])

    def test_pressure_break_is_observation_not_profit_exit(self):
        m=self.manager();m.manage(self.bs[:55],self.p);self.assertEqual(m.pressure,25)
        bs=self.bs[:56];bs[-1]=replace(bs[-1],open=26,high=28,low=25,close=27)
        exits,events=m.manage(bs,self.p)
        self.assertFalse(exits);self.assertIsNone(m.pressure)
        self.assertEqual(events[0]['event'],'main_pressure_broken')
        self.assertIsNone(m.protection)  # No automatic pressure-to-support promotion.

    def test_entries_and_initial_risk_identical(self):
        from test_breakout_trend_ihs import BreakoutTests
        f=BreakoutTests();bs=f.bars()
        old,new=BreakoutTrendIHS('same',{}),ConfirmedSupportIHS('same',{})
        for i in range(1,len(bs)+1):self.assertEqual(old.on_close(bs[:i],set()),new.on_close(bs[:i],set()))
        a=json.loads(Path('configs/experiments/inverse_head_shoulders_v5_breakout_trend.json').read_text())
        b=json.loads(Path('configs/experiments/inverse_head_shoulders_v6_confirmed_support.json').read_text())
        b['strategies'][0]['type']=a['strategies'][0]['type'];b['strategies'][0]['id']=a['strategies'][0]['id']
        self.assertEqual(a,b)

    def test_daily_exit_next_open_and_limit_down_deferral(self):
        cfg=json.loads(Path('configs/experiments/inverse_head_shoulders_v6_confirmed_support.json').read_text())
        e=Backtest(cfg,[]);e.positions['X']=self.p;e.marks['X']=12
        m=self.manager();m.protection=8
        bs=self.bs[:71];bs[-1]=replace(bs[-1],open=9,high=12,low=6,close=7)
        e.pending_exits=m.manage(bs,self.p)[0]
        b=replace(self.bs[71],open=6,high=6,low=6,close=6,down_limit=6)
        e.execute_interval({'X':b},b.date,None,e.cash)
        self.assertIn('X',e.positions);self.assertEqual(len(e.pending_exits),1)
        b=replace(self.bs[72],open=5.5,high=6,low=5,close=5.7)
        e.execute_interval({'X':b},b.date,None,e.cash)
        self.assertAlmostEqual(e.trades[0]['exit'],5.5*.999)
        self.assertEqual(e.trades[0]['reason'],'confirmed_support_daily_break')

    def test_missing_week_does_not_prevent_daily_exit_against_old_level(self):
        bs=self.bs[:75];bs=[b for i,b in enumerate(bs) if i!=71];bs[-1]=replace(bs[-1],low=6,close=7)
        m=self.manager();m.protection=8
        self.assertTrue(m.manage(bs,self.p)[0])

if __name__=='__main__':unittest.main()
