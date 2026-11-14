import unittest
from dataclasses import replace
from unittest.mock import patch
from datetime import date,timedelta
from trading_system.domain import Bar,Intent,Position
from trading_system.strategies.ihs_price_line_research import RetestConfirmedIHS,BreakoutFailureIHS,ProfitActivatedIHS,scaled_seed
from trading_system.strategies.pressure_support_ihs import PressureSupportIHS
from trading_system.pressure_support_trend import PressureSupportTrend

class IHSLifecycleTests(unittest.TestCase):
    def seed(self):
        e=dict(factor=1,ihs_neckline=10,ihs_head_neckline=10,ihs_floor=7,ihs_target=13,ihs_right_low=9,ihs_entry_atr=.4,
               ihs_peak1_price=10,ihs_peak2_price=10,ihs_peak1_date='20250101',ihs_peak2_date='20250201',breakout_reference=10,ihs_breakout_date='20260101',entry_order='next_open')
        return Intent('test','X','20260101',10.2,8.8,13,'seed','inverse_head_shoulders',e)

    def test_retest_needs_later_confirmation_and_keeps_original_bracket(self):
        s=RetestConfirmedIHS('test',{});seed=self.seed();h=[Bar('X','20260101',10,10.3,9.9,10.2,100)]
        self.assertEqual(s.retest_on_close(h,[seed])[0],[])
        h.append(Bar('X','20260102',10.1,10.4,10,10.3,100))
        self.assertEqual(s.retest_on_close(h,[])[0],[])
        h.append(Bar('X','20260103',10.2,10.6,10.1,10.5,100))
        intents,_=s.retest_on_close(h,[]);self.assertEqual(len(intents),1)
        i=intents[0];self.assertEqual((i.stop,i.target),(8.8,13));self.assertEqual(i.date,'20260103')
        self.assertEqual(i.evidence['retest_touch_date'],'20260102');self.assertEqual(i.evidence['ihs_breakout_date'],'20260101')
        self.assertEqual(s.retest_on_close(h,[seed])[0],[])

    def test_retest_invalidation_and_expiry(self):
        for bar,reason in [(Bar('X','20260102',10,10.3,8.9,10.2,100),'right_shoulder_broken'),(Bar('X','20260102',10,13,9.9,10.2,100),'original_target_touched')]:
            s=RetestConfirmedIHS('test',{});h=[Bar('X','20260101',10,10.3,9.9,10.2,100)]
            s.retest_on_close(h,[self.seed()]);i,e=s.retest_on_close(h+[bar],[])
            self.assertFalse(i);self.assertEqual(e[-1]['reason'],reason)
        s=RetestConfirmedIHS('test',{});h=[Bar('X',f'202601{i:02d}',10.3,10.5,10.2,10.3,100) for i in range(1,13)]
        s.retest_on_close(h[:1],[self.seed()]);i,e=s.retest_on_close(h,[])
        self.assertFalse(i);self.assertEqual(e[-1]['reason'],'expired_10_stock_bars')

    def test_retest_factor_scales_all_price_fields_without_mutation(self):
        seed=self.seed();other=scaled_seed(seed,2)
        self.assertEqual((other.stop,other.target,other.evidence['ihs_entry_atr']),(4.4,6.5,.2))
        self.assertEqual(seed.evidence['ihs_peak1_price'],10)

    def position(self):
        return Position('test','X','20260121',10,100,9,100,0,'seed',1,dict(self.seed().evidence),10)

    def history(self):
        return [Bar('X',(date(2026,1,1)+timedelta(days=i)).strftime('%Y%m%d'),10,10.2,9.8,10,100) for i in range(20)]

    def test_failure_requires_two_buffered_closes_and_queues_once(self):
        s=BreakoutFailureIHS('test',{});p=self.position();h=self.history()+[Bar('X','20260121',10,10.1,9.5,9.6,100)]
        with patch.object(PressureSupportIHS,'manage_position',side_effect=lambda *args:([],[])):
            self.assertEqual(s.manage_position(h,p)[0],[])
            h.append(Bar('X','20260122',9.6,9.8,9.4,9.5,100));ex,ev=s.manage_position(h,p)
            self.assertEqual(len(ex),1);self.assertEqual(ex[0].date,'20260122')
            self.assertEqual(ev[-1]['execution'],'next_executable_open')
            self.assertEqual(s.manage_position(h,p),([],[]))

    def test_single_deep_failure_or_unbuffered_break_is_not_enough(self):
        s=BreakoutFailureIHS('test',{});p=self.position();h=self.history()+[Bar('X','20260121',10,10.1,9.8,9.95,100),Bar('X','20260122',9.8,9.9,9.4,9.5,100)]
        with patch.object(PressureSupportIHS,'manage_position',side_effect=lambda *args:([],[])):
            self.assertFalse(s.manage_position(h,p)[0])

    def test_profit_activation_then_pivot_right_confirmation(self):
        s=ProfitActivatedIHS('test',{});p=self.position();s.managers['seed']=PressureSupportTrend('test',[],set())
        h=self.history()+[Bar('X',f'202601{i+21:02d}',low+.1,low+1.3,low,low+1,100) for i,low in enumerate([10,11.1,11.2,10.8,11.3,11.4])]
        with patch.object(PressureSupportIHS,'manage_position',side_effect=lambda *args:([],[])):
            _,events=s.manage_position(h[:21],p)
            self.assertEqual(events[0]['event'],'profit_protection_activated')
            self.assertFalse(s.manage_position(h[:-1],p)[1])
            _,events=s.manage_position(h,p)
        self.assertEqual(len(events),1);e=events[0]
        self.assertEqual(e['formed'],'20260124');self.assertEqual(e['confirmed'],'20260126');self.assertEqual(e['activation_date'],'20260121')
        self.assertEqual(e['effective'],'next_session');self.assertGreater(e['new'],9);self.assertLess(e['new'],10.8)

    def test_pivot_before_activation_cannot_be_used_retroactively(self):
        s=ProfitActivatedIHS('test',{});p=replace(self.position(),initial_risk=1000);s.managers['seed']=PressureSupportTrend('test',[],set())
        h=self.history()+[Bar('X',f'202601{i+21:02d}',low+.1,low+.3,low,low+.2,100) for i,low in enumerate([10,11.1,11.2,10.8,11.3,11.4])]
        with patch.object(PressureSupportIHS,'manage_position',side_effect=lambda *args:([],[])):
            self.assertFalse(s.manage_position(h,p)[1])
            s.profit_activation['seed']='20260125'
            self.assertFalse(s.manage_position(h,p)[1])
