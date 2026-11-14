import copy,json,unittest
from dataclasses import replace
from pathlib import Path
from trading_system.analysis import adjusted
from trading_system.strategies.pressure_support_w import PressureSupportW
from trading_system.strategies.qualified_w_retest import QualifiedWRetest
from trading_system.strategies import build_strategies
from trading_system.pressure_support_trend import PressureSupportTrend
from trading_system.engine import Backtest
from trading_system.domain import Bar,Intent

class PressureWTests(unittest.TestCase):
    def fixture(self):
        from test_main_trend import Tests
        f=Tests();f.setUp();return f

    def test_normalization_matches_original_across_factors_and_repeat_calls(self):
        bs=self.fixture().bars;s=QualifiedWRetest('x',{})
        bs=[replace(b,factor=2 if i>30 else 1) for i,b in enumerate(bs)]
        for n in range(1,len(bs)+1):
            self.assertEqual(s.normalized_history(bs[:n]),adjusted(bs[:n]))
            self.assertEqual(s.normalized_history(bs[:n]),adjusted(bs[:n]))
        self.assertEqual(s.normalized_history(bs[:20]),adjusted(bs[:20]))

    def test_pressure_manager_is_shared_with_ihs_and_target_does_not_sell(self):
        f=self.fixture();s=PressureSupportW('x',{});s.set_trend_calendar(f.cal,set(f.ends))
        f.p.plan={'w_target':13}
        for n in range(36,71):s.manage_position(f.bars[:n],f.p)
        bs=f.bars[:71];bs[-1]=replace(bs[-1],open=20,high=30,low=19,close=27)
        exits,_=s.manage_position(bs,f.p)
        self.assertFalse(exits);self.assertIsInstance(s.managers['id'],PressureSupportTrend)
        self.assertEqual(f.p.plan['dynamic_support_economic'],25)
        self.assertEqual(s.trailing_stop(bs,f.p),3)

    def test_config_retains_original_entry_parameters_and_account(self):
        root=Path('configs/experiments')
        old=json.loads((root/'double_bottom_v5_19_qualified_w_structure.json').read_text())
        new=json.loads((root/'double_bottom_v7_pressure_support.json').read_text())
        new['strategies'][0]['params'].pop('pressure_breakout_atr')
        new['strategies'][0]['type']=old['strategies'][0]['type'];new['strategies'][0]['id']=old['strategies'][0]['id']
        self.assertEqual(old,new)
        combo=json.loads((root/'double_bottom_ihs_v7_pressure_support.json').read_text())
        self.assertEqual(len(build_strategies(combo['strategies'])),2)

    def test_two_patterns_cannot_duplicate_same_symbol_entry(self):
        cfg=json.loads(Path('configs/experiments/double_bottom_ihs_v7_pressure_support.json').read_text())
        strategies=build_strategies(cfg['strategies']);e=Backtest(cfg,strategies)
        a=Intent(strategies[0].name,'X','20250115',10,9.8,14,'w','direct_w',dict(entry_order='next_open',entry_mode='w_neckline',rebound_confirmed_at='20250115',breakout_reference=9.9))
        b=replace(a,strategy=strategies[1].name,setup_id='ihs',reason='inverse_head_shoulders',evidence=dict(a.evidence,entry_mode='ihs_neckline'))
        e.pending=[a,b];bar=Bar('X','20250116',10,10.2,9.9,10.1,100)
        e.execute_interval({'X':bar},bar.date,None,e.cash)
        self.assertEqual(len(e.positions),1)
        self.assertEqual(sum(o['side']=='buy' and o['status']=='filled' for o in e.orders),1)
        self.assertEqual(e.positions['X'].strategy,strategies[0].name)

if __name__=='__main__':unittest.main()
