import copy,json,unittest
from dataclasses import replace
from pathlib import Path
from trading_system.profit_structure_trim import ProfitStructureTrim
from trading_system.domain import Bar,Position,ExitIntent
from trading_system.engine import Backtest


class TrimTests(unittest.TestCase):
    def setUp(self):
        self.cfg=json.loads(Path('configs/experiments/double_bottom_ihs_v10_profit_structure_trim.json').read_text())
        self.cal=[f'202601{i:02}' for i in range(1,32)]
        self.bs=[Bar('X',d,10,11,9,10,100) for d in self.cal]
        shapes=[(14,12,13),(13,12,12.5),(12.5,11,12),(11.8,10.5,11),
                (12.1,11,11.5),(12.5,11.5,12),(13,11.6,12.5),(12.2,11.7,12),
                (11.8,11.2,11.5),(11,10.2,10.4)]
        for i,(h,l,c) in enumerate(shapes,15):self.bs[i]=replace(self.bs[i],open=c,high=h,low=l,close=c)
        self.p=Position('x','X',self.cal[15],10,1000,9,1000,5,'id',1,{'support_exit_on_touch':True})

    def manager(self):
        m=ProfitStructureTrim('x',self.cal,[],execution=self.cfg['execution']);m.initialized=True
        return m

    def replay(self,m,end=25):
        result=[]
        for n in range(16,end+1):result.append(m.manage(self.bs[:n],self.p))
        return result

    def test_arm_not_sell_then_one_partial_after_failed_rebound(self):
        m=self.manager();result=self.replay(m)
        self.assertTrue(m.armed);self.assertEqual(m.trough['date'],self.cal[18])
        self.assertEqual(m.rebound['confirmed'],self.cal[23])
        self.assertFalse(any(x[0] for x in result[:-1]))
        self.assertEqual(result[-1][0][0].fraction,1/3)
        self.assertFalse(m.manage(self.bs[:26],self.p)[0]);self.assertEqual(self.p.stop,9)

    def test_intraday_spike_and_gross_2R_cannot_arm(self):
        for close in (11,12):
            m=self.manager();bs=self.bs[:16];bs[-1]=replace(bs[-1],high=30,close=close)
            m.manage(bs,self.p);self.assertFalse(m.armed)

    def test_costs_control_net_activation(self):
        m=self.manager();m.execution['commission_rate']=.02
        bs=self.bs[:16];bs[-1]=replace(bs[-1],close=12.2)
        m.manage(bs,self.p);self.assertFalse(m.armed)

    def test_no_same_day_rebound_confirmation_exit(self):
        self.bs[23]=replace(self.bs[23],close=10.4,low=10.2)
        m=self.manager();result=self.replay(m,24)
        self.assertFalse(result[-1][0])

    def test_new_high_resets_chain(self):
        m=self.manager();self.replay(m,24)
        bs=self.bs[:25];bs[-1]=replace(bs[-1],high=15,close=14)
        self.assertFalse(m.manage(bs,self.p)[0]);self.assertIsNone(m.trough)

    def test_missing_session_resets_chain(self):
        m=self.manager();self.replay(m,24)
        bs=self.bs[:24]+[replace(self.bs[25],close=10.4)]
        self.assertFalse(m.manage(bs,self.p)[0]);self.assertIsNone(m.rebound)

    def test_factor_invariance(self):
        a=self.manager();aresult=self.replay(a)
        self.bs=[replace(b,open=b.open/2,high=b.high/2,low=b.low/2,close=b.close/2,factor=2) for b in self.bs]
        self.p=replace(self.p,entry=5,quantity=2000,stop=4.5,factor=2)
        b=self.manager();bresult=self.replay(b)
        self.assertEqual(aresult[-1][0],bresult[-1][0]);self.assertEqual(a.trough,b.trough)

    def test_small_position_is_not_forced_to_sell_all(self):
        self.p=replace(self.p,quantity=200,initial_risk=200)
        m=self.manager();result=self.replay(m)
        self.assertFalse(result[-1][0]);self.assertTrue(m.trim_requested)
        self.assertEqual(result[-1][1][-1]['event'],'profit_trim_skipped_small_lot')

    def test_core_exit_precedes_trim(self):
        m=self.manager();self.replay(m,24);m.protection=11
        ex,_=m.manage(self.bs[:25],self.p)
        self.assertEqual(ex[0].fraction,1);self.assertEqual(ex[0].reason,'dynamic_support_daily_break')

    def test_partial_settlement_and_trade_level_statistics(self):
        e=Backtest(self.cfg,[]);e.positions['X']=self.p;e.marks['X']=10
        e.queue_exit(ExitIntent('x','X',self.cal[24],'id','profit_structure_trim',1/3))
        b=replace(self.bs[25],open=13,high=14,low=12,close=13)
        e.execute_interval({'X':b},b.date,None,e.cash)
        self.assertEqual(self.p.quantity,700);self.assertEqual(self.p.initial_risk,700)
        self.assertAlmostEqual(self.p.entry_fee,3.5)
        self.assertEqual(e.summary()['closed_trades'],0);self.assertIsNone(e.summary()['win_rate'])
        e.queue_exit(ExitIntent('x','X',b.date,'id','core_exit'))
        b=replace(b,date=self.cal[26],open=9,high=10,low=8,close=9)
        e.execute_interval({'X':b},b.date,None,e.cash)
        self.assertEqual(len(e.trades),2);self.assertEqual(e.summary()['closed_trades'],1)
        self.assertEqual(e.summary()['win_rate'],1)
        self.assertAlmostEqual(sum(t['quantity'] for t in e.trades),1000)

    def test_blocked_trim_replaced_by_full_exit(self):
        e=Backtest(self.cfg,[]);e.positions['X']=self.p;e.marks['X']=10
        trim=ExitIntent('x','X',self.cal[24],'id','profit_structure_trim',1/3)
        self.assertTrue(e.queue_exit(trim));self.assertFalse(e.queue_exit(trim))
        b=replace(self.bs[25],open=9,high=9,low=9,close=9,down_limit=9)
        e.execute_interval({'X':b},b.date,None,e.cash);self.assertFalse(e.trades)
        full=replace(trim,date=b.date,reason='core',fraction=1)
        self.assertTrue(e.queue_exit(full));self.assertFalse(e.queue_exit(trim))
        b=replace(b,date=self.cal[26],open=10,high=11,close=10)
        e.execute_interval({'X':b},b.date,None,e.cash)
        self.assertFalse(e.positions);self.assertEqual(e.trades[0]['quantity'],1000)

    def test_adapter_cost_injection_and_entry_rule_inheritance(self):
        from trading_system.strategies import build_strategies
        orig=json.loads(Path('configs/experiments/double_bottom_ihs_v7_pressure_support.json').read_text())
        for a,b in zip(orig['strategies'],self.cfg['strategies']):self.assertEqual(a['params'],b['params'])
        strategies=build_strategies(self.cfg['strategies']);Backtest(self.cfg,strategies)
        for s in strategies:
            s.set_trend_calendar(self.cal,[]);p=replace(self.p,strategy=s.name,plan={})
            s.manage_position(self.bs[:16],p)
            self.assertEqual(s.managers[p.setup_id].execution,self.cfg['execution'])

if __name__=='__main__':unittest.main()
