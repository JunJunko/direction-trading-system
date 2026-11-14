import sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar,Position
from trading_system.strategies.direct_double_bottom import DirectDoubleBottom
from trading_system.engine import Backtest
from trading_system.strategies import build_strategies
import json
ROOT=Path(__file__).resolve().parents[1]
class DirectWTests(unittest.TestCase):
    def fixture(self):
        bars=[Bar('X',f'202501{i+1:02}',v,v+.2,v-.2,v,100) for i,v in enumerate([12,10,11,10.1,10.5,11.3])]
        w=dict(first=1,second=3,neckline=11.2,bottom=9.8,first_breakout_index=5,pattern_area=5)
        return bars,w
    def test_single_W_owns_all_levels_and_no_extra_N(self):
        bars,w=self.fixture();s=DirectDoubleBottom('w',{})
        with patch('trading_system.strategies.direct_double_bottom.hierarchy_double_bottom_candidates',return_value=([w],'qualified')):
            intents,_=s.on_close(bars,set());self.assertEqual(len(intents),1)
            i=intents[0];self.assertEqual(i.stop,9.8);self.assertAlmostEqual(i.target,12.6)
            self.assertEqual(i.evidence['w_owner'],i.setup_id)
            self.assertEqual(s.on_close(bars,set()),([],[]))
    def test_next_open_gate_accepts_W_but_RR_rejects_it(self):
        bars,w=self.fixture();c=json.loads((ROOT/'configs/experiments/double_bottom_v5_17_direct_w_structure.json').read_text())
        s=DirectDoubleBottom('w',{})
        with patch('trading_system.strategies.direct_double_bottom.hierarchy_double_bottom_candidates',return_value=([w],'qualified')):i=s.on_close(bars,set())[0][0]
        e=Backtest(c,[s]);e.pending=[i]
        e.execute_interval({'X':Bar('X','20250107',11.3,11.5,11.2,11.4,100)},'20250107',None,1e6)
        self.assertFalse(e.positions)
        self.assertEqual(e.entry_audits[-1]['risk_reason'],'net_rr_not_above_threshold')
    def test_parameters(self):
        for p in ({'left':True},{'bottom_tolerance':float('nan')},{'unknown':1}):
            with self.assertRaises(ValueError):DirectDoubleBottom('w',p)


    def test_close_target_only_and_factor_rescaling(self):
        c=json.loads((ROOT/'configs/experiments/double_bottom_v5_17_direct_w_structure.json').read_text())
        s=DirectDoubleBottom('w',{});e=Backtest(c,[s])
        p=Position('w','X','20250101',10,100,8,200,5,'id',1,dict(w_target=12,w_floor=8,w_neckline=10),10)
        e.positions['X']=p
        e.histories['X']=[Bar('X','20250101',10,10,10,10,100)];e.marks['X']=10
        self.assertEqual(s.manage_position([Bar('X','20250102',11,13,10,11,100)],p),([],[]))
        exits,_=s.manage_position([Bar('X','20250102',11,13,10,12,100)],p)
        self.assertEqual(exits[0].reason,'w_target_close_confirmed')
        e.adjust_factors({'X':Bar('X','20250103',5,6,4,5,100,factor=2)},'20250103')
        self.assertEqual(p.plan['w_target'],6)
        self.assertEqual(p.plan['w_floor'],4)
        self.assertEqual(p.plan['w_neckline'],5)

    def test_delayed_confirmation_below_neckline_cannot_enter(self):
        bars,w=self.fixture()
        from dataclasses import replace
        bars[-1]=replace(bars[-1],close=10.8)
        with patch('trading_system.strategies.direct_double_bottom.hierarchy_double_bottom_candidates',return_value=([w],'qualified')):
            intents,events=DirectDoubleBottom('w',{}).on_close(bars,set())
        self.assertFalse(intents)
        self.assertEqual(events[0]['event'],'w_neckline_not_held')
