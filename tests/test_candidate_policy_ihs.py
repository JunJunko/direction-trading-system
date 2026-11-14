
import unittest
from dataclasses import replace
from types import SimpleNamespace

from trading_system.domain import Bar
from trading_system.engine import Backtest
from trading_system.strategies.candidate_policy_ihs import CandidatePolicyIHS
from test_breakout_trend_ihs import BreakoutTests


class CandidatePolicyTests(unittest.TestCase):
    def candidates(self):
        intent = BreakoutTests().intent()
        def layout(indices, area):
            result = {key: SimpleNamespace(index=index) for key, index in
                      zip(('left', 'peak1', 'head', 'peak2', 'right'), indices)}
            return dict(result, area=area)
        return [(replace(intent, setup_id='large'), layout([0, 1, 200, 400, 402], 1000)),
                (replace(intent, setup_id='balanced'), layout([350, 355, 370, 385, 390], 100))]

    def test_ranking_and_consumption_are_independent(self):
        bar = Bar('X', '20250115', 10, 11, 9, 10, 100)
        for rank, expected in [('area', 'large'), ('time_balance', 'balanced')]:
            for policy in ('all', 'selected', 'fallback'):
                strategy = CandidatePolicyIHS('v5', dict(candidate_ranking=rank, candidate_consumption=policy))
                intents, events = strategy.select_candidates(self.candidates(), bar)
                self.assertEqual(intents[0].setup_id, expected)
                self.assertEqual(len(intents), 2 if policy == 'fallback' else 1)
                self.assertEqual(len(strategy.seen), 1 if policy == 'selected' else 2)
                self.assertEqual(sum(e['consumed'] for e in events), len(strategy.seen))

    def test_fallback_uses_actual_open_and_does_not_duplicate_position(self):
        fixture = BreakoutTests()
        config = fixture.config()
        strategy = CandidatePolicyIHS('v5', {})
        engine = Backtest(config, [strategy])
        valid = fixture.intent()
        # The first candidate fails its structural bracket at execution.
        invalid = replace(valid, setup_id='bad', target=100)
        engine.pending = [invalid, valid, replace(valid, setup_id='third')]
        bar = Bar('X', '20250116', 10.05, 10.2, 10, 10.1, 100)
        engine.execute_interval({'X': bar}, bar.date, None, engine.cash)
        self.assertEqual(engine.positions['X'].setup_id, valid.setup_id)
        self.assertEqual(sum(o['side']=='buy' and o['status']=='filled' for o in engine.orders), 1)
        self.assertEqual(engine.entry_audits[0]['risk_reason'], 'ihs_target_not_structural')
        self.assertFalse(engine.pending)

    def test_repeated_calls_and_future_data_do_not_reemit(self):
        bars = BreakoutTests().bars()
        def replay(data):
            strategy = CandidatePolicyIHS('v5', {})
            output = []
            for n in range(1, len(data)+1):
                signals, _ = strategy.on_close(data[:n], set())
                output.extend(signals)
                self.assertEqual(strategy.on_close(data[:n], set()), ([], []))
            return output
        full = replay(bars)
        self.assertTrue(full)
        for n in (len(bars)-2, len(bars)-1, len(bars)):
            self.assertEqual(replay(bars[:n]), [i for i in full if i.date <= bars[n-1].date])
        scaled = [replace(b, open=b.open/2, high=b.high/2, low=b.low/2, close=b.close/2, factor=2) for b in bars]
        other = replay(scaled)
        self.assertEqual([i.setup_id for i in full], [i.setup_id for i in other])
        self.assertEqual(full[0].evidence['candidate_time_balance'], other[0].evidence['candidate_time_balance'])
        self.assertAlmostEqual(full[0].target/2, other[0].target)

    def test_unknown_modes_fail(self):
        for params in ({'candidate_ranking':'bad'}, {'candidate_consumption':'bad'}):
            with self.assertRaises(ValueError):
                CandidatePolicyIHS('x', params)


if __name__ == '__main__':
    unittest.main()

