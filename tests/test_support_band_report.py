import sys
import unittest
from pathlib import Path
from dataclasses import replace

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from report_support_band import post_stop,audit_plan
from trading_system.domain import Bar
import test_support_band as fixtures


class SupportBandReportTests(unittest.TestCase):
    def fixture(self):
        calendar=[f'2026010{i}' for i in range(1,9)]
        bars=[Bar('X',d,10,10.2,9.8,10,100) for d in calendar]
        trade=dict(symbol='X',setup_id='id',entry_date=calendar[0],exit_date=calendar[1],reason='support_band_break',pnl=-100)
        audit=dict(setup_id='id',execution_reason='filled',support_lower=9.5,fill=10,target=12)
        return calendar,bars,trade,audit

    def run_case(self,calendar,bars,trade,audit,end='20260108'):
        return post_stop([trade],[audit],{'X':bars},calendar,end)

    def test_five_session_recovery_requires_intact_original_support(self):
        c,b,t,a=self.fixture();rows,m=self.run_case(c,b,t,a)
        self.assertEqual(m['complete_5_session_windows'],1)
        self.assertTrue(rows[0]['recovered_entry']);self.assertFalse(rows[0]['reached_target'])
        b[3]=replace(b[3],low=9.5)
        rows,m=self.run_case(c,b,t,a)
        self.assertFalse(rows[0]['recovered_entry']);self.assertFalse(rows[0]['original_floor_intact'])

    def test_incomplete_and_suspended_windows_are_censored(self):
        c,b,t,a=self.fixture();rows,m=self.run_case(c,b,t,a,end='20260105')
        self.assertFalse(rows[0]['complete_5_sessions']);self.assertIsNone(m['recovered_entry_rate'])
        b[4]=replace(b[4],volume=0)
        rows,m=self.run_case(c,b,t,a)
        self.assertEqual(m['incomplete_windows'],1)

    def test_future_factor_normalization_preserves_recovery_classification(self):
        c,b,t,a=self.fixture();before=self.run_case(c,b,t,a)
        b=[bar if i<2 else replace(bar,open=bar.open/2,high=bar.high/2,low=bar.low/2,close=bar.close/2,factor=2) for i,bar in enumerate(b)]
        self.assertEqual(before,self.run_case(c,b,t,a))

    def test_core_trailing_stop_does_not_count_as_initial_band_exit(self):
        c,b,t,a=self.fixture();t['reason']='support_break'
        rows,m=self.run_case(c,b,t,a)
        self.assertEqual(rows,[]);self.assertEqual(m['band_exit_count'],0)

    def test_post_exit_target_is_separate_from_simple_entry_recovery(self):
        c,b,t,a=self.fixture();b[4]=replace(b[4],high=12.1)
        rows,m=self.run_case(c,b,t,a)
        self.assertTrue(rows[0]['reached_target']);self.assertEqual(m['intact_floor_reached_target'],1)

    def test_independent_plan_audit_recomputes_frozen_band(self):
        bars,_=fixtures.example();i=fixtures.signal()
        plan=dict(symbol=i.symbol,date=i.date,setup_id=i.setup_id,stop=i.stop,trigger=i.trigger,target=i.target,evidence=i.evidence)
        result=audit_plan(plan,bars)
        self.assertAlmostEqual(result['defense_lower'],i.stop)
        changed=dict(plan,stop=i.stop+.01)
        with self.assertRaises(AssertionError):audit_plan(changed,bars)


if __name__=='__main__':unittest.main()
