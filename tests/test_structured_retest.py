import sys,unittest
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.structure import structured_retest

class StructuredRetestTests(unittest.TestCase):
 def bars(self,closes=(11.5,13.8,13.4,13.1,12.8,13.7)):
  return [Bar('X',f'202401{i+1:02d}',c-.1,c+.2,c-.3,c,100) for i,c in enumerate(closes)]
 def pending(self):return dict(breakout_index=0,second=0,bottom=5,neckline=10)
 def test_sloping_adjustment_and_recovery(self):
  bars=self.bars();c,o=structured_retest(bars,self.pending())
  self.assertEqual(c['kind'],'sloping');self.assertEqual(c['peak_date'],'20240102')
  self.assertEqual(c['trough_date'],'20240105');self.assertEqual(c['correction_duration'],3)
 def test_no_confirmation_before_recovery(self):
  bars=self.bars()
  for i in range(1,len(bars)):
   self.assertIsNone(structured_retest(bars[:i],self.pending())[0])
 def test_single_pause_during_rising_trend_is_not_retest(self):
  bars=self.bars((11.5,13.8,13.4,13.5,13.6,13.9))
  self.assertIsNone(structured_retest(bars,self.pending())[0])
 def test_horizontal_retest_above_neckline(self):
  bars=self.bars((11.5,13.8,13.4,13.1,13.3,13.5))
  bars[-2]=replace(bars[-2],high=13.9)
  c,_=structured_retest(bars,self.pending())
  self.assertEqual(c['kind'],'horizontal');self.assertGreater(c['floor'],10)
  self.assertLess(bars[-1].close,max(b.high for b in bars[2:-1]))
 def test_new_peak_resets_correction_interval(self):
  bars=self.bars();bars[3]=replace(bars[3],high=14.5)
  c,o=structured_retest(bars,self.pending())
  self.assertIsNone(c);self.assertEqual(o['peak_date'],bars[3].date)
 def test_broken_trough_is_not_recovery(self):
  bars=self.bars();bars[-1]=replace(bars[-1],low=12.0)
  self.assertIsNone(structured_retest(bars,self.pending())[0])
 def test_excessive_adjustment_is_rejected(self):
  bars=self.bars();bars[3]=replace(bars[3],low=4)
  self.assertIsNone(structured_retest(bars,self.pending())[0])

class RetestDeadlineTests(unittest.TestCase):
 def test_new_high_does_not_extend_candidate_deadline(self):
  bars=StructuredRetestTests().bars((11.5,12,13,14,15,16))
  c,o=structured_retest(bars,dict(breakout_index=0,second=0,bottom=5,neckline=10),maximum=4)
  self.assertIsNone(c);self.assertEqual(o['reason'],'retest_expired')

if __name__=='__main__':unittest.main()
