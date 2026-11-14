import unittest,copy
from trading_system.domain import Bar,Position,ExitIntent
from trading_system.target_migration import State,PositionContext,TargetDecisionEngine,KeyLevelRegistry,ConfirmedSupportTrail,atr_pre
from trading_system.strategies.target_migration_w import TargetMigrationW
from trading_system.engine import Backtest

def bar(i,o=11.1,h=11.46,l=11.08,c=11.42,volume=100,down=0):
    return Bar('X',f'202601{i+1:02}',o,h,l,c,volume,1,0,down)
def context():return PositionContext('test',0,10,100,9,9,10,11.2)

class TargetMigrationTests(unittest.TestCase):
    def test_spec_numeric_candidate_acceptance_not_support(self):
        ctx=context();d=TargetDecisionEngine()
        self.assertEqual(d.close(ctx,1,bar(1),.25),'breakout_candidate')
        self.assertEqual(ctx.execution_stop,9)
        self.assertEqual(d.close(ctx,2,bar(2,c=11.39),.25),'acceptance_confirmed')
        self.assertEqual(ctx.state,State.TREND_HOLD)
        self.assertEqual(ctx.execution_stop,9);self.assertEqual(ctx.confirmed_support_ids,[])

    def test_failed_first_touch_cannot_be_resurrected(self):
        for mode in ('soft','dynamic'):
            ctx=context();d=TargetDecisionEngine(mode)
            d.close(ctx,1,bar(1,h=11.34,c=11.25),.25)
            self.assertEqual(ctx.state,State.EXIT_PENDING)
            d.close(ctx,2,bar(2,c=12.5,h=12.6),.25)
            self.assertEqual(ctx.state,State.EXIT_PENDING)
            self.assertIsNone(ctx.breakout_candidate_at)

    def test_high_only_cross_is_not_breakout(self):
        ctx=context();TargetDecisionEngine().close(ctx,1,bar(1,c=11.19),.25)
        self.assertEqual(ctx.state,State.EXIT_PENDING)

    def test_candidate_gap_failure(self):
        ctx=context();d=TargetDecisionEngine();d.close(ctx,1,bar(1),.25)
        self.assertEqual(d.close(ctx,2,bar(2,o=10.8,h=11.1,l=10.7,c=11),.25),'candidate_failed')

    def test_acceptance_must_be_consecutive_and_expire(self):
        ctx=context();d=TargetDecisionEngine();d.close(ctx,1,bar(1),.25)
        for i in (2,3):d.close(ctx,i,bar(i,c=11.21),.25)
        self.assertEqual(d.close(ctx,4,bar(4,c=11.21),.25),'candidate_expired')

    def test_legacy_hard_is_close_based(self):
        ctx=context();d=TargetDecisionEngine('hard')
        self.assertIsNone(d.close(ctx,1,bar(1,c=11.19),.25))
        self.assertEqual(d.close(ctx,2,bar(2,c=11.2),.25),'legacy_target_close')

    def test_atr_excludes_current_bar(self):
        bars=[bar(i,o=10,h=10.2,l=9.8,c=10) for i in range(18)]
        a=atr_pre(bars)
        bars[-1]=bar(17,h=100,l=1,c=50)
        self.assertAlmostEqual(a,.4);self.assertEqual(a,atr_pre(bars))

    def test_plateau_has_deterministic_confirmation(self):
        highs=[10,11,13,13,12,11]
        bars=[bar(i,o=x-1,h=x,l=x-2,c=x-1) for i,x in enumerate(highs)]
        r=KeyLevelRegistry();r.update(bars[:-1],.25)
        self.assertFalse(any(x.kind=='RESISTANCE' for x in r.levels.values()))
        r.update(bars,.25);level=next(x for x in r.levels.values() if x.kind=='RESISTANCE')
        self.assertEqual((level.pivot_at,level.confirmed_at,level.valid_from),(3,5,6))

    def test_confirmed_support_buffer_and_monotonic_stop(self):
        lows=[12,11.8,11.28,11.6,11.7]
        bars=[bar(i,o=x+.1,h=x+.3,l=x,c=x+.2) for i,x in enumerate(lows)]
        r=KeyLevelRegistry();ctx=context();ctx.initial_stop=10.9;ctx.execution_stop=10.9
        r.update(bars[:-1],.25)
        self.assertEqual(ConfirmedSupportTrail().propose(ctx,r,bars[:-1],.25),(10.9,None))
        r.update(bars,.25)
        self.assertAlmostEqual(ConfirmedSupportTrail().propose(ctx,r,bars,.25)[0],11.155)
        ctx.execution_stop=11.3
        self.assertEqual(ConfirmedSupportTrail().propose(ctx,r,bars,.25)[0],11.3)

    def test_prefix_replay_and_no_synthetic_resistance(self):
        bars=[bar(i,o=10+i*.1,h=10.3+i*.1,l=9.9+i*.1,c=10.2+i*.1) for i in range(20)]
        running=KeyLevelRegistry()
        for t in range(1,len(bars)+1):
            prefix=bars[:t];running.update(prefix,.25);fresh=KeyLevelRegistry();fresh.update(prefix,.25)
            self.assertEqual(running.levels,fresh.levels)
            self.assertEqual(running.resistances(prefix[-1].close,t-1,.25,.01),[])

    def test_missing_b4_does_not_invent_momentum(self):
        with self.assertRaises(ValueError):TargetMigrationW('x',dict(target_arm='B4',minimum_price_tick=.01))

    def test_execution_stop_priority_and_limit_down_retry(self):
        c=dict(initial_cash=10000,execution=dict(minimum_commission=5,commission_rate=.0003,slippage=.001,
            sell_tax_after_20230828=.0005,sell_tax_before_20230828=.001),
            risk=dict(risk_per_trade=.005,max_portfolio_risk=.02,max_position_weight=.1,max_gross_weight=.5,max_positions=5,min_rr=3))
        e=Backtest(c,[])
        e.positions['X']=Position('s','X','20260101',10,100,9,110,5,'id',1,dict(support_exit_on_touch=True))
        e.pending_exits=[ExitIntent('s','X','20260101','id','candidate_failed')]
        e.execute_interval({'X':bar(1,o=8,h=8,l=8,c=8,down=8)},'20260102',None,e.cash)
        self.assertEqual(len(e.trades),0);self.assertEqual(len(e.pending_exits),1)
        e.execute_interval({'X':bar(2,o=8.2,h=8.7,l=8,c=8.5)},'20260103',None,e.cash)
        self.assertEqual(len(e.trades),1);self.assertEqual(e.trades[0]['reason'],'deferred_support_break')
        self.assertAlmostEqual(e.trades[0]['exit'],8.2*.999)
        self.assertEqual(e.trades[0]['quantity'],100)

    def test_suspension_defers_exit(self):
        c=dict(initial_cash=10000,execution=dict(minimum_commission=5,commission_rate=.0003,slippage=.001,
            sell_tax_after_20230828=.0005,sell_tax_before_20230828=.001),
            risk=dict(risk_per_trade=.005,max_portfolio_risk=.02,max_position_weight=.1,max_gross_weight=.5,max_positions=5,min_rr=3))
        e=Backtest(c,[]);e.positions['X']=Position('s','X','20260101',10,100,9,110,5,'id',1,{})
        e.pending_exits=[ExitIntent('s','X','20260101','id','candidate_failed')]
        e.execute_interval({'X':bar(1,volume=0)},'20260102',None,e.cash)
        self.assertEqual(len(e.trades),0);self.assertEqual(len(e.pending_exits),1)

if __name__=='__main__':unittest.main()
