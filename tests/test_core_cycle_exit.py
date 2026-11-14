import unittest
from dataclasses import replace
from trading_system.domain import Bar, Position
from trading_system.core_cycle_exit import CoreCycleExit, ProfitGivebackExit


class CoreCycleTests(unittest.TestCase):
    def setUp(self):
        self.cal = [f'202601{i:02d}' for i in range(1, 25)]
        highs = [12,13,16,14,13,12,13,14,17,16,16,16]
        lows = [10,11,12,11,10,9,10,11,12,10,8,8]
        self.bs = [Bar('X', d, l+1, h, l, h-.5, 100) for d,h,l in zip(self.cal,highs,lows)]
        self.p = Position('x','X',self.cal[0],11,100,7,400,5,'id',1)

    def manager(self, resume=True):
        m = CoreCycleExit('x', self.cal, [], require_resume=resume)
        m.initialized = True
        return m

    def replay(self,m,bs):
        result=[]
        for i in range(1,len(bs)+1):result.append(m.manage(bs[:i],self.p))
        return result

    def test_confirmed_low_waits_two_bars_and_resume(self):
        m=self.manager();self.replay(m,self.bs[:7]);self.assertIsNone(m.protection)
        m.manage(self.bs[:8],self.p);self.assertIsNone(m.protection)
        self.assertEqual(m.daily_candidates[0]['price'],9)
        exits,_=m.manage(self.bs[:9],self.p)
        self.assertFalse(exits);self.assertEqual(m.protection,9)
        self.assertEqual(self.p.stop,7)

    def test_independent_low_promotes_at_confirmation(self):
        m=self.manager(False);self.replay(m,self.bs[:8]);self.assertEqual(m.protection,9)

    def test_next_close_break_and_pending_idempotency(self):
        m=self.manager();self.replay(m,self.bs[:9])
        bs=self.bs[:10];bs[-1]=replace(bs[-1],low=8,close=8.5)
        exits,_=m.manage(bs,self.p);self.assertEqual(len(exits),1)
        self.assertEqual(exits[0].date,self.cal[9]);self.assertFalse(m.manage(bs,self.p)[0])

    def test_missing_session_cannot_confirm_pivot(self):
        m=self.manager(False);self.replay(m,self.bs[:6]+self.bs[7:8]);self.assertIsNone(m.protection)

    def test_factor_invariant(self):
        a=self.manager();self.replay(a,self.bs[:9])
        b=self.manager();bs=[replace(v,open=v.open/2,high=v.high/2,low=v.low/2,close=v.close/2,factor=2) for v in self.bs[:9]]
        self.p.entry/=2;self.p.stop/=2;self.p.factor=2
        self.replay(b,bs);self.assertEqual(a.protection,b.protection)

    def test_lower_candidate_never_lowers_support(self):
        m=self.manager(False);m.protection=10
        bs=[replace(b,close=max(10.5,b.close)) for b in self.bs[:8]]
        self.replay(m,bs);self.assertEqual(m.protection,10)

    def test_no_future_bar_access(self):
        a=self.manager();b=self.manager()
        future=list(self.bs);future[-1]=replace(future[-1],high=999,low=.01)
        self.assertEqual(self.replay(a,self.bs[:9]),self.replay(b,future[:9]))

    def test_invalidated_candidate_not_resurrected(self):
        m=self.manager();self.replay(m,self.bs[:8])
        bs=self.bs[:9];bs[-1]=replace(bs[-1],low=8,close=8.5)
        m.manage(bs,self.p);self.assertFalse(m.daily_candidates)
        bs.append(replace(self.bs[9],high=20,close=19))
        m.manage(bs,self.p);self.assertIsNone(m.protection)

    def test_giveback_uses_close_not_high_and_preserves_initial_risk(self):
        m=ProfitGivebackExit('x',self.cal,[]);m.initialized=True
        bs=[replace(self.bs[0],high=30,close=15)]
        m.manage(bs,self.p);self.assertIsNone(m.protection)
        bs.append(replace(self.bs[1],high=30,low=8,close=19))
        ex,_=m.manage(bs,self.p);self.assertFalse(ex);self.assertEqual(m.protection,15)
        self.assertEqual(self.p.initial_risk,400);self.assertEqual(self.p.stop,7)
        bs.append(replace(self.bs[2],high=20,low=14,close=14.5))
        self.assertTrue(m.manage(bs,self.p)[0])

    def test_giveback_factor_change_does_not_move_economic_floor(self):
        m=ProfitGivebackExit('x',self.cal,[]);m.initialized=True
        bs=[replace(self.bs[0],high=20,close=19)];m.manage(bs,self.p)
        self.p.factor=2;self.p.entry/=2;self.p.stop/=2;self.p.quantity*=2
        bs.append(replace(self.bs[1],open=9,high=10,low=8,close=9,factor=2))
        self.assertFalse(m.manage(bs,self.p)[0]);self.assertEqual(m.protection,15)

    def test_giveback_invalid_parameters(self):
        for args in ({'activation_r':0},{'retain':1},{'retain':float('nan')}):
            with self.assertRaises(ValueError):ProfitGivebackExit('x',self.cal,[],**args)

    def test_experiment_strategy_adapters(self):
        import json
        from pathlib import Path
        from trading_system.strategies import build_strategies
        cfg=json.loads(Path('configs/experiments/double_bottom_ihs_v8_profit_giveback.json').read_text())
        for s in build_strategies(cfg['strategies']):
            s.set_trend_calendar(self.cal,[])
            p=replace(self.p,strategy=s.name,plan={})
            s.manage_position([replace(self.bs[0],high=20,close=19)],p)
            self.assertIsInstance(s.managers[p.setup_id],ProfitGivebackExit)
            self.assertEqual(p.plan['dynamic_support_economic'],15)

if __name__=='__main__':unittest.main()
