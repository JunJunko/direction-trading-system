import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.analysis import pivot_lows,weekly
from trading_system.domain import Bar
from trading_system.strategies.double_bottom import DoubleBottom,Setup
from trading_system.demo import demo_data
from trading_system.engine import Backtest
from trading_system.strategies import build_strategies
import json


def history(closes):
    return [Bar('X',f'202401{i+1:02d}',c-.02,c+.05,c-.05,c,100)
            for i,c in enumerate(closes)]


class EdgeTests(unittest.TestCase):
    def test_v4_full_pipeline_and_prefix_invariance(self):
        config=json.loads((Path(__file__).resolve().parents[1]/'configs/experiments/double_bottom_v4.json').read_text(encoding='utf-8'))
        bars,calendar,ends=demo_data()
        def run(cut):
            return Backtest(config,build_strategies(config['strategies'])).run(
                [b for b in bars if b.date<=cut],[d for d in calendar if d<=cut],ends)
        full=run(calendar[-1])
        # A longer, fully bounded pullback delays this scripted example's entry.
        # Do not relax RR or truncate the pullback to preserve v3 demo trades.
        self.assertEqual(len(full.entry_audits),2)
        self.assertEqual(full.summary()['filled_buys'],0)
        self.assertTrue(all(a['net_rr']<3 for a in full.entry_audits))
        self.assertTrue(any(a['execution_reason']=='net_rr_not_above_threshold'
                            for a in full.entry_audits))
        for cut in (calendar[94],calendar[96],calendar[98],calendar[100]):
            short=run(cut)
            self.assertEqual(short.events,[e for e in full.events if e['date']<=cut])
            self.assertEqual(short.orders,[o for o in full.orders if o['date']<=cut])

    def test_v4_suspended_breakout_is_actionable_on_resume(self):
        start=date(2024,1,5)
        closes=[16,15,14,12,10,11,12,11.2,10.1,12.4,12.6]
        ends={(start+timedelta(weeks=i)).strftime('%Y%m%d') for i in range(13)}
        bars=[]
        s=DoubleBottom('v4',{'rule_version':'v4'})
        events=[]
        for i,c in enumerate(closes):
            d=start+timedelta(weeks=i,days=-1 if i==10 else 0)
            bars.append(Bar('X',d.strftime('%Y%m%d'),c-.02,c+.05,c-.05,c,100))
            _,e=s.on_close(bars,ends)
            events.extend(e)
        self.assertEqual(events,[])
        bars.append(Bar('X','20240318',12.6,12.8,12.5,12.7,100))
        _,e=s.on_close(bars,ends)
        self.assertEqual(e[0]['event'],'double_bottom_breakout')
        self.assertEqual(e[0]['date'],'20240318')
        self.assertEqual(e[0]['actionable_direction_bar'],'20240315')
        self.assertEqual(s.on_close(bars,ends),([],[]))

    def test_v4_rising_neckline_touch_is_not_pullback(self):
        s=DoubleBottom('v4',{'rule_version':'v4'})
        s.active['X']=Setup('id',12,10,'20240101',age=3)
        bars=[Bar('X','20240101',12,12.1,12,12.05,100)]
        for day,c in [('20240102',12.1),('20240103',12.3),('20240104',12.4)]:
            bars.append(Bar('X',day,c-.1,c+.05,12.05,c,100))
            intents,events=s.on_close(bars,set())
            self.assertEqual(intents,[])
            self.assertFalse(any(e['event']=='retest_observed' for e in events))

    def test_v4_pullback_duration_and_stop_include_whole_pullback(self):
        s=DoubleBottom('v4',{'rule_version':'v4'})
        s.active['X']=Setup('id',12,10,'20240101',age=10)
        bars=[Bar('X','20240101',12.7,12.8,12.6,12.7,100)]
        # The setup's age must not substitute for three completed pullback bars.
        for day,op,hi,lo,c in [
            ('20240102',12.7,12.75,11.8,12.4),
            ('20240103',12.4,12.5,12.0,12.2),
            ('20240104',12.2,12.85,12.1,12.8),
        ]:
            bars.append(Bar('X',day,op,hi,lo,c,100))
            intents,_=s.on_close(bars,set())
            self.assertEqual(intents,[])
        bars.append(Bar('X','20240105',12.8,13.1,12.7,13.0,100))
        intents,_=s.on_close(bars,set())
        self.assertEqual(len(intents),1)
        self.assertAlmostEqual(intents[0].stop,11.8*.995)

    def test_breakout_during_second_bottom_confirmation(self):
        bars=history([16,15,14,12,10,11,12,11.2,10.1,12.4,12.6])
        strategy=DoubleBottom('edge',{'direction_cycle':'daily'})
        _,before=strategy.on_close(bars[:-1],set())
        self.assertEqual(before,[])
        _,confirmed=strategy.on_close(bars,set())
        self.assertTrue(any(e['event']=='double_bottom_breakout' for e in confirmed))
        self.assertEqual(confirmed[-1]['date'],'20240111')

    def test_minimum_history_has_no_extra_bar_delay(self):
        bars=history([14,13,10,12,11,10.1,11,12.5])
        strategy=DoubleBottom('edge',{'direction_cycle':'daily'})
        _,events=strategy.on_close(bars,set())
        self.assertTrue(any(e['event']=='double_bottom_breakout' for e in events))

    def test_flat_trough_confirmed_only_after_plateau_end(self):
        bars=history([9,8,7,7,8,9])
        self.assertEqual(pivot_lows(bars[:-1],2,2),[])
        self.assertEqual(pivot_lows(bars,2,2),[3])

    def test_suspended_week_end_does_not_delete_whole_week(self):
        bars=history([10,11,12,13])
        bars=[Bar(b.symbol,f'2024010{i+1}',b.open,b.high,b.low,b.close,b.volume)
              for i,b in enumerate(bars)]
        self.assertEqual(weekly(bars,{'20240105'}),[])
        bars.append(Bar('X','20240108',13,14,12,13.5,100))
        weeks=weekly(bars,{'20240105','20240112'})
        self.assertEqual(len(weeks),1)
        self.assertEqual(weeks[0].date,'20240105')
        self.assertEqual(weeks[0].close,13)

    def test_invalid_geometry_parameters_rejected(self):
        for params in ({'min_separation':1},{'right':0},{'max_retest_days':0},
                       {'bottom_tolerance':-1},{'left':1.5},{'typo_parameter':1},
                       {'rule_version':'invalid'}):
            with self.subTest(params=params),self.assertRaises(ValueError):
                DoubleBottom('bad',params)

    def test_intraday_new_low_invalidates_original_bottom(self):
        strategy=DoubleBottom('edge',{})
        strategy.active['X']=Setup('id',12,10,'20240101',age=3)
        bar=Bar('X','20240102',12.1,12.3,9.8,12.05,100)
        intents,events=strategy.on_close([bar],set())
        self.assertEqual(intents,[])
        self.assertEqual(events[0]['reason'],'bottom_broken')
        self.assertNotIn('X',strategy.active)

    def test_deep_intraday_recovery_is_not_near_neckline_retest(self):
        strategy=DoubleBottom('edge',{})
        strategy.active['X']=Setup('id',12,10,'20240101',age=3)
        bar=Bar('X','20240102',12.1,12.3,11,12.05,100)
        _,events=strategy.on_close([bar],set())
        self.assertFalse(any(e['event']=='retest_observed' for e in events))
        self.assertIsNone(strategy.active['X'].retest_index)

    def test_same_close_is_idempotent_and_factor_is_rescaled_once(self):
        strategy=DoubleBottom('edge',{})
        strategy.active['X']=Setup('id',12,10,'20240101',price_factor=1)
        bars=[Bar('X','20240101',12,13,11,12,100,1),
              Bar('X','20240102',6.1,6.3,6,6.2,100,2)]
        strategy.on_close(bars,set())
        setup=strategy.active['X']
        self.assertEqual(setup.neckline,6)
        self.assertEqual(setup.age,1)
        self.assertEqual(strategy.on_close(bars,set()),([],[]))
        self.assertEqual(setup.neckline,6)
        self.assertEqual(setup.age,1)

    def test_delayed_confirmation_signals_are_prefix_invariant(self):
        bars=history([16,15,14,12,10,11,12,11.2,10.1,12.4,12.6,12.3,12.1,12.2])
        def stream(end):
            s=DoubleBottom('edge',{'direction_cycle':'daily'})
            events=[]
            for i in range(end):
                _,e=s.on_close(bars[:i+1],set())
                events.extend(e)
            return events
        full=stream(len(bars))
        for cut in (9,10,11,12):
            self.assertEqual(stream(cut),[e for e in full if e['date']<=bars[cut-1].date])


if __name__=='__main__':
    unittest.main()
