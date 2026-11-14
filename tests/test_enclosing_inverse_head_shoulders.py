import json
import random
import sys
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from trading_system.analysis import adjusted
from trading_system.domain import Bar
from trading_system.engine import Backtest
from trading_system.strategies import build_strategies
from trading_system.strategies.inverse_head_shoulders import InverseHeadShoulders
from trading_system.strategies.enclosing_inverse_head_shoulders import EnclosingInverseHeadShoulders, _PriceRanges


def fixture(knots=None):
    knots = knots or [16, 18, 10, 13, 8, 13, 10, 14]
    values = [a+(b-a)*j/3 for a,b in zip(knots,knots[1:]) for j in range(3)] + knots[-1:]
    return [Bar('X', (date(2025,1,1)+timedelta(days=i)).strftime('%Y%m%d'),
                v,v+.1,v-.1,v,100) for i,v in enumerate(values)]


def replay(bars, cls=EnclosingInverseHeadShoulders, params=None):
    strategy = cls('ihs', params or {})
    signals, events = [], []
    for end in range(1, len(bars)+1):
        new, audit = strategy.on_close(bars[:end], set())
        signals.extend(new); events.extend(audit)
    return signals, events


class EnclosingInverseHeadShouldersTests(unittest.TestCase):
    nested = [16,18,10,13,11.5,12,8,9.6,9.1,11.1,10.5,13,10,14]

    def test_enclosing_pattern_survives_internal_swings(self):
        bars = fixture(self.nested)
        self.assertFalse(replay(bars, InverseHeadShoulders)[0])
        signals, _ = replay(bars)
        self.assertEqual(len(signals), 1)
        e = signals[0].evidence
        self.assertEqual((e['ihs_left_date'],e['ihs_head_date'],e['ihs_right_date']),
                         tuple(bars[i*3].date for i in (2,6,12)))
        self.assertAlmostEqual(signals[0].stop, 7.9)
        self.assertAlmostEqual(signals[0].target, 18.3)

    def test_near_triple_bottom_is_not_head_shoulders(self):
        bars = fixture([16,18,10,13,9.99,13,10,14])
        self.assertEqual(len(replay(bars, InverseHeadShoulders)[0]), 1)
        self.assertFalse(replay(bars)[0])

    def test_shoulder_gap_has_its_own_height_gate(self):
        bars = fixture([106,108,100,103,98,103,101.3,104])
        self.assertEqual(len(replay(bars, InverseHeadShoulders)[0]), 1)
        self.assertFalse(replay(bars)[0])
        self.assertEqual(len(replay(bars, params={'max_shoulder_height': .3})[0]), 1)

    def test_neckline_gap_has_its_own_height_gate(self):
        bars = fixture([106,108,100,103,98,102.3,100,104])
        self.assertEqual(len(replay(bars, InverseHeadShoulders)[0]), 1)
        self.assertFalse(replay(bars)[0])
        self.assertEqual(len(replay(bars, params={'max_neckline_height': .2})[0]), 1)

    def test_shape_is_invariant_under_price_scale_and_offset(self):
        bars = fixture(self.nested)
        original = replay(bars)[0][0]
        for scale, offset in ((3.7, 0), (1, 1000), (.5, 200)):
            transformed = [replace(b, **{k:getattr(b,k)*scale+offset for k in ('open','high','low','close')}) for b in bars]
            result = replay(transformed)[0]
            self.assertEqual(len(result), 1)
            for key in ('ihs_left_date','ihs_head_date','ihs_right_date','ihs_peak1_date','ihs_peak2_date'):
                self.assertEqual(result[0].evidence[key], original.evidence[key])
            for key in ('ihs_head_prominence','ihs_shoulder_gap','ihs_neckline_gap'):
                self.assertAlmostEqual(result[0].evidence[key], original.evidence[key])

    def test_actual_deepest_head_cannot_be_skipped(self):
        bars = fixture([16,18,10,13,7,11,8,13,10,14])
        signals, _ = replay(bars)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].evidence['ihs_head_date'], bars[12].date)
        self.assertAlmostEqual(signals[0].stop, 6.9)

    def test_separated_equal_heads_are_not_one_head(self):
        self.assertFalse(replay(fixture([16,18,10,13,8,11,8,13,10,14]))[0])

    def test_deeper_left_valley_owns_the_shoulder(self):
        bars = fixture([16,18,10,11,9.2,13,8,13,10,14])
        signals, _ = replay(bars)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].evidence['ihs_left_date'], bars[12].date)

    def test_prefix_causality_and_no_duplicate_stale_break(self):
        bars = fixture(self.nested)
        strategy = EnclosingInverseHeadShoulders('ihs', {})
        for end in range(1,len(bars)+1):
            self.assertEqual(strategy.on_close(bars[:end],set()),
                             EnclosingInverseHeadShoulders('ihs',{}).on_close(bars[:end],set()))
        self.assertEqual(strategy.on_close(bars,set()), ([],[]))
        future = replace(bars[-1],date='20250210',open=14.3,high=14.5,low=14.1,close=14.3)
        self.assertFalse(strategy.on_close(bars+[future],set())[0])

    def test_delayed_confirmation_must_hold_neckline(self):
        bars = fixture()
        bars[20] = replace(bars[20], open=13.4,high=13.5,close=13.4)
        bars[21] = replace(bars[21], open=12.8,high=13,low=12.6,close=12.8)
        signals, events = replay(bars, params={'right':3})
        self.assertFalse(signals)
        self.assertIn('ihs_neckline_not_held', [e['event'] for e in events])

    def test_head_failure_and_already_reached_target(self):
        for change in ({'low':7.8}, {'high':19}):
            bars = fixture(); bars[-1] = replace(bars[-1], **change)
            self.assertFalse(replay(bars)[0])

    def test_factor_change_rebuilds_ranges_without_changing_shape(self):
        bars = fixture()
        bars = [replace(b, factor=2, **{k:getattr(b,k)/2 for k in ('open','high','low','close')}) if i>=18 else b
                for i,b in enumerate(bars)]
        signals, _ = replay(bars)
        self.assertEqual(len(signals), 1)
        self.assertAlmostEqual(signals[0].stop, 3.95)
        self.assertAlmostEqual(signals[0].target, 9.15)

    def test_registry_and_existing_execution_risk_gate(self):
        config = json.loads((ROOT/'configs/experiments/inverse_head_shoulders_v2_enclosing_structure.json').read_text())
        strategy = build_strategies(config['strategies'])[0]
        intent = strategy.on_close(fixture(),set())[0][0]
        engine = Backtest(config, [strategy]); engine.pending = [intent]
        engine.execute_interval({'X':Bar('X','20250123',14,14.2,13.8,14,100)},'20250123',None,1e6)
        self.assertFalse(engine.positions)
        self.assertEqual(engine.entry_audits[-1]['risk_reason'],'net_rr_not_above_threshold')

    def test_reject_legacy_and_invalid_parameters(self):
        for params in ({'shoulder_tolerance':.06},{'min_head_height':0},{'min_head_height':True},
                       {'max_neckline_height':float('nan')},{'max_shoulder_height':1},{'left':0}):
            with self.assertRaises(ValueError):EnclosingInverseHeadShoulders('ihs',params)

    def test_sparse_ranges_match_brute_force_across_append_and_rebase(self):
        rng = random.Random(42)
        bars = [replace(b,high=b.high+rng.random(),low=b.low-rng.random()) for b in fixture(self.nested)]
        cache = _PriceRanges()
        for end in range(1,len(bars)+1):
            prefix = bars[:end]
            if end>=25:
                prefix = adjusted([replace(b, factor=2) if i>=24 else b for i,b in enumerate(prefix)])
            cache.update(prefix)
            for _ in range(8):
                left = rng.randrange(end); right = rng.randrange(left+1,end+1)
                for kind in ('low','high','close'):
                    expected = (min if kind=='low' else max)(getattr(b,kind) for b in prefix[left:right])
                    self.assertEqual(cache.query(kind,left,right)[0],expected)
                threshold = prefix[left].close
                expected = next((i for i in range(left,right) if prefix[i].close>threshold),None)
                self.assertEqual(cache.first_close_above(left,right,threshold),expected)
