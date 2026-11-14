import unittest
from dataclasses import replace
from types import SimpleNamespace
import test_breakout_trend_ihs as fixtures
from trading_system.domain import Bar
from trading_system.engine import Backtest
from trading_system.strategies.qualified_candidate_ihs import QualifiedCandidateIHS


class QualifiedCandidateTests(unittest.TestCase):
    def strategy(self, **params):
        return QualifiedCandidateIHS('v5', params)

    def test_relative_scale_and_minimum_shoulder_are_independent(self):
        s=self.strategy()
        for legs,expected in [([3,30,30,3],True),([2,4,4,3],False),
                              ([3,300,300,3],False),([50,400,400,50],True)]:
            self.assertEqual(s.qualification({'candidate_leg_sessions':legs})['shape_qualified'],expected)

    def test_filter_before_ranking_and_keep_rejection_audit(self):
        s=self.strategy();i=fixtures.BreakoutTests().intent()
        def item(pid,legs,area):
            return replace(i,setup_id=pid,evidence=dict(i.evidence,candidate_leg_sessions=legs,
                candidate_area=area,ihs_right_date='20250113',candidate_time_balance=min(legs)/max(legs)))
        output,events=s.choose_intents([item('large',[1,200,200,2],1000),item('small',[3,10,10,3],10)],Bar('X',i.date,10,11,9,10,100))
        self.assertEqual([v.setup_id for v in output],['small'])
        self.assertEqual(s.seen,{'large','small'})
        self.assertTrue(any(e['event']=='candidate_qualification' and not e['shape_qualified'] for e in events))

    def test_market_failure_propagates_across_anchors_and_dates_not_heads(self):
        s=self.strategy();i=fixtures.BreakoutTests().intent()
        s.on_entry_result(i,'20250116','execution','ihs_breakout_lost_at_entry')
        later=replace(i,date='20250120',setup_id='new_anchors')
        self.assertEqual(s.entry_block(later,'20250120','signal')['risk_reason'],'ihs_bottom_invalidated')
        newhead=replace(later,evidence=dict(later.evidence,ihs_head_date='20250118'))
        self.assertIsNone(s.entry_block(newhead,'20250120','signal'))

    def test_budget_is_not_failure_and_rr_is_only_cohort_veto(self):
        s=self.strategy();i=fixtures.BreakoutTests().intent()
        for reason in ('max_positions','insufficient_budget_or_cash','symbol_already_owned','expired_suspended'):
            s.on_entry_result(i,i.date,'signal',reason)
            self.assertIsNone(s.entry_block(i,i.date,'signal'))
        s.on_entry_result(i,i.date,'signal','net_rr_not_above_threshold')
        self.assertEqual(s.entry_block(replace(i,setup_id='alternate'),i.date,'signal')['risk_reason'],'ihs_bottom_cohort_veto')
        self.assertIsNone(s.entry_block(replace(i,date='20250120'),'20250120','signal'))

    def test_preview_assessment_does_not_mutate_failure_state(self):
        f=fixtures.BreakoutTests();s=self.strategy();e=Backtest(f.config(),[s]);i=f.intent()
        e.assess_entry(i,9.95,1e6,1e6,{},'20250116',phase='execution')
        self.assertFalse(s.failed_bottoms)

    def test_actual_open_failure_blocks_otherwise_valid_fallback(self):
        f=fixtures.BreakoutTests();good=f.intent()
        # A different neckline for the same head: first loses breakout at the open.
        ev=dict(good.evidence,ihs_peak1_price=10.1,ihs_peak2_price=10.1,
                ihs_neckline=10.1,ihs_head_neckline=10.1,ihs_target=12.2)
        leader=replace(good,setup_id='leader',target=12.2,evidence=ev)
        for propagate,count in [(False,1),(True,0)]:
            s=self.strategy(propagate_bottom_failure=propagate);e=Backtest(f.config(),[s])
            e.pending=[leader,replace(good,setup_id='fallback')]
            b=Bar('X','20250116',10.05,10.2,10,10.1,100)
            e.execute_interval({'X':b},b.date,None,e.cash)
            self.assertEqual(len(e.positions),count)
            self.assertFalse(e.pending)
            if propagate:self.assertEqual(e.entry_audits[-1]['execution_reason'],'ihs_bottom_invalidated')

    def test_intraday_protection_cannot_veto_earlier_open(self):
        f=fixtures.BreakoutTests();s=self.strategy();i=f.intent()
        p=SimpleNamespace(symbol=i.symbol,setup_id=i.setup_id,plan=i.evidence)
        s.on_protection_failure(p,'20250116')
        self.assertIsNone(s.entry_block(i,'20250116','execution'))
        self.assertIsNotNone(s.entry_block(i,'20250116','signal'))
        self.assertIsNotNone(s.entry_block(i,'20250117','execution'))

    def test_unused_alternative_cannot_invalidate_filled_leader(self):
        f=fixtures.BreakoutTests();good=f.intent();s=self.strategy();e=Backtest(f.config(),[s])
        ev=dict(good.evidence,ihs_peak1_price=10.1,ihs_peak2_price=10.1,
                ihs_neckline=10.1,ihs_head_neckline=10.1,ihs_target=12.2)
        unused=replace(good,setup_id='unused',target=12.2,evidence=ev)
        e.pending=[good,unused];b=Bar('X','20250116',10.05,10.2,10,10.1,100)
        e.execute_interval({'X':b},b.date,None,e.cash)
        self.assertIn('X',e.positions)
        self.assertFalse(s.failed_bottoms)

    def test_real_t1_failure_notifies_at_close(self):
        f=fixtures.BreakoutTests();s=self.strategy();e=Backtest(f.config(),[s]);i=f.intent()
        e.pending=[i];b=Bar('X','20250116',10.05,10.2,9.7,10,100)
        e.execute_interval({'X':b},b.date,None,e.cash)
        self.assertIn('X',e.positions)
        self.assertEqual(s.failed_bottoms[('X','20250106')]['failure_phase'],'close')
        self.assertIsNone(s.entry_block(i,b.date,'execution'))

    def test_prefix_and_factor_invariance(self):
        bs=fixtures.BreakoutTests().bars()
        def replay(data):
            s=self.strategy(min_shoulder_sessions=0,min_shoulder_ratio=0);out=[]
            for n in range(1,len(data)+1):out.extend(s.on_close(data[:n],set())[0])
            return out
        full=replay(bs);self.assertTrue(full)
        self.assertEqual(replay(bs[:-1]),[i for i in full if i.date<=bs[-2].date])
        scaled=[replace(b,open=b.open/2,high=b.high/2,low=b.low/2,close=b.close/2,factor=2) for b in bs]
        other=replay(scaled)
        self.assertEqual([i.setup_id for i in full],[i.setup_id for i in other])
        self.assertEqual(full[0].evidence['shape_qualified'],other[0].evidence['shape_qualified'])

    def test_invalid_parameters(self):
        for p in [{'min_shoulder_sessions':True},{'min_shoulder_ratio':float('nan')},{'propagate_bottom_failure':1}]:
            with self.assertRaises(ValueError):self.strategy(**p)
