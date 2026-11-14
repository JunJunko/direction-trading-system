import copy,json,unittest
from pathlib import Path
from dataclasses import replace
from trading_system.engine import Backtest
from trading_system.domain import Bar,Position,ExitIntent
from trading_system.matched_cycle_exit import MatchedCycleExit


class ExecutionOrderTests(unittest.TestCase):
    def engine(self,order='open_first'):
        cfg=json.loads(Path('configs/experiments/double_bottom_ihs_v7_pressure_support.json').read_text())
        cfg['execution']['daily_exit_order']=order
        e=Backtest(cfg,[])
        p=Position('x','X','20260101',12,100,10,200,5,'id',1,{'support_exit_on_touch':True})
        e.positions['X']=p;e.marks['X']=12
        e.pending_exits=[ExitIntent('x','X','20260102','id','close_break')]
        return e

    def test_existing_open_order_precedes_later_stop(self):
        b=Bar('X','20260103',15,16,9,12,100)
        e=self.engine();e.execute_interval({'X':b},b.date,None,e.cash)
        self.assertAlmostEqual(e.trades[0]['exit'],14.985)
        self.assertEqual(e.trades[0]['reason'],'close_break')
        e=self.engine('legacy_stop_first');e.execute_interval({'X':b},b.date,None,e.cash)
        self.assertEqual(e.trades[0]['reason'],'support_break')

    def test_future_low_cannot_change_open_fill(self):
        fills=[]
        for low in (9,14.999):
            e=self.engine();b=Bar('X','20260103',15,16,low,15,100)
            e.execute_interval({'X':b},b.date,None,e.cash);fills.append(e.trades[0]['exit'])
        self.assertEqual(fills[0],fills[1])

    def test_limit_open_blocks_even_if_later_unlocks(self):
        e=self.engine();b=Bar('X','20260103',9,13,9,12,100,1,15,9)
        e.execute_interval({'X':b},b.date,None,e.cash)
        self.assertFalse(e.trades);self.assertEqual(len(e.pending_exits),1)
        b=replace(b,date='20260104',open=11)
        e.execute_interval({'X':b},b.date,None,e.cash)
        self.assertEqual(e.trades[0]['reason'],'close_break')

    def test_t1_and_signal_timing(self):
        for date in ('20260101','20260102'):
            e=self.engine();b=Bar('X',date,13,14,9,12,100)
            e.execute_interval({'X':b},date,None,e.cash)
            self.assertFalse(e.trades);self.assertTrue(e.pending_exits)

    def test_suspension_and_gap(self):
        e=self.engine();b=Bar('X','20260103',8,9,7,8,0)
        e.execute_interval({'X':b},b.date,None,e.cash);self.assertFalse(e.trades)
        b=replace(b,date='20260104',volume=100)
        e.execute_interval({'X':b},b.date,None,e.cash)
        self.assertAlmostEqual(e.trades[0]['exit'],7.992)


class MatchedTests(unittest.TestCase):
    def setUp(self):
        self.cal=[f'202601{i:02}' for i in range(1,32)]
        self.p=Position('x','X',self.cal[15],10,100,7,300,5,'id',1)
        self.bs=[Bar('X',d,10,11,9,10,100) for d in self.cal]
        self.bs[15]=replace(self.bs[15],high=12,low=10,close=11)
        self.bs[16]=replace(self.bs[16],high=11.5,low=9,close=10)
        self.bs[17]=replace(self.bs[17],high=11,low=9.5,close=10)
        self.bs[18]=replace(self.bs[18],high=15,low=8,close=14)

    def replay(self,m,end):
        for n in range(16,end+1):m.manage(self.bs[:n],self.p)

    def manager(self,expansion=False):
        m=MatchedCycleExit('x',self.cal,[],expansion_exit=expansion);m.initialized=True
        return m

    def test_resumption_uses_only_prior_low(self):
        m=self.manager();self.replay(m,18);self.assertIsNone(m.protection)
        ex,ev=m.manage(self.bs[:19],self.p)
        self.assertFalse(ex);self.assertEqual(m.protection,9)
        self.assertEqual(m.reference['duration'],2)
        self.assertEqual(self.p.stop,7)

    def test_small_correction_does_not_promote(self):
        self.bs[17]=replace(self.bs[17],close=14,high=15)
        m=self.manager();self.replay(m,18);self.assertIsNone(m.protection)
        self.assertEqual(m.anchor,15)

    def test_expansion_requires_prior_matched_reference(self):
        m=self.manager(True);self.replay(m,19)
        self.bs[19]=replace(self.bs[19],high=14,low=10,close=11)
        self.bs[20]=replace(self.bs[20],high=13,low=10,close=11)
        self.assertFalse(m.manage(self.bs[:20],self.p)[0])
        self.assertEqual(m.manage(self.bs[:21],self.p)[0][0].reason,'matched_correction_expanded')
        self.assertFalse(m.manage(self.bs[:21],self.p)[0])

    def test_gap_resets_matching_not_existing_support(self):
        m=self.manager();self.replay(m,19)
        bs=self.bs[:19]+[replace(self.bs[21],close=11)]
        m.manage(bs,self.p);self.assertIsNone(m.reference);self.assertEqual(m.protection,9)

    def test_factor_invariance(self):
        a=self.manager();self.replay(a,19)
        self.bs=[replace(b,open=b.open/2,high=b.high/2,low=b.low/2,close=b.close/2,factor=2) for b in self.bs]
        self.p.entry/=2;self.p.stop/=2;self.p.factor=2
        b=self.manager();self.replay(b,19)
        self.assertEqual(a.protection,b.protection);self.assertEqual(a.reference,b.reference)

    def test_registered_adapters_and_frozen_entry_parameters(self):
        from trading_system.strategies import build_strategies
        original=json.loads(Path('configs/experiments/double_bottom_ihs_v7_pressure_support.json').read_text())
        for suffix in ('','_expansion'):
            cfg=json.loads(Path('configs/experiments/double_bottom_ihs_v9_matched'+suffix+'.json').read_text())
            for a,b in zip(original['strategies'],cfg['strategies']):
                self.assertEqual(a['params'],{k:v for k,v in b['params'].items() if k!='expansion_exit'})
            for s in build_strategies(cfg['strategies']):
                s.set_trend_calendar(self.cal,[]);p=replace(self.p,strategy=s.name,plan={})
                s.manage_position(self.bs[:16],p)
                self.assertIsInstance(s.managers[p.setup_id],MatchedCycleExit)
                self.assertEqual(s.managers[p.setup_id].expansion_exit,bool(suffix))

if __name__=='__main__':unittest.main()
