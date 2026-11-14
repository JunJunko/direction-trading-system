import copy
import json
import sys
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Bar
from trading_system.engine import Backtest
from trading_system.strategies import build_strategies
from trading_system.strategies.direction_double_bottom import DirectionDoubleBottom
from test_direction_system import reversal_data,core_data


def daily_reversal():
    bars,_=reversal_data()
    days=[];day=date(2024,1,1)
    while len(days)<len(bars):
        if day.weekday()<5:days.append(day.strftime('%Y%m%d'))
        day+=timedelta(days=1)
    return [replace(b,date=d) for b,d in zip(bars,days)]


def candidate_config():
    return json.loads((ROOT/'configs/experiments/double_bottom_v5_12_daily_direction_structure.json').read_text(encoding='utf-8'))


class DailyDirectionTests(unittest.TestCase):
    def replay(self,bars,ends=None):
        s=build_strategies(candidate_config()['strategies'])[0]
        events=[];intents=[]
        for i in range(len(bars)):
            new,observed=s.on_close(bars[:i+1],ends or set())
            events.extend(observed);intents.extend(new)
        return s,events,intents

    def test_daily_breakout_waits_for_retest_and_confirms_midweek(self):
        bars=daily_reversal()
        ends={b.date for b in bars if date.fromisoformat(b.date).weekday()==4}
        s,events,_=self.replay(bars,ends)
        candidates=[e for e in events if e['event']=='daily_reversal_candidate']
        confirms=[e for e in events if e['event']=='upper_direction_confirmed']
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0]['date'],bars[38].date)
        self.assertEqual(len(confirms),1)
        self.assertEqual(confirms[0]['date'],bars[42].date)
        self.assertNotIn(confirms[0]['date'],ends)
        self.assertEqual(confirms[0]['daily_retest_bars'],3)
        self.assertEqual(s.states['X']['direction'],'long')
        self.assertFalse(any(e['event'].startswith('weekly_') or 'weekly_retest_bars' in e for e in events))
        self.assertTrue(all(e['direction_cycle']=='daily' for e in events))
        _,without_calendar,_=self.replay(bars)
        self.assertEqual(events,without_calendar)

    def test_prefixes_preserve_confirmation_dates_and_plan_causality(self):
        bars=daily_reversal()
        _,full,intents=self.replay(bars)
        for end in (35,36,37,38,39,40,42):
            s,events,short_intents=self.replay(bars[:end])
            self.assertEqual(events,[e for e in full if e['date']<=bars[end-1].date])
            self.assertEqual(short_intents,[i for i in intents if i.date<=bars[end-1].date])
            self.assertNotEqual(s.states['X']['direction'],'long')
            self.assertEqual(s.on_close(bars[:end],set()),([],[]))

    def test_daily_direction_loss_does_not_wait_for_friday(self):
        bars=daily_reversal()
        bars.append(Bar('X','20240229',9,9.2,8.8,9,100))
        s,events,_=self.replay(bars)
        losses=[e for e in events if e['event']=='upper_direction_lost']
        self.assertEqual([e['date'] for e in losses],['20240229'])
        self.assertEqual(s.states['X']['direction'],'unknown')

    def test_daily_origin_is_exact_right_bottom_instead_of_whole_week_low(self):
        bars=core_data()
        origin=bars[3].date
        for cycle,expected in (('daily',origin),('weekly',bars[2].date)):
            s=DirectionDoubleBottom('origin',dict(direction_cycle=cycle,core_mode='nested',lower_cycle='daily_nested'))
            s.states['X']=dict(direction='long',processed=bars[-1].date,pending=None,
                factor=1,floor=1,confirmed_date=origin,
                direction_source=dict(second_date=origin,candidate_id='owner'))
            with patch('trading_system.strategies.direction_double_bottom.WaveHierarchy.get',return_value=(None,'waiting',[])) as model:
                s.on_close(bars,set())
            self.assertEqual(model.call_args.kwargs['origin_date'],expected)
            self.assertEqual(s.wave_source_ids['X'],'owner')

    def test_legacy_weekly_configuration_keeps_identical_events_and_intents(self):
        config=candidate_config()
        params=config['strategies'][0]['params']
        for key in ('direction_cycle','direction_retest_min','direction_retest_max'):params.pop(key)
        implicit=build_strategies(config['strategies'])[0]
        params['direction_cycle']='weekly'
        explicit=build_strategies(config['strategies'])[0]
        bars,ends=reversal_data()
        for i in range(len(bars)):
            self.assertEqual(implicit.on_close(bars[:i+1],ends),explicit.on_close(bars[:i+1],ends))
        self.assertEqual(implicit.states,explicit.states)

    def test_direction_retest_limits_count_daily_bars(self):
        config=candidate_config()
        config['strategies'][0]['params']['direction_retest_min']=5
        s=build_strategies(config['strategies'])[0]
        bars=daily_reversal();events=[]
        for i in range(len(bars)):
            _,e=s.on_close(bars[:i+1],set());events.extend(e)
        self.assertFalse(any(e['event']=='upper_direction_confirmed' for e in events))

    def test_invalid_cycle_and_duration_are_rejected(self):
        for params in ({'direction_cycle':'hourly'}, {'direction_retest_min':True},
                       {'direction_retest_max':0}, {'direction_retest_min':15,'direction_retest_max':14}):
            with self.assertRaises(ValueError):DirectionDoubleBottom('invalid',params)
        s=DirectionDoubleBottom('legacy',{'weekly_retest_min':4,'weekly_retest_max':9})
        self.assertEqual((s.p['direction_retest_min'],s.p['direction_retest_max']),(4,9))

    def test_shared_account_prefix_replay_and_hourly_data_gate(self):
        config=candidate_config()
        bars=daily_reversal()
        # Two symbols share one account, policy and evaluation window.
        bars+= [replace(b,symbol='Y') for b in bars]
        calendar=sorted({b.date for b in bars})
        def run(cut):
            return Backtest(config,build_strategies(config['strategies'])).run(
                [b for b in bars if b.date<=cut],[d for d in calendar if d<=cut],set(),
                evaluation_start=calendar[30])
        full=run(calendar[-1]);short=run(calendar[-2])
        self.assertEqual(short.events,[e for e in full.events if e['date']<=calendar[-2]])
        self.assertEqual(short.orders,[o for o in full.orders if o['date']<=calendar[-2]])
        self.assertEqual(short.curve,full.curve[:-1])
        # A production configuration still requires the genuine hourly path.
        invalid=copy.deepcopy(config);invalid.pop('research_scope')
        with self.assertRaisesRegex(ValueError,'real hourly data'):
            Backtest(invalid,build_strategies(invalid['strategies']))
        hourly=json.loads((ROOT/'configs/experiments/double_bottom_v5_12_daily_direction.json').read_text(encoding='utf-8'))
        engine=Backtest(hourly,build_strategies(hourly['strategies'])).run(bars,calendar,set())
        self.assertEqual(engine.summary()['filled_buys'],0)
        self.assertFalse(any(e['event']=='entry_intent' for e in engine.events))


if __name__=='__main__':
    unittest.main()
