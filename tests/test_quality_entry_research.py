import unittest
from dataclasses import replace
from trading_system.domain import Bar,Intent
from trading_system.quality_entry_research import quality_measure


class QualityEntryTests(unittest.TestCase):
    def setUp(self):
        self.bars=[Bar('X',f'202601{i+1:02d}',10,11,9,10,100) for i in range(16)]
        self.intent=Intent('test','X','20260116',10,9,12,'root','direct_w',dict(w_separation_sessions=120,ihs_peak1_date='20260101',ihs_peak2_date='20260110',ihs_peak1_price=10,ihs_peak2_price=10))

    def test_current_day_extremes_cannot_change_decision(self):
        for rule in ('no_gap_up','neck_half_atr'):
            args=(rule,self.intent,self.bars,'20260117',1,10,10.01)
            before=quality_measure(*args)
            future=Bar('X','20260117',10,1000,.01,900,100)
            after=quality_measure(rule,self.intent,self.bars+[future],'20260117',1,10,10.01)
            self.assertEqual(before,after)
            self.assertLess(before[2],'20260117')

    def test_gap_uses_raw_open_and_adjusted_previous_close(self):
        value,passed,_=quality_measure('no_gap_up',self.intent,self.bars,'20260117',2,5,5.005)
        self.assertTrue(passed);self.assertAlmostEqual(value,0)
        self.assertFalse(quality_measure('no_gap_up',self.intent,self.bars,'20260117',2,5.01,5.015)[1])

    def test_strict_neckline_boundary_and_closed_atr(self):
        self.assertFalse(quality_measure('neck_half_atr',self.intent,self.bars,'20260117',1,11,11)[1])
        self.assertTrue(quality_measure('neck_half_atr',self.intent,self.bars,'20260117',1,10.9,10.9)[1])
        self.assertFalse(quality_measure('neck_half_atr',self.intent,self.bars[:4],'20260117',1,10,10)[1])

    def test_span_boundary(self):
        self.assertTrue(quality_measure('span120',self.intent,[],'20260117',1,10,10)[1])
        other=replace(self.intent,evidence=dict(w_separation_sessions=121))
        self.assertFalse(quality_measure('span120',other,[],'20260117',1,10,10)[1])
