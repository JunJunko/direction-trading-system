import copy
import json
import unittest
from dataclasses import replace
from datetime import datetime,timedelta
from pathlib import Path
from trading_system.domain import Bar
from trading_system.engine import Backtest
from trading_system.strategies.retest_inverse_head_shoulders import RetestInverseHeadShoulders
from test_enclosing_inverse_head_shoulders import fixture


class RetestTests(unittest.TestCase):
    def prepare(self,params=None):
        s=RetestInverseHeadShoulders('r',params or {})
        bars=fixture()
        for i in range(1,len(bars)+1):
            intents,_=s.on_close(bars[:i],set())
            self.assertFalse(intents)
        self.assertTrue(s.waiting['X'])
        return s,bars

    def add(self,s,bars,o,h,l,c,factor=1):
        date=(datetime.strptime(bars[-1].date,'%Y%m%d')+timedelta(days=1)).strftime('%Y%m%d')
        bars.append(Bar('X',date,o,h,l,c,100,factor))
        return s.on_close(bars,set())

    def signal(self):
        s,bars=self.prepare()
        self.add(s,bars,13.3,13.4,13.08,13.15)
        intents,events=self.add(s,bars,13.15,13.3,13.1,13.22)
        self.assertEqual(len(intents),1)
        return s,bars,intents[0]

    def test_retest_after_breakout_only_and_original_bracket(self):
        s,bars,i=self.signal()
        self.assertLess(i.evidence['ihs_known_at'],i.evidence['ihs_retest_date'])
        self.assertEqual(i.stop,9.9)
        self.assertAlmostEqual(i.target,18.3)
        self.assertEqual(i.evidence['entry_mode'],'ihs_retest')
        self.assertFalse(s.on_close(bars,set())[0])
        self.assertFalse(self.add(s,bars,13.2,13.4,13.1,13.3)[0])

    def test_failures_and_expiry(self):
        for low,high,params,reason in [(12.7,13.3,{},'neckline_retest_failed'),
                (9.8,13.3,{},'right_shoulder_broken'),(7.8,13.3,{},'head_broken'),
                (13.1,19,{},'target_already_touched')]:
            s,b=self.prepare(params)
            intents,ev=self.add(s,b,13.2,high,low,13.25)
            self.assertFalse(intents)
            self.assertTrue(any(e.get('reason')==reason for e in ev),ev)
        s,b=self.prepare({'retest_sessions':1})
        self.add(s,b,14,14.1,13.8,13.9)
        intents,ev=self.add(s,b,13.2,13.4,13.1,13.3)
        self.assertFalse(intents)
        self.assertTrue(any(e.get('reason')=='expired' for e in ev))

    def test_does_not_buy_without_touch_or_chase(self):
        s,b=self.prepare()
        self.assertFalse(self.add(s,b,14,14.3,13.8,14.2)[0])
        self.assertFalse(self.add(s,b,13.2,14.6,13.1,14.5)[0])

    def test_factor_change_during_wait(self):
        s,b=self.prepare()
        self.add(s,b,6.65,6.7,6.54,6.575,2)
        intents,_=self.add(s,b,6.575,6.65,6.55,6.61,2)
        self.assertEqual(len(intents),1)
        self.assertAlmostEqual(intents[0].stop,4.95)
        self.assertAlmostEqual(intents[0].target,9.15)

    def test_prefix_outputs_equal(self):
        _,bars,_=self.signal()
        def replay(end):
            s=RetestInverseHeadShoulders('r',{})
            return [s.on_close(bars[:i],set()) for i in range(1,end+1)]
        full=replay(len(bars))
        for end in range(1,len(bars)+1):self.assertEqual(replay(end),full[:end])

    def test_execution_open_checks_and_rebase(self):
        _,bars,i=self.signal()
        config=json.loads(Path('configs/experiments/inverse_head_shoulders_v3_retest.json').read_text())
        # Isolate open guards from the unchanged RR filter.
        for opening,expected in [(13.09,'ihs_neckline_lost_at_open'),(13.5,'ihs_retest_entry_too_far'),(13.2,'filled')]:
            e=Backtest(copy.deepcopy(config),[])
            e.config['strategies']=[]
            # owners only needed for ordering; interval uses strategy names.
            e.strategies=[type('Owner',(),{'name':'r'})()]
            e.pending=[replace(i,target=30)]
            day='20260201';bar=Bar('X',day,opening,opening+.2,opening-.05,opening+.1,100)
            e.execute_interval({'X':bar},day,None,e.cash)
            self.assertEqual(e.entry_audits[-1]['execution_reason'],expected)
        e=Backtest(copy.deepcopy(config),[]);e.pending=[i]
        e.histories['X']=bars.copy();e.marks['X']=bars[-1].close
        bar=Bar('X','20260201',6.6,6.7,6.5,6.6,100,2)
        e.adjust_factors({'X':bar},bar.date)
        self.assertAlmostEqual(e.pending[0].evidence['ihs_entry_ceiling'],i.evidence['ihs_entry_ceiling']/2)

    def test_invalid_parameters(self):
        for p in ({'retest_sessions':True},{'touch_tolerance':float('nan')},
                  {'touch_tolerance':.03,'max_neckline_distance':.02}):
            with self.assertRaises(ValueError):RetestInverseHeadShoulders('r',p)
