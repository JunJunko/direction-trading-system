import copy,json,unittest
from pathlib import Path
from dataclasses import replace
from datetime import date,timedelta
from trading_system.domain import Bar,Intent,Position
from trading_system.strategies.breakout_trend_ihs import BreakoutTrendIHS
from trading_system.ihs_geometry import neckline_at
from trading_system.engine import Backtest
from trading_system.risk import RiskManager
from trading_system.main_trend import MainTrend
from test_enclosing_inverse_head_shoulders import fixture

class BreakoutTests(unittest.TestCase):
 def bars(self,peak2=13.,right=10.):
  values=[30-i*.5 for i in range(20)]
  head=[Bar('X',(date(2025,1,1)+timedelta(days=i)).strftime('%Y%m%d'),v,v+.1,v-.1,v,100) for i,v in enumerate(values)]
  shape=fixture([20,21,10,13,8,peak2,right,14])
  return head+[replace(b,date=(date(2025,1,1)+timedelta(days=20+i)).strftime('%Y%m%d')) for i,b in enumerate(shape)]
 def replay(self,bs):
  s=BreakoutTrendIHS('v5',{});out=[]
  for i in range(1,len(bs)+1):out.extend(s.on_close(bs[:i],set())[0])
  return out
 def test_breakout_without_retest_and_once(self):
  signals=self.replay(self.bars());self.assertEqual(len(signals),1)
  i=signals[0];self.assertEqual(i.evidence['entry_mode'],'ihs_breakout');self.assertNotIn('ihs_retest_date',i.evidence)
  self.assertEqual(i.date,i.evidence['ihs_breakout_date']);self.assertLessEqual(i.evidence['ihs_known_at'],i.date)
 def test_sloped_neckline_target(self):
  for peak in [12.8,13.2]:
   signals=self.replay(self.bars(peak));self.assertTrue(signals)
   i=signals[0];e=i.evidence
   self.assertAlmostEqual(i.target,neckline_at(e,i.date)+neckline_at(e,e['ihs_head_date'])-e['ihs_floor'])
   self.assertNotEqual(neckline_at(e,i.date),neckline_at(e,e['ihs_head_date']))
 def test_right_shoulder_can_be_lower_than_left(self):self.assertTrue(self.replay(self.bars(right=9.8)))
 def test_no_prior_decline_rejected(self):
  bs=self.bars();bs=[replace(b,open=8+i*.3,high=8+i*.3+.1,low=8+i*.3-.1,close=8+i*.3) if i<26 else b for i,b in enumerate(bs)]
  self.assertFalse(self.replay(bs))
 def test_prefix_and_factor_invariance(self):
  bs=self.bars();full=self.replay(bs)
  for n in range(1,len(bs)+1):self.assertEqual(self.replay(bs[:n]),[i for i in full if i.date<=bs[n-1].date])
  # All prices and ATR scale together; future factors cannot alter earlier decisions.
  scaled=[replace(b,open=b.open/2,high=b.high/2,low=b.low/2,close=b.close/2,factor=2) for b in bs]
  i=self.replay(scaled)[0];self.assertAlmostEqual(i.target,full[0].target/2);self.assertAlmostEqual(i.stop,full[0].stop/2)
 def config(self):return json.loads(Path('configs/experiments/inverse_head_shoulders_v5_breakout_trend.json').read_text())
 def intent(self,slope=0):
  e=dict(ihs_risk_version=5,ihs_peak1_date='20250101',ihs_peak2_date='20250111',ihs_peak1_price=10.,ihs_peak2_price=10.+slope,ihs_head_date='20250106',ihs_breakout_date='20250115',ihs_entry_atr=.2,ihs_right_low=9.9,ihs_floor=8.,ihs_stop_buffer_atr=.5,ihs_min_stop_atr=1.,ihs_max_entry_atr=1.,entry_order='next_open',entry_mode='ihs_breakout',rebound_confirmed_at='20250115',support_exit_on_touch=True,factor=1.)
  e.update(ihs_neckline=neckline_at(e,'20250115'),ihs_head_neckline=neckline_at(e,'20250106'))
  e.update(breakout_reference=e['ihs_neckline'],ihs_target=e['ihs_neckline']+e['ihs_head_neckline']-8.)
  return Intent('v5','X','20250115',10.05,9.8,e['ihs_target'],'id','inverse_head_shoulders',e)
 def engine(self):
  c=self.config();c['automatic_account_policy']={**c['automatic_account_policy']}
  return Backtest(c,[BreakoutTrendIHS('v5',{})])
 def test_gap_chase_rejected_next_open(self):
  for op,reason in [(10.05,'filled'),(10.3,'ihs_breakout_entry_too_far'),(9.95,'ihs_breakout_lost_at_entry')]:
   e=self.engine();e.pending=[self.intent()];b=Bar('X','20250116',op,op+.1,op-.05,op,100)
   e.execute_interval({'X':b},b.date,None,e.cash)
   self.assertEqual(e.entry_audits[-1]['execution_reason'],reason)
   self.assertEqual(e.entry_audits[-1]['decision'],'BUY_ALLOWED' if reason=='filled' else 'NO_TRADE')
 def test_execution_neckline_uses_actual_date(self):
  e=self.engine();i=self.intent(.1)
  a=e.assess_entry(i,10.3,1e6,1e6,{},'20250120')
  self.assertAlmostEqual(a['execution_neckline'],10.19)
 def test_inflated_target_and_tightened_stop_rejected(self):
  e=self.engine();i=self.intent()
  self.assertEqual(e.assess_entry(replace(i,target=100),10.05,1e6,1e6,{},i.date)['risk_reason'],'ihs_target_not_structural')
  self.assertEqual(e.assess_entry(replace(i,stop=9.9),10.05,1e6,1e6,{},i.date)['risk_reason'],'invalid_ihs_structural_stop')
 def test_factor_rebase_anchors_and_atr(self):
  e=self.engine();i=self.intent(.1);e.pending=[i];e.histories['X']=[Bar('X',i.date,10,11,9,10,100)];e.marks['X']=10
  b=Bar('X','20250116',5,5.5,4.5,5,100,2);e.adjust_factors({'X':b},b.date)
  for k in ['ihs_peak1_price','ihs_peak2_price','ihs_entry_atr','ihs_head_neckline']:self.assertAlmostEqual(e.pending[0].evidence[k],i.evidence[k]/2)
 def test_target_does_not_force_sale(self):
  s=BreakoutTrendIHS('v5',{});s.set_trend_calendar(['20250116','20250117'],{'20250117'})
  i=self.intent();p=Position('v5','X','20250116',10.05,100,9.8,30,5,'id',1,dict(i.evidence))
  bs=[Bar('X','20250116',10.05,15,10,14,100),Bar('X','20250117',14,16,13,15,100)]
  self.assertFalse(s.manage_position(bs,p)[0]);self.assertEqual(s.trailing_stop(bs,p),9.8)
 def test_run_initializes_trend_calendar(self):
  e=self.engine();bs=self.bars();cal=[b.date for b in bs]
  e.run(bs,cal,set(cal[4::5]))
  self.assertEqual(e.strategies[0].calendar,cal)
  self.assertTrue(e.entry_audits)
 def test_entry_day_stop_is_deferred_and_gap_executes(self):
  e=self.engine();e.pending=[self.intent()]
  b=Bar('X','20250116',10.05,10.2,9.7,9.9,100)
  e.execute_interval({'X':b},b.date,None,e.cash)
  self.assertIn('X',e.positions);self.assertFalse(e.trades)
  self.assertEqual(e.positions['X'].plan['t1_stop_breached_at'],b.date)
  b=Bar('X','20250117',9.5,9.7,9.4,9.6,100)
  e.execute_interval({'X':b},b.date,None,e.cash)
  self.assertEqual(e.trades[-1]['reason'],'deferred_ihs_trade_protection_break')
  self.assertAlmostEqual(e.trades[-1]['exit'],9.5*.999)
 def test_weekly_close_exit_executes_next_open(self):
  from test_main_trend import Tests
  f=Tests();f.setUp();e=self.engine();s=e.strategies[0]
  s.set_trend_calendar(f.cal,set(f.ends));p=f.p;p.strategy='v5'
  p.plan={'ihs_risk_version':5,'ihs_floor':2,'support_exit_on_touch':True}
  e.positions['X']=p;e.marks['X']=12
  m=MainTrend('v5',f.cal,f.ends);m.protection=8;s.managers[p.setup_id]=m
  bs=f.bars[:75];bs[-1]=replace(bs[-1],open=9,high=12,low=6,close=7)
  exits,_=s.manage_position(bs,p);self.assertEqual(len(exits),1)
  self.assertFalse(e.trades);e.pending_exits=exits
  b=replace(f.bars[75],open=6.5,high=7,low=6,close=6.8)
  e.execute_interval({'X':b},b.date,None,e.cash)
  self.assertEqual(e.trades[-1]['reason'],'weekly_main_trend_break')
  self.assertAlmostEqual(e.trades[-1]['exit'],6.5*.999)
if __name__=='__main__':unittest.main()
