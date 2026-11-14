import unittest,json
from pathlib import Path
from dataclasses import replace
from trading_system.domain import Intent,Position,Bar
from trading_system.risk import RiskManager
from trading_system.strategies.risk_defined_ihs import RiskDefinedIHS
class RiskDefinitionTests(unittest.TestCase):
 def setUp(self):
  self.c=json.loads(Path('configs/experiments/inverse_head_shoulders_v4_risk_defined.json').read_text())
  self.r=RiskManager(self.c['risk'])
 def intent(self,**kw):
  e=dict(ihs_risk_version=4,ihs_entry_atr=.1,ihs_min_stop_atr=1.,ihs_stop_buffer_atr=.25,ihs_right_low=9.875,ihs_neckline=10.,ihs_floor=8.)
  e.update(kw);return Intent('v4','X','20260101',10.,e['ihs_right_low']-.25*e['ihs_entry_atr'],2*e['ihs_neckline']-e['ihs_floor'],'id','inverse_head_shoulders',e)
 def assess(self,i,fill=10.):return self.r.assess(i,fill,1000000,1000000,{}, {},.0003,.0005,slippage=.001)
 def test_valid_risk(self):self.assertEqual(self.assess(self.intent())['risk_reason'],'approved')
 def test_wide_structural_stop_sized_by_account_budget(self):
  i=self.intent(ihs_right_low=8.8,ihs_floor=1.)
  result=self.assess(i)
  self.assertEqual(result['risk_reason'],'approved')
  self.assertLessEqual(result['expected_loss'],result['risk_budget'])
  self.assertLess(result['quantity'],self.assess(self.intent())['quantity'])
 def test_too_tight_for_noise(self):
  self.assertEqual(self.assess(self.intent(ihs_entry_atr=.4,ihs_right_low=9.95))['risk_reason'],'ihs_stop_inside_noise')
 def test_inflated_target_rejected(self):self.assertEqual(self.assess(replace(self.intent(),target=100.))['risk_reason'],'ihs_target_not_structural')
 def test_actual_gap_fill_rechecks_net_rr(self):self.assertEqual(self.assess(self.intent(),11.)['risk_reason'],'net_rr_not_above_threshold')
 def test_600063_not_rejected_for_price_distance(self):
  i=self.intent(ihs_entry_atr=.29,ihs_right_low=5.41,ihs_neckline=6.19,ihs_floor=3.02477275172117)
  result=self.assess(i,6.29629)
  self.assertEqual(result['risk_reason'],'approved')
  self.assertLessEqual(result['expected_loss'],result['risk_budget'])
 def test_reclaim_timeout_and_recovery(self):
  s=RiskDefinedIHS('v4',{});p=Position('v4','X','20260101',10,100,9,100,5,'id',1,dict(ihs_neckline=10,ihs_target=12,ihs_reclaim_sessions=3))
  bs=[Bar('X','2026010'+str(j),9.9,10,9.8,9.9,100) for j in range(1,4)]
  self.assertFalse(s.manage_position(bs[:2],p)[0]);self.assertEqual(s.manage_position(bs,p)[0][0].reason,'ihs_neckline_not_reclaimed')
  bs[-1]=replace(bs[-1],close=10.01);self.assertFalse(s.manage_position(bs,p)[0])
 def test_invalid_parameters(self):
  for params in [dict(reclaim_sessions=True),dict(min_stop_atr=float('nan')),dict(stop_buffer_atr=-1)]:
   with self.assertRaises(ValueError):RiskDefinedIHS('v4',params)
 def test_signal_prefix_and_buffer(self):
  from test_enclosing_inverse_head_shoulders import fixture
  from datetime import datetime,timedelta
  bs=fixture()
  for o,h,l,c in [(13.3,13.4,13.08,13.15),(13.15,13.3,13.1,13.22)]:
   d=(datetime.strptime(bs[-1].date,'%Y%m%d')+timedelta(days=1)).strftime('%Y%m%d');bs.append(Bar('X',d,o,h,l,c,100))
  def replay(n):
   strategy=RiskDefinedIHS('v4',{});return [strategy.on_close(bs[:j],set()) for j in range(1,n+1)]
  full=replay(len(bs))
  for n in range(1,len(bs)+1):self.assertEqual(replay(n),full[:n])
  intents=[i for output,events in full for i in output]
  self.assertTrue(intents)
  for i in intents:self.assertAlmostEqual(i.stop,i.evidence['ihs_right_low']-.25*i.evidence['ihs_entry_atr'])
if __name__=='__main__':unittest.main()
