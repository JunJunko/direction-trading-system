import json
import sys
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from trading_system.domain import Bar, Position
from trading_system.engine import Backtest
from trading_system.strategies import build_strategies
from trading_system.strategies.inverse_head_shoulders import InverseHeadShoulders
from trading_system.analysis import adjusted


def fixture(knots=None):
    knots = knots or [16, 18, 10, 13, 8, 13, 10, 14]
    values = [a + (b-a)*j/3 for a, b in zip(knots, knots[1:]) for j in range(3)] + [14]
    return [Bar('X', (date(2025, 1, 1)+timedelta(days=i)).strftime('%Y%m%d'),
                v, v+.1, v-.1, v, 100) for i, v in enumerate(values)]


class InverseHeadShouldersTests(unittest.TestCase):
    def config(self):
        return json.loads((ROOT/'configs/experiments/inverse_head_shoulders_v1_structure.json').read_text())

    def test_real_pivots_and_prefix_causality(self):
        bars = fixture()
        incremental = InverseHeadShoulders('ihs', {})
        signals = []
        for end in range(1, len(bars)+1):
            prefix = bars[:end]
            actual, _ = incremental.on_close(prefix, set())
            fresh, _ = InverseHeadShoulders('ihs', {}).on_close(prefix, set())
            self.assertEqual(actual, fresh)
            signals.extend(actual)
        self.assertEqual(len(signals), 1)
        intent = signals[0]
        self.assertEqual(intent.stop, 7.9)
        self.assertAlmostEqual(intent.target, 18.3)
        self.assertEqual(intent.evidence['ihs_owner'], intent.setup_id)
        self.assertEqual(intent.evidence['ihs_right_date'], bars[18].date)
        self.assertEqual(intent.date, bars[21].date)
        self.assertEqual(incremental.on_close(bars, set()), ([], []))

    def test_reject_non_head_and_unmatched_shoulders(self):
        for index, value in ((4, 10.5), (6, 11.8), (5, 14.5), (1, 12.5)):
            knots = [12, 18, 10, 13, 8, 13, 10, 14]
            knots[index] = value
            bars = fixture(knots)
            self.assertFalse(InverseHeadShoulders('ihs', {}).on_close(bars, set())[0])

    def test_head_break_and_exhausted_target(self):
        for changes, reason in ((dict(low=7.8), 'ihs_structure_invalidated'),
                                (dict(high=19), 'ihs_space_exhausted')):
            bars = fixture()
            bars[-1] = replace(bars[-1], **changes)
            signals, events = InverseHeadShoulders('ihs', {}).on_close(bars, set())
            self.assertFalse(signals)
            self.assertIn(reason, [e['event'] for e in events])

    def test_delayed_confirmation_requires_held_neckline(self):
        bars = fixture()
        bars[20] = replace(bars[20], open=13.4, high=13.5, close=13.4)
        bars[21] = replace(bars[21], open=12.8, high=13, low=12.6, close=12.8)
        signals, events = InverseHeadShoulders('ihs', {'right': 3}).on_close(bars, set())
        self.assertFalse(signals)
        self.assertIn('ihs_neckline_not_held', [e['event'] for e in events])

    def test_registry_next_open_risk_and_same_day_guard(self):
        config = self.config()
        strategy = build_strategies(config['strategies'])[0]
        intent = strategy.on_close(fixture(), set())[0][0]
        engine = Backtest(config, [strategy])
        engine.pending = [intent]
        with self.assertRaises(ValueError):
            engine.execute_interval({'X': fixture()[-1]}, intent.date, None, 1e6)
        engine.pending = [intent]
        engine.execute_interval({'X': Bar('X', '20250123', 14, 14.2, 13.8, 14, 100)}, '20250123', None, 1e6)
        self.assertFalse(engine.positions)
        self.assertEqual(engine.entry_audits[-1]['risk_reason'], 'net_rr_not_above_threshold')

    def test_target_exit_and_factor_rescaling(self):
        strategy = InverseHeadShoulders('ihs', {})
        engine = Backtest(self.config(), [strategy])
        p = Position('ihs', 'X', '20250101', 14, 100, 8, 600, 5, 'id', 1,
                     dict(ihs_target=18, ihs_floor=8, ihs_neckline=13), 14)
        engine.positions['X'] = p
        engine.histories['X'] = [Bar('X', '20250101', 14, 14, 14, 14, 100)]
        engine.marks['X'] = 14
        self.assertFalse(strategy.manage_position([Bar('X', '20250102', 17, 19, 16, 17, 100)], p)[0])
        self.assertTrue(strategy.manage_position([Bar('X', '20250102', 17, 19, 16, 18, 100)], p)[0])
        engine.adjust_factors({'X': Bar('X', '20250103', 7, 7, 7, 7, 100, factor=2)}, '20250103')
        self.assertEqual(p.plan['ihs_target'], 9)
        self.assertEqual(p.plan['ihs_floor'], 4)
        self.assertEqual(p.plan['ihs_neckline'], 6.5)

    def test_parameters(self):
        for params in ({'left': True}, {'right': 0}, {'shoulder_tolerance': float('nan')},
                       {'neckline_tolerance': 1}, {'unknown': 1}):
            with self.assertRaises(ValueError):
                InverseHeadShoulders('ihs', params)

    def test_normalization_cache_matches_uncached_with_factor_changes(self):
        bars = [replace(b, factor=1.3 if i < 10 else 1.7 if i < 17 else 2.1)
                for i, b in enumerate(fixture())]
        strategy = InverseHeadShoulders('ihs', {})
        for end in range(1, len(bars) + 1):
            self.assertEqual(strategy.normalized_history(bars[:end]), adjusted(bars[:end]))
        self.assertEqual(strategy.normalized_history(bars[:9]), adjusted(bars[:9]))
        self.assertEqual(strategy.normalized_history(bars[:9]), adjusted(bars[:9]))
