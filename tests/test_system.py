import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.analysis import adjusted,pivot_lows,weekly
from trading_system.demo import demo_data
from trading_system.domain import Bar,Intent,Position
from trading_system.engine import Backtest
from trading_system.risk import RiskManager
from trading_system.strategies import build_strategies


def config():
    return json.loads((Path(__file__).resolve().parents[1]/'configs/double_bottom_v3.json').read_text())


class Tests(unittest.TestCase):
    def test_end_to_end_winner_and_loser(self):
        bars,calendar,ends=demo_data()
        c=config()
        e=Backtest(c,build_strategies(c['strategies'])).run(bars,calendar,ends)
        self.assertEqual(e.summary()['filled_buys'],2)
        self.assertEqual(len(e.trades),2)
        self.assertTrue(any(t['pnl']>0 for t in e.trades))
        self.assertTrue(any(t['pnl']<0 for t in e.trades))
        self.assertTrue(all(t['exit_date']>t['entry_date'] for t in e.trades))
        self.assertTrue(all(r['cash']>=0 for r in e.curve))
        self.assertTrue(any(x['event']=='stop_raised' for x in e.events))

    def test_prefix_invariance_no_future_signals(self):
        bars,calendar,ends=demo_data()
        def run(cut):
            c=config()
            return Backtest(c,build_strategies(c['strategies'])).run(
                [b for b in bars if b.date<=cut],[d for d in calendar if d<=cut],ends)
        full=run(calendar[-1])
        for cut in (calendar[70],calendar[95],calendar[99],calendar[105]):
            short=run(cut)
            self.assertEqual(short.events,[x for x in full.events if x['date']<=cut])
            self.assertEqual(short.orders,[x for x in full.orders if x['date']<=cut])

    def test_pivot_confirmation_delay(self):
        bars=[Bar('X',f'2024010{i+1}',10,11,v,10,1) for i,v in enumerate([9,8,7,8,9])]
        self.assertEqual(pivot_lows(bars[:4],2,2),[])
        self.assertEqual(pivot_lows(bars,2,2),[2])

    def test_partial_week_not_visible(self):
        bars,_,ends=demo_data()
        history=[b for b in bars if b.symbol=='DEMO.WIN'][:4]
        self.assertEqual(weekly(history,ends),[])

    def test_adjustment_uses_only_known_factor(self):
        bars=[Bar('X','20240101',10,11,9,10,1,1),Bar('X','20240102',5,6,4,5,1,2)]
        self.assertEqual(adjusted(bars[:1])[0].close,10)
        self.assertEqual(adjusted(bars)[0].close,5)

    def test_gap_and_net_rr_rejection(self):
        c=config()
        risk=RiskManager(c['risk'])
        i=Intent('s','X','20240101',12.2,11.7,14,'id','reason')
        q,reason=risk.size(i,12.2,1e6,1e6,{}, {},.0003,.0005)
        self.assertGreater(q,0)
        self.assertEqual(q%100,0)
        q,reason=risk.size(i,12.8,1e6,1e6,{}, {},.0003,.0005)
        self.assertEqual(q,0)
        self.assertEqual(reason,'net_rr_not_above_threshold')

    def test_philosophy_gate(self):
        c=config()
        c['risk']['min_rr']=2
        with self.assertRaises(ValueError):
            RiskManager(c['risk'])

    def test_shared_portfolio_symbol_ownership(self):
        c=config()
        p=Position('one','X','20240101',12,100,11,100,5,'setup',1)
        i=Intent('two','X','20240102',12.2,11.7,14,'id','reason')
        q,reason=RiskManager(c['risk']).size(i,12.2,1e6,1e6,{'X':p},{'X':12},.0003,.0005)
        self.assertEqual((q,reason),(0,'symbol_already_owned'))

    def test_nonadjacent_troughs_cannot_be_combined(self):
        from trading_system.strategies.double_bottom import DoubleBottom
        # Old v1 could pair 10 and 10.1 across a materially deeper 8-yuan trough.
        closes=[15,14,12,10,11,12,11,8,10,12,11,10.1,11,12,13]
        bars=[Bar('X',f'202401{i+1:02d}',c,c+.01,c-.01,c,100) for i,c in enumerate(closes)]
        s=DoubleBottom('strict',dict(direction_cycle='daily',left=1,right=1))
        _,events=s.on_close(bars,set())
        self.assertFalse(any(e['event']=='double_bottom_breakout' for e in events))

    def test_slippage_rejection_is_not_reported_as_limit_up(self):
        e=Backtest(config(),[])
        e.pending=[Intent('fixture','X','20240101',10.01,9,15,'id','test')]
        class Fixture:
            name='fixture'
            def on_close(self,*args): return [],[]
            def trailing_stop(self,h,p): return p.stop
        e.strategies=[Fixture()]
        e.run([Bar('X','20240102',10.1,10.1,10,10.05,100,1,11,9)],['20240102'],set())
        audit=e.entry_audits[0]
        self.assertEqual(audit['execution_reason'],'slippage_exceeds_daily_high')
        self.assertTrue(audit['fill_below_up_limit'])
        self.assertFalse(audit['fill_within_bar'])
        self.assertGreater(audit['net_rr'],3)

    def test_portfolio_risk_includes_estimated_exit_costs(self):
        c=config()
        p=Position('one','Y','20240101',12,100,11,100,5,'setup',1)
        i=Intent('two','X','20240102',12.2,11.7,14,'id','reason')
        result=RiskManager(c['risk']).assess(i,12.2,1e6,1e6,{'Y':p},{'Y':12},.0003,.0005,slippage=.001)
        self.assertGreater(result['used_portfolio_risk'],100)

    def test_stop_gap_limit_down_and_suspension(self):
        c=config()
        e=Backtest(c,[])
        e.positions['X']=Position('fixture','X','20240101',10,100,9,100,5,'id',1)
        e.marks['X']=10
        # Suspended date carries mark; locked down day preserves stop; gap exits at executable price.
        bars=[Bar('X','20240103',8,8,8,8,100,1,12,8),
              Bar('X','20240104',7.5,8,7,7.8,100,1,10,6)]
        # Owner is needed only for trailing management; use a fixture with no signals.
        class Fixture:
            name='fixture'
            def on_close(self,*args): return [],[]
            def trailing_stop(self,h,p): return p.stop
        e.strategies=[Fixture()]
        e.run(bars,['20240102','20240103','20240104'],set())
        self.assertEqual(len(e.trades),1)
        self.assertLess(e.trades[0]['exit'],9)
        self.assertEqual(e.trades[0]['exit_date'],'20240104')
        self.assertTrue(any(x['event']=='stop_blocked_limit_down' for x in e.events))


if __name__=='__main__':
    unittest.main()
