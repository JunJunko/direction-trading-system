import unittest,sys
from pathlib import Path
from datetime import date,timedelta
from trading_system.domain import Bar,Position
from trading_system.main_trend import completed_weeks,confirmed_sequences,MainTrend
class Tests(unittest.TestCase):
 def setUp(self):
  self.bars=[];self.cal=[];self.ends=[]
  for w in range(16):
   high={2:20,8:25}.get(w,15);low={5:5,11:8}.get(w,10)
   for j in range(5):
    d=(date(2025,1,6)+timedelta(days=7*w+j)).strftime('%Y%m%d');self.cal.append(d);self.bars.append(Bar('X',d,12,high,low,12,100,1))
   self.ends.append(d)
  self.p=Position('x','X',self.cal[35],12,100,3,900,5,'id',1,{})
 def test_two_right_weeks_required(self):
  self.assertFalse(confirmed_sequences(completed_weeks(self.bars[:65],self.cal)))
  seq=confirmed_sequences(completed_weeks(self.bars[:70],self.cal));self.assertEqual(seq[-1]['price'],8);self.assertEqual(seq[-1]['confirmed'],self.ends[13])
 def test_partial_week_not_used(self):
  self.assertEqual(len(completed_weeks(self.bars[:69],self.cal)),13)
 def test_future_tail_does_not_change_confirmed_prefix(self):
  a=confirmed_sequences(completed_weeks(self.bars[:70],self.cal));self.bars[-1]=Bar('X',self.cal[-1],12,100,1,12,100)
  self.assertEqual(a,confirmed_sequences(completed_weeks(self.bars[:70],self.cal)))
 def test_initial_stop_and_no_target(self):
  m=MainTrend('x',self.cal,self.ends);ex,ev=m.manage(self.bars[:70],self.p);self.assertFalse(ex);self.assertEqual(m.protection,8);self.assertEqual(self.p.stop,3)
 def test_week_close_exit_not_intraday(self):
  m=MainTrend('x',self.cal,self.ends);m.protection=8
  bs=self.bars[:71];bs[-1]=Bar('X',bs[-1].date,9,12,6,7,100)
  self.assertFalse(m.manage(bs,self.p)[0]);bs=self.bars[:75];bs[-1]=Bar('X',bs[-1].date,9,12,6,7,100)
  self.assertEqual(m.manage(bs,self.p)[0][0].reason,'weekly_main_trend_break')
 def test_factor_invariance(self):
  m=MainTrend('x',self.cal,self.ends);m.protection=8;bs=self.bars[:75];bs=[Bar(b.symbol,b.date,b.open/2,b.high/2,b.low/2,b.close/2,b.volume,2) for b in bs];self.p.stop=1.5;self.p.factor=2
  self.assertFalse(m.manage(bs,self.p)[0]);self.assertEqual(m.protection,8)
if __name__=='__main__':unittest.main(verbosity=2)

