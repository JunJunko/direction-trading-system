import unittest
from study_ihs_keyline_events import forward
class EventTests(unittest.TestCase):
 def setUp(self):
  self.bs=[dict(date=str(i),close=c,high=c+1,low=c-1) for i,c in enumerate([10,9,11,12])];self.ci={str(i):i for i in range(4)}
 def test_event_day_extremes_excluded(self):
  self.bs[0]['high']=1000;self.bs[0]['low']=0
  r=forward(self.bs,0,10,11,2,self.ci)
  self.assertAlmostEqual(r['up'],.2);self.assertAlmostEqual(r['down'],-.2);self.assertEqual(r['reclaim_days'],2)
 def test_missing_future_not_zero_return(self):self.assertIsNone(forward(self.bs,2,10,11,2,self.ci))
 def test_suspension_excludes_horizon(self):
  self.ci['2']=3;self.assertIsNone(forward(self.bs,0,10,11,2,self.ci))
 def test_future_tail_does_not_change_fixed_window(self):
  a=forward(self.bs,0,10,11,2,self.ci);self.bs[3]['close']=999
  self.assertEqual(a,forward(self.bs,0,10,11,2,self.ci))
if __name__=='__main__':unittest.main(verbosity=2)
