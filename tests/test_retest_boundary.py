import sys
import unittest
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.structure import structured_retest


class BoundaryRecoveryTests(unittest.TestCase):
    def bars(self,closes):
        return [Bar('X',f'202401{i+1:02d}',c-.1,c+.2,c-.3,c,100)
                for i,c in enumerate(closes)]

    def pending(self):
        return dict(breakout_index=0,second=0,bottom=5,neckline=10)

    def test_small_rebound_after_decline_does_not_confirm_boundary(self):
        bars=self.bars([11.5,15,14,13,12,12.5])
        self.assertIsNotNone(structured_retest(bars,self.pending())[0])
        result,observed=structured_retest(bars,self.pending(),recovery_mode='boundary')
        self.assertIsNone(result)
        self.assertEqual(observed['reason'],'adjustment_boundary_not_recovered')

    def test_boundary_recovery_confirms_without_peak_recovery(self):
        bars=self.bars([11.5,15,14,13,12,14.5])
        result,_=structured_retest(bars,self.pending(),recovery_mode='boundary')
        self.assertEqual(result['kind'],'sloping')
        self.assertLess(bars[-1].close,bars[1].high)
        for end in range(1,len(bars)):
            self.assertIsNone(structured_retest(bars[:end],self.pending(),recovery_mode='boundary')[0])

    def test_horizontal_midpoint_is_not_boundary_breakout(self):
        bars=self.bars([11.5,13.8,13.4,13.1,13.3,13.35])
        bars[-2]=replace(bars[-2],high=13.9)
        self.assertIsNotNone(structured_retest(bars,self.pending())[0])
        self.assertIsNone(structured_retest(bars,self.pending(),recovery_mode='boundary')[0])
        bars[-1]=replace(bars[-1],close=13.5,high=13.7)
        self.assertEqual(structured_retest(bars,self.pending(),recovery_mode='boundary')[0]['kind'],'horizontal')

    def test_invalid_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            structured_retest(self.bars([11,12]),self.pending(),recovery_mode='unknown')
