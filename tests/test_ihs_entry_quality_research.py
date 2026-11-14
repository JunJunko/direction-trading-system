import unittest
from dataclasses import replace
from trading_system.domain import Bar,Intent
from trading_system.ihs_entry_quality_research import entry_features,extra_pass,IHSEntryQualityBacktest

class IHSEntryQualityTests(unittest.TestCase):
    def setUp(self):
        self.h=[Bar('X',f'202601{i+1:02d}',10,11,9,10,100) for i in range(30)]
        self.i=Intent('test','X','20260130',10,9,13,'root','inverse_head_shoulders',{})

    def test_current_bar_extremes_and_future_volume_do_not_leak(self):
        a=entry_features(self.i,self.h,'20260131',1,10)
        b=entry_features(self.i,self.h+[Bar('X','20260131',10,500,.1,400,100000)],'20260131',1,10)
        self.assertEqual(a,b)
        for k in ('signal_known_at','atr_known_at'):self.assertLess(a[k],'20260131')

    def test_volume_average_excludes_signal_and_rules_include_boundaries(self):
        f=entry_features(self.i,self.h,'20260131',1,9)
        for rule in ('solid_close','volume_confirmed','rising_ma20','limited_gap_down'):
            self.assertTrue(extra_pass(rule,f),rule)
        h=self.h[:-1]+[replace(self.h[-1],volume=200)]
        self.assertEqual(entry_features(self.i,h,'20260131',1,10)['volume_ratio'],2)
        self.assertFalse(extra_pass('limited_gap_down',entry_features(self.i,self.h,'20260131',1,8.9)))

    def test_factor_adjustment_keeps_price_features_consistent(self):
        a=entry_features(self.i,self.h,'20260131',1,9.5)
        b=entry_features(self.i,self.h,'20260131',2,4.75)
        self.assertEqual(a,b)
        h=[replace(x,open=x.open/2,high=x.high/2,low=x.low/2,close=x.close/2,factor=2) for x in self.h]
        self.assertEqual(a,entry_features(self.i,h,'20260131',2,4.75))

    def test_negative_features_and_missing_history_fail(self):
        f=entry_features(self.i,self.h,'20260131',1,10)
        for rule,key,value in [('solid_close','close_location',.49),('volume_confirmed','volume_ratio',.99),('rising_ma20','ma20_change',-.001),('limited_gap_down','gap_atr',-.51)]:
            self.assertFalse(extra_pass(rule,dict(f,**{key:value})))
            self.assertFalse(extra_pass(rule,None))
        self.assertIsNone(entry_features(self.i,self.h[:12],'20260131',1,10))

    def test_wrong_base_is_rejected(self):
        with self.assertRaises(ValueError):IHSEntryQualityBacktest({},[])
