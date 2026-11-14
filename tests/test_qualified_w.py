import sys
import unittest
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.strategies.qualified_w_retest import QualifiedWRetest
from trading_system.strategies.w_retest import WRetest


class QualifiedWTests(unittest.TestCase):
    def fixture(self):
        prices=[14-i*.17 for i in range(22)]+[10.2,10.6,11,10.7,10.4,10.6,10.9,11.3]
        bars=[Bar('X',f'202501{i+1:02}',v,v+.1,v-.1,v,100) for i,v in enumerate(prices)]
        return bars,dict(first=22,second=26,neckline=11.1,bottom=10.1,first_breakout_index=29)

    def test_qualifies_with_evidence_before_first_bottom(self):
        bars,w=self.fixture();ok,reason,e=QualifiedWRetest('x',{}).qualify(bars,w)
        self.assertTrue(ok,reason);self.assertLess(e['w_trend_end'],bars[w['first']].date)
        self.assertLess(e['w_prior_slope_pct'],0)

    def test_high_origin_alone_does_not_prove_decline(self):
        bars,w=self.fixture()
        for i in range(22):bars[i]=replace(bars[i],close=10+i*.1)
        self.assertEqual(QualifiedWRetest('x',{}).qualify(bars,w)[1],'prior_downtrend_not_confirmed')

    def test_rebound_requirement(self):
        bars,w=self.fixture();w['neckline']=10.4
        self.assertEqual(QualifiedWRetest('x',{}).qualify(bars,w)[1],'rebound_too_shallow')

    def test_optional_separation_and_volume(self):
        bars,w=self.fixture()
        self.assertEqual(QualifiedWRetest('x',{'min_separation':5}).qualify(bars,w)[1],'bottom_separation')
        self.assertEqual(QualifiedWRetest('x',{'breakout_volume_ratio':1.5}).qualify(bars,w)[1],'breakout_volume_insufficient')
        bars[-1]=replace(bars[-1],volume=200)
        self.assertTrue(QualifiedWRetest('x',{'breakout_volume_ratio':1.5}).qualify(bars,w)[0])

    def test_atr_uses_price_units_and_freezes_at_right_bottom(self):
        bars,w=self.fixture();bars[26]=replace(bars[26],low=10.7,open=10.8,close=10.8)
        for i in range(13,27):bars[i]=replace(bars[i],high=bars[i].high+2)
        s=QualifiedWRetest('x',{'tolerance_mode':'percent_or_atr'})
        ok,reason,e=s.qualify(bars,w);self.assertTrue(ok,reason)
        self.assertEqual(QualifiedWRetest('x',{}).qualify(bars,w)[1],'bottoms_not_close')
        bars[-1]=replace(bars[-1],high=100)
        self.assertEqual(e['w_tolerance_atr_pct'],s.qualify(bars,w)[2]['w_tolerance_atr_pct'])

    def test_structure_close_and_execution_wick_are_distinct(self):
        after=[Bar('X','20250101',10,11,8,10,100)]
        self.assertFalse(QualifiedWRetest('x',{}).structure_broken(after,9))
        self.assertTrue(WRetest('x',{}).structure_broken(after,9))
        self.assertTrue(QualifiedWRetest('x',{}).structure_broken([replace(after[0],close=8.9)],9))

    def test_bad_options(self):
        for p in ({'trend_lookback':True},{'min_rebound':float('nan')},{'tolerance_mode':'atr'},
                  {'max_separation':1},{'min_separation':10,'max_separation':5},{'breakout_volume_ratio':False}):
            with self.assertRaises(ValueError):QualifiedWRetest('x',p)
