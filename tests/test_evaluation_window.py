import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar,Intent
from trading_system.engine import Backtest


class Fixture:
    name='fixture'
    def on_close(self,history,week_ends):
        b=history[-1]
        intents=[Intent(self.name,b.symbol,b.date,10.01,9.8,12,'id:'+b.date,'fixture')]
        return intents,[dict(date=b.date,symbol=b.symbol,strategy=self.name,event='fixture_signal')]
    def trailing_stop(self,history,position):
        return position.stop


class EvaluationWindowTests(unittest.TestCase):
    def run_window(self,end='20240104'):
        config=json.loads((Path(__file__).resolve().parents[1]/'configs/double_bottom_v3.json').read_text())
        bars=[Bar('X',day,10,10.2,9.95,10.1,100) for day in
              ('20240101','20240102','20240103','20240104')]
        return Backtest(config,[Fixture()]).run(bars,[b.date for b in bars],set(),
                                               evaluation_start='20240102',evaluation_end=end)

    def test_warmup_does_not_trade_or_carry_previous_intents(self):
        engine=self.run_window()
        self.assertEqual([e['date'] for e in engine.warmup_events],['20240101'])
        self.assertEqual(engine.orders[0]['date'],'20240103')
        self.assertTrue(all(e['date']>='20240102' for e in engine.events))
        self.assertEqual(engine.curve[0]['date'],'20240102')
        self.assertEqual(engine.curve[0]['equity'],engine.config['initial_cash'])
        self.assertEqual(len(engine.histories['X']),4)

    def test_evaluation_end_does_not_process_future_observations(self):
        full=self.run_window()
        short=self.run_window('20240103')
        self.assertEqual(short.events,[e for e in full.events if e['date']<='20240103'])
        self.assertEqual(short.orders,[o for o in full.orders if o['date']<='20240103'])
        self.assertEqual(short.curve,[r for r in full.curve if r['date']<='20240103'])
        self.assertEqual(len(short.histories['X']),3)


if __name__=='__main__':
    unittest.main()
