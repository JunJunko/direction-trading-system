import sys,json,unittest
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from test_direction_system import core_data
from trading_system.strategies.direction_double_bottom import DirectionDoubleBottom
from trading_system.engine import Backtest

class LifecycleTests(unittest.TestCase):
    def fixture(self):
        s=DirectionDoubleBottom('fresh',dict(lower_cycle='daily_nested',entry_lifecycle='fresh'))
        s.states['X']=dict(direction='long',processed='',pending=None,factor=1,floor=9,confirmed_date='20240101')
        bars=core_data()
        intent=s.on_close(bars,set())[0][0]
        return s,bars,intent

    def test_warmup_reset_preserves_direction_and_consumed_identity(self):
        s,bars,intent=self.fixture()
        events=s.begin_evaluation('20240129')
        self.assertFalse(s.opportunities)
        self.assertIn(intent.setup_id,s.seen)
        self.assertEqual(s.states['X']['direction'],'long')
        self.assertEqual(events[0]['reason'],'warmup_plan_not_executable')
        tail=replace(bars[-1],date='20240129',high=13.3,low=13,close=13.2)
        intents,_=s.on_close(bars+[tail],set())
        self.assertFalse(any(i.setup_id==intent.setup_id for i in intents))

    def test_rejected_first_trigger_cannot_be_retried(self):
        s,bars,intent=self.fixture()
        tail=replace(bars[-1],date='20240129',high=intent.trigger+.1,low=intent.stop+.1,close=intent.trigger-.01)
        intents,events=s.on_close(bars+[tail],set())
        self.assertFalse(any(i.setup_id==intent.setup_id for i in intents))
        self.assertTrue(any(e.get('reason')=='trigger_consumed' for e in events))
        self.assertNotIn('X',s.opportunities)

    def test_untouched_plan_remains_executable(self):
        s,bars,intent=self.fixture()
        tail=replace(bars[-1],date='20240129',high=intent.trigger-.01,low=intent.stop+.1,close=intent.trigger-.02)
        intents,_=s.on_close(bars+[tail],set())
        self.assertEqual(intents[0].setup_id,intent.setup_id)

    def test_engine_calls_boundary_hook_before_first_evaluation_close(self):
        s,bars,intent=self.fixture()
        # A warmed detector has already planned; a flat account may not adopt it.
        config=json.loads((Path(__file__).resolve().parents[1]/'configs/double_bottom_v3.json').read_text())
        tail=replace(bars[-1],date='20240129',high=13.3,low=13,close=13.2)
        config['research_scope']='structure_only'
        engine=Backtest(config,[s]).run([tail],[tail.date],set(),evaluation_start=tail.date)
        self.assertTrue(any(e.get('reason')=='warmup_plan_not_executable' for e in engine.events))
        self.assertFalse(engine.pending)

if __name__=='__main__':unittest.main()

