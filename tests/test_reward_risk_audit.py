import random
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'scripts'))
from audit_reward_risk import cash_flows,required_target
from trading_system.domain import Intent
from trading_system.risk import RiskManager


class RewardRiskAuditTests(unittest.TestCase):
    def test_cash_flow_scenarios_include_each_side_once(self):
        # Minimum commission applies to each mutually exclusive sale scenario.
        r=cash_flows(10,9,14,100,.0003,.0005,.001)
        self.assertEqual(r['entry_fee'],Decimal(5))
        self.assertEqual(r['expected_profit'],Decimal('387.9007000'))
        self.assertEqual(r['expected_loss'],Decimal('111.3495500'))

    def test_target_inverse_both_commission_branches(self):
        for q in (100,10000):
            for commission in (0,.0003):
                target=required_target(10,9,q,commission,.0005,.001)
                exact=cash_flows(10,9,target,q,commission,.0005,.001)
                self.assertLess(abs(exact['net_rr']-3),Decimal('1e-30'))
                for step,passes in ((Decimal('-.000001'),False),(Decimal('.000001'),True)):
                    r=cash_flows(10,9,target+step,q,commission,.0005,.001)
                    self.assertEqual(r['net_rr']>3,passes)

    def test_strict_threshold_and_minimum_commission(self):
        config=dict(risk_per_trade=.005,max_portfolio_risk=.02,
            max_position_weight=.1,max_gross_weight=.5,max_positions=5,min_rr=3)
        risk=RiskManager(config)
        # 100 shares, zero rates but 5 yuan minimum each side: reward310/loss110.
        intent=Intent('s','X','20260101',10,9,13.2,'id','test')
        result=risk.assess(intent,10,10000,10000,{}, {},0,0)
        self.assertGreater(result['gross_rr'],3)
        self.assertEqual(result['risk_reason'],'insufficient_budget_or_cash')
        result=risk.assess(intent,10,25000,1000,{}, {},0,0)
        self.assertEqual(result['risk_reason'],'net_rr_not_above_threshold')
        self.assertAlmostEqual(result['net_rr'],310/110)

    def test_sizing_matches_independent_exhaustive_board_lots(self):
        rng=random.Random(20261010)
        config=dict(risk_per_trade=.005,max_portfolio_risk=.02,
            max_position_weight=.1,max_gross_weight=.5,max_positions=5,min_rr=3)
        manager=RiskManager(config)
        for _ in range(400):
            fill=rng.uniform(2,90);stop=fill*(1-rng.uniform(.003,.20))
            target=fill*(1+rng.uniform(.003,.7))
            equity=rng.uniform(20000,100000);cash=rng.uniform(400,equity)
            commission=rng.choice([0,.0003,.001]);tax=rng.choice([0,.0005,.001])
            slip=rng.choice([0,.001,.003])
            intent=Intent('s','X','20260101',fill,stop,target,'id','test')
            actual=manager.assess(intent,fill,equity,cash,{}, {},commission,tax,slippage=slip)
            cap=int(equity*.1/fill//100)*100;expected=0
            for q in range(100,cap+1,100):
                r=cash_flows(fill,stop,target,q,commission,tax,slip)
                if (Decimal(str(fill))*q+r['entry_fee']<=Decimal(str(cash))
                        and r['expected_loss']<=Decimal(str(equity))*Decimal('.005')
                        and r['net_rr']>3):expected=q
            self.assertEqual(actual['quantity'],expected,(intent,actual,expected))

    def test_reducing_board_lots_cannot_rescue_threshold_rejection(self):
        # Justifies rejecting before decrementing infeasible candidate quantity:
        # lower quantity cannot rescue RR>3 under these cost schedules. Negative
        # ratios need not be monotone, but are still below the positive threshold.
        for target in (10.01,12,14,30):
            ratios=[cash_flows(10,9,target,q,.0003,.0005,.001)['net_rr']
                    for q in range(100,20001,100)]
            self.assertTrue(all(a<=3 for i,b in enumerate(ratios) if b<=3 for a in ratios[:i]))


if __name__=='__main__':unittest.main()
