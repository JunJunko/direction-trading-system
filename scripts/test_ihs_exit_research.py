import copy,sys,unittest
from datetime import date,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v3-retest/source/src'))
from trading_system.domain import Bar,Position
from trading_system.engine import Backtest
from ihs_exit_research import ResearchExit,liquidation_net,breakeven_stop

C=dict(initial_cash=1000000,execution=dict(minimum_commission=5,commission_rate=.0003,slippage=.001,
    sell_tax_after_20230828=.0005,sell_tax_before_20230828=.001),risk=dict(risk_per_trade=.005,
    max_portfolio_risk=.02,max_position_weight=.1,max_gross_weight=.5,max_positions=5,min_rr=3))
def bar(i,o=10,h=10.2,l=9.8,c=10,factor=1,down=0,volume=100):
    return Bar('X',(date(2026,1,1)+timedelta(days=i)).strftime('%Y%m%d'),o,h,l,c,volume,factor,0,down)
def pos():
    return Position('s','X',bar(16).date,10,1000,9,1025,5,'pid',1,
        dict(ihs_target=20,ihs_neckline=10,ihs_retest_low=9.9,research_initial_stop=9,support_exit_on_touch=True))
def manager(arm):return ResearchExit('s',arm,C['execution'],[bar(i).date for i in range(100)])

class ExitTests(unittest.TestCase):
    def test_breakeven_covers_fees_and_sell_slip(self):
        for q in (100,1000,10000):
            p=pos();p.quantity=q
            level=breakeven_stop(p,.0006,.0005,.002)
            self.assertGreaterEqual(liquidation_net(p,level,.0006,.0005,.002),0)
            self.assertLess(liquidation_net(p,level-.01,.0006,.0005,.002),0)

    def test_high_only_one_R_does_not_activate(self):
        s=manager('E1');p=pos();history=[bar(i) for i in range(17)]+[bar(17,h=12,c=10.2)]
        _,events,_=s.manage(history,p)
        self.assertEqual(p.stop,9);self.assertFalse(s.be_active)
        self.assertFalse(any(e['reason']=='stop_raised' for e in events))

    def test_close_activation_never_reuses_same_bar_low(self):
        s=manager('E1');p=pos();history=[bar(i) for i in range(17)]
        e=Backtest(copy.deepcopy(C),[]);e.positions['X']=p;e.histories['X']=history;e.marks['X']=10
        b=bar(17,o=10,h=11.5,l=9.5,c=11.3)
        e.execute_interval({'X':b},b.date,None,e.cash)
        self.assertFalse(e.trades)
        _,events,_=s.manage(history+[b],p)
        self.assertGreater(p.stop,10);self.assertFalse(e.trades)
        self.assertTrue(all(v['valid_from']==bar(18).date for v in events))
        tomorrow=bar(18,o=10.05,h=10.2,l=9.9,c=10)
        e.execute_interval({'X':tomorrow},tomorrow.date,None,e.cash)
        self.assertEqual(len(e.trades),1)

    def test_confirmed_structure_only_then_frozen_buffer(self):
        s=manager('E2');p=pos();history=[bar(i) for i in range(17)]
        values=[10.8,10.5,10.3,10.6,10.7]
        history += [bar(17+i,o=v+.1,h=v+.4,l=v,c=v+.2) for i,v in enumerate(values)]
        for end in range(18,22):
            s.manage(history[:end],p)
            self.assertEqual(p.stop,9)
        _,events,_=s.manage(history,p)
        self.assertGreater(p.stop,9)
        selected=next(e for e in events if e['reason']=='higher_support_selected')
        self.assertEqual(selected['formed'],bar(19).date)
        self.assertEqual(selected['confirmed'],bar(21).date)
        self.assertEqual(selected['valid_from'],bar(22).date)
        old=p.stop
        s.manage(history+[bar(22,o=10.9,h=11,l=10.8,c=10.9)],p)
        self.assertEqual(p.stop,old)

    def test_prefix_equivalence_and_monotonic(self):
        history=[bar(i) for i in range(17)]+[bar(i,o=v+.1,h=v+.4,l=v,c=v+.2)
            for i,v in enumerate([10.8,10.5,10.3,10.6,11.3,11.5,11.2,11.1,11.4,11.6],17)]
        def replay(end):
            s=manager('E3');p=pos();out=[]
            for n in range(17,end+1):
                old=p.stop;ex,ev,net=s.manage(history[:n],p);self.assertGreaterEqual(p.stop,old)
                out.append((p.stop,ex,ev,net))
            return out
        full=replay(len(history))
        for n in range(17,len(history)+1):self.assertEqual(replay(n),full[:n-16])

    def test_gap_and_limit_down_and_T1(self):
        e=Backtest(copy.deepcopy(C),[]);p=pos();e.positions['X']=p
        same=bar(16,o=10,h=10.1,l=8.8,c=9)
        e.execute_interval({'X':same},same.date,None,e.cash)
        self.assertFalse(e.trades);self.assertTrue(p.plan.get('t1_stop_breached_at'))
        blocked=bar(17,o=8,h=8,l=8,c=8,down=8)
        e.execute_interval({'X':blocked},blocked.date,None,e.cash);self.assertFalse(e.trades)
        gap=bar(18,o=8.2,h=8.7,l=8,c=8.5)
        e.execute_interval({'X':gap},gap.date,None,e.cash)
        self.assertAlmostEqual(e.trades[0]['exit'],8.2*.999)
        self.assertEqual(e.trades[0]['reason'],'deferred_support_break')

    def test_factor_change_keeps_economic_stop(self):
        s=manager('E1');p=pos();history=[bar(i) for i in range(17)]+[bar(17,o=11,h=11.5,l=10.9,c=11.3)]
        s.manage(history,p);old=p.stop
        p.entry/=2;p.quantity*=2;p.stop/=2;p.factor=2;p.plan['research_initial_stop']/=2;p.plan['ihs_target']/=2
        _,events,_=s.manage(history+[bar(18,o=5.6,h=5.7,l=5.5,c=5.6,factor=2)],p)
        self.assertEqual(p.stop,old/2)
        self.assertFalse(any(e['reason']=='breakeven_activated' for e in events))

if __name__=='__main__':unittest.main(verbosity=2)
