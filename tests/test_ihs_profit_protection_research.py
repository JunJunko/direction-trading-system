import unittest
from dataclasses import replace
from datetime import date,timedelta
from unittest.mock import patch
from trading_system.domain import Bar,Position,ExitIntent
from trading_system.strategies.pressure_support_ihs import PressureSupportIHS
from trading_system.pressure_support_trend import PressureSupportTrend
from trading_system.strategies.ihs_profit_protection_research import LargerProfitStructureIHS,HalfProfitRetentionIHS

class ProfitProtectionResearchTests(unittest.TestCase):
    def setup_case(self,kind):
        s=kind('test',{});p=Position('test','X','20260121',10,100,9,100,5,'seed',1,{})
        s.managers['seed']=PressureSupportTrend('test',[],set());s.managers['seed'].initialized=True
        h=[Bar('X',(date(2026,1,1)+timedelta(days=i)).strftime('%Y%m%d'),10,10.2,9.8,10,100) for i in range(20)]
        return s,p,h

    def test_larger_structure_waits_five_right_bars(self):
        s,p,h=self.setup_case(LargerProfitStructureIHS)
        lows=[10,12,12.1,12.2,12.3,12.4,11.5,12.4,12.3,12.2,12.1,12]
        with patch.object(PressureSupportIHS,'manage_position',side_effect=lambda *args:([],[])):
            for i,low in enumerate(lows):
                d=(date(2026,1,21)+timedelta(days=i)).strftime('%Y%m%d');h.append(Bar('X',d,low+.2,low+1.5,low,low+1.2,100))
                _,events=s.manage_position(h,p)
                raised=[e for e in events if e['event']=='main_protection_raised']
                self.assertEqual(bool(raised),i==11)
        self.assertEqual(raised[0]['formed'],'20260127');self.assertEqual(raised[0]['confirmed'],'20260201')
        self.assertEqual(raised[0]['source'],'profit_activated_larger_daily_low')

    def test_larger_window_rejects_a_small_pivot_with_lower_nearby_low(self):
        s,p,h=self.setup_case(LargerProfitStructureIHS)
        lows=[10,12,11.4,12,12,12,11.5,12,12,12,12,12]
        with patch.object(PressureSupportIHS,'manage_position',side_effect=lambda *args:([],[])):
            for i,low in enumerate(lows):
                d=(date(2026,1,21)+timedelta(days=i)).strftime('%Y%m%d');h.append(Bar('X',d,low+.2,low+1.5,low,low+1.2,100))
                _,events=s.manage_position(h,p)
        self.assertFalse([e for e in events if e['event']=='main_protection_raised'])

    def test_half_profit_fee_activation_peak_and_no_lowering(self):
        s,p,h=self.setup_case(HalfProfitRetentionIHS)
        with patch.object(PressureSupportIHS,'manage_position',side_effect=lambda *args:([],[])):
            for d,close in [('20260121',11),('20260122',12),('20260123',11.5),('20260124',14)]:
                h.append(Bar('X',d,close,close+.2,close-.2,close,100));_,events=s.manage_position(h,p)
                if d=='20260121':self.assertFalse(events) # 100 gross, 95 after entry fee <1R
                if d=='20260122':self.assertAlmostEqual(s.managers['seed'].protection,11.025)
                if d=='20260123':self.assertFalse(events);self.assertAlmostEqual(s.managers['seed'].protection,11.025)
        self.assertAlmostEqual(s.managers['seed'].protection,12.025)
        self.assertEqual(events[-1]['peak_marked_profit'],395)
        self.assertEqual(events[-1]['effective'],'next_session')

    def test_half_profit_invariant_across_factor_change(self):
        s,p,h=self.setup_case(HalfProfitRetentionIHS)
        with patch.object(PressureSupportIHS,'manage_position',side_effect=lambda *args:([],[])):
            h.append(Bar('X','20260121',12,12,12,12,100));s.manage_position(h,p)
            adjusted=replace(p,entry=5,quantity=200,stop=4.5,factor=2)
            h.append(Bar('X','20260122',6,6,6,6,100,factor=2));_,events=s.manage_position(h,adjusted)
            self.assertFalse(events);self.assertAlmostEqual(s.managers['seed'].protection,11.025)
            h.append(Bar('X','20260123',7,7,7,7,100,factor=2));_,events=s.manage_position(h,adjusted)
            self.assertAlmostEqual(events[-1]['new'],12.025)

    def test_original_exit_precedence_and_next_day_support_breach(self):
        s,p,h=self.setup_case(HalfProfitRetentionIHS)
        h.append(Bar('X','20260121',12,12,12,12,100))
        original=ExitIntent('test','X','20260121','seed','original')
        with patch.object(PressureSupportIHS,'manage_position',return_value=([original],[])):
            self.assertEqual(s.manage_position(h,p),([original],[]));self.assertFalse(s.profit_activation)
        with patch.object(PressureSupportIHS,'manage_position',side_effect=lambda *args:([],[])):s.manage_position(h,p)
        h.append(Bar('X','20260122',11,11.2,10.7,11,100))
        exits,events=s.managers['seed'].manage(h,p)
        self.assertEqual(exits[0].date,'20260122');self.assertEqual(events[0]['execution'],'next_executable_open')

if __name__=='__main__':unittest.main()
