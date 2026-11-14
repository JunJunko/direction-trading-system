import json
import sys
import unittest
from dataclasses import replace
from datetime import date,timedelta
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.account import PhasePolicy
from trading_system.analysis import weekly
from trading_system.domain import Bar,Intent,Position,ExitIntent
from trading_system.engine import Backtest
from trading_system.structure import double_bottom,n_structure,rhythm
from trading_system.strategies import build_strategies
from trading_system.strategies.direction_double_bottom import DirectionDoubleBottom


def stage(**changes):
    row=dict(id='synthetic-stage',known_at='20231231',effective_from='20240101',expires='20261231',
             market_state='uptrend',system_matched=True,gross_limit=.5,
             allow_win_expansion=False,allow_cycle_upgrade=False,allow_same_level=False,
             reason='Synthetic fixture only, not a historical market assessment')
    row.update(changes)
    return row


def config(stages=None):
    c=json.loads((Path(__file__).resolve().parents[1]/'configs/double_bottom_v3.json').read_text())
    c['account_policy']=dict(stages=[stage()] if stages is None else stages)
    c['strategies']=[dict(type='direction_double_bottom',id='direction_v5',params={'lower_cycle':'daily_nested'})]
    return c


def reversal_data():
    values=[29,29.5,30,29,28,27,27.5,28,29,27.5,25,23,24,25,26,23,21,19,20,21,22,
            19,17,15,16,17,18,15,12,10,11,12,12.3,11.5,10.5,10.1,11,12,13,
            12.8,12.6,12.7,13.4]
    start=date(2024,1,5)
    bars=[Bar('X',(start+timedelta(weeks=i)).strftime('%Y%m%d'),c-.03,c+.05,c-.05,c,
              200 if i>=35 else 100) for i,c in enumerate(values)]
    ends={b.date for b in bars}
    return bars,ends


def core_data(start=date(2024,1,1),offset=0):
    values=[10.8,10.4,10,10.5,11,11.8,12.6,13.4,14,13.6,13,12.5,12,12.3,12.7,13,12.9,12.8,13.2,13.4]
    dates=[]
    day=start
    while len(dates)<len(values):
        if day.weekday()<5:
            dates.append(day.strftime('%Y%m%d'))
        day+=timedelta(days=1)
    return [Bar('X',d,c+offset-.02,c+offset+.05,c+offset-.05,c+offset,100) for d,c in zip(dates,values)]


class StructureTests(unittest.TestCase):
    def test_reversal_requires_trend_area_match_and_volume(self):
        bars,_=reversal_data()
        candidate,reason=double_bottom(bars[:39])
        self.assertIsNotNone(candidate,reason)
        self.assertGreater(candidate['pattern_area'],candidate['prior_area'])
        self.assertGreater(candidate['right_volume'],candidate['left_volume'])
        flat=[replace(b,volume=100) for b in bars[:39]]
        self.assertEqual(double_bottom(flat)[1],'right_side_volume_not_stronger')
        # Identical W after a sideways backdrop is not the same reversal.
        sideways=[replace(b,high=max(b.high,31)) for b in bars[:29]]+bars[29:39]
        self.assertIsNone(double_bottom(sideways)[0])

    def test_small_n_and_target_share_daily_core(self):
        bars=core_data()
        core,reason=n_structure(bars)
        self.assertIsNotNone(core,reason)
        small,reason=rhythm(bars,core)
        self.assertIsNotNone(small,reason)
        self.assertLess(small['small_area'],core['correction_area'])
        self.assertEqual(core['target'],bars[core['c']].low+core['impulse'])
        self.assertIsNone(rhythm(bars[:17],core)[0])

    def test_weekly_confirmation_is_separate_from_breakout(self):
        bars,ends=reversal_data()
        s=DirectionDoubleBottom('v5',{'lower_cycle':'daily_nested'})
        events=[]
        for i in range(len(bars)):
            intents,e=s.on_close(bars[:i+1],ends)
            self.assertEqual(intents,[])
            events.extend(e)
            if i==38:
                self.assertNotEqual(s.states['X']['direction'],'long')
        confirms=[e for e in events if e['event']=='upper_direction_confirmed']
        self.assertEqual(len(confirms),1)
        self.assertEqual(confirms[0]['date'],bars[-1].date)
        self.assertEqual(confirms[0]['weekly_retest_bars'],3)

    def test_entry_uses_core_target_and_nearer_pressure(self):
        bars=core_data()
        s=DirectionDoubleBottom('v5',{'lower_cycle':'daily_nested'})
        s.states['X']=dict(direction='long',processed='',pending=None,factor=1,floor=9,confirmed_date='20240101')
        intents,_=s.on_close(bars,set())
        self.assertEqual(len(intents),1)
        intent=intents[0]
        self.assertEqual(intent.evidence['target_cycle'],'daily')
        self.assertAlmostEqual(intent.target,16.05)
        self.assertAlmostEqual(intent.stop,12.75*.995)
        self.assertEqual(s.on_close(bars,set()),([],[]))


class AccountTests(unittest.TestCase):
    def test_missing_expired_and_future_stage_block_entries(self):
        p=PhasePolicy(dict(stages=[]))
        self.assertFalse(p.observe('20240101',100)['allow_entries'])
        p=PhasePolicy(dict(stages=[stage(effective_from='20240201',known_at='20240131',expires='20240228')]))
        self.assertFalse(p.observe('20240130',100)['allow_entries'])
        self.assertTrue(p.observe('20240201',100)['allow_entries'])
        self.assertFalse(p.observe('20240301',100)['allow_entries'])

    def test_contraction_sticky_capped_and_carried_to_next_year(self):
        p=PhasePolicy(dict(stages=[stage()]))
        p.observe('20240101',100)
        self.assertEqual(p.observe('20240201',97)['contraction_steps'],1)
        self.assertEqual(p.observe('20240301',94)['contraction_steps'],2)
        self.assertEqual(p.observe('20240401',90)['contraction_steps'],3)
        self.assertEqual(p.observe('20240501',110)['contraction_steps'],3)
        self.assertEqual(p.observe('20250101',110)['contraction_steps'],3)
        self.assertAlmostEqual(p.context['multiplier'],.8*.75**3)

    def test_win_requires_profit_and_manual_permission_and_resets(self):
        p=PhasePolicy(dict(stages=[stage(allow_win_expansion=True,allow_same_level=True)]))
        p.observe('20240101',100)
        self.assertFalse(p.observe('20240201',105)['win_expansion'])
        self.assertTrue(p.observe('20240301',111)['win_expansion'])
        self.assertTrue(p.context['allow_same_level'])
        self.assertLessEqual(p.context['multiplier'],1)
        self.assertFalse(p.observe('20250101',111)['win_expansion'])
        p=PhasePolicy(dict(stages=[stage()]))
        p.observe('20240101',100)
        self.assertFalse(p.observe('20240301',150)['win_expansion'])

    def test_probe_expansion_requires_actual_protected_profit(self):
        c=config()
        p=PhasePolicy(c['account_policy'])
        p.observe('20240101',1e6)
        limited=p.limits(c['risk'],1e6,{}, {})
        self.assertAlmostEqual(limited['max_gross_weight'],.08)
        position=Position('s','X','20240101',10,1000,9,1000,5,'id',1)
        protected=p.limits(c['risk'],1e6,{'X':position},{'X':12})
        self.assertAlmostEqual(protected['max_gross_weight'],.4)

    def test_invalid_or_lookahead_stage_rejected(self):
        for row in [stage(known_at='20240101'),stage(gross_limit=float('nan')),stage(system_matched='yes')]:
            with self.assertRaises(ValueError):
                PhasePolicy(dict(stages=[row]))


class ExecutionTests(unittest.TestCase):
    def test_complete_direction_core_entry_and_causal_replay(self):
        bars,ends=reversal_data()
        next_day=date.fromisoformat(f'{bars[-1].date[:4]}-{bars[-1].date[4:6]}-{bars[-1].date[6:]}')+timedelta(days=3)
        core=core_data(next_day,10)
        # Core signal gets a next-day fill, then a deliberately failing small N.
        tail=Bar('X',(next_day+timedelta(days=28)).strftime('%Y%m%d'),23.5,23.7,23.4,23.6,100)
        loss=replace(tail,date=(next_day+timedelta(days=29)).strftime('%Y%m%d'),open=22.5,high=22.6,low=22.3,close=22.4)
        bars=bars+core+[tail,loss]
        calendar=sorted({b.date for b in bars})
        # Include all genuine Friday closes, including those in the daily tail.
        ends|={d for d in calendar if date.fromisoformat(f'{d[:4]}-{d[4:6]}-{d[6:]}').weekday()==4}
        def run(cut):
            c=config()
            return Backtest(c,build_strategies(c['strategies'])).run(
                [b for b in bars if b.date<=cut],[d for d in calendar if d<=cut],ends)
        full=run(calendar[-1])
        self.assertTrue(any(e['event']=='upper_direction_confirmed' for e in full.events))
        self.assertTrue(full.entry_audits)
        self.assertEqual(full.summary()['filled_buys'],1)
        self.assertEqual(len(full.trades),1)
        self.assertLess(full.trades[0]['pnl'],0)
        for cut in (calendar[38],calendar[42],calendar[50],calendar[-3]):
            short=run(cut)
            self.assertEqual(short.events,[e for e in full.events if e['date']<=cut])
            self.assertEqual(short.orders,[o for o in full.orders if o['date']<=cut])
        self.assertTrue(all(r['cash']>=0 for r in full.curve))

    def test_exit_intent_survives_suspension_and_locked_down(self):
        class Fixture:
            name='fixture'
            def on_close(self,*args): return [],[]
            def trailing_stop(self,h,p): return p.stop
        e=Backtest(config(),[Fixture()])
        e.positions['X']=Position('fixture','X','20240101',10,100,7,100,5,'id',1)
        e.marks['X']=10
        e.pending_exits=[ExitIntent('fixture','X','20240101','id','core_top_confirmed')]
        bars=[Bar('X','20240103',8,8,8,8,100,1,12,8),Bar('X','20240104',8.1,8.4,8,8.3,100)]
        e.run(bars,['20240102','20240103','20240104'],set())
        self.assertEqual(len(e.trades),1)
        self.assertEqual(e.trades[0]['reason'],'core_top_confirmed')
        self.assertEqual(e.trades[0]['exit_date'],'20240104')

    def test_phase_and_volatility_gates(self):
        intent=Intent('fixture','X','20240101',12,11.8,15,'id','test',dict(volatility=.10))
        e=Backtest(config([]),[])
        e.refresh_context('20240102')
        self.assertEqual(e.assess_entry(intent,12,1e6,1e6,{},'20240102')['risk_reason'],'phase_entry_gate_closed')
        e=Backtest(config(),[])
        e.refresh_context('20240102')
        result=e.assess_entry(intent,12,1e6,1e6,{},'20240102')
        self.assertGreater(result['quantity'],0)
        self.assertLessEqual(result['quantity']*12*.10,1e6*.002*.8)

    def test_adjustment_expansion_exit_and_stop_never_lowered(self):
        bars=core_data()
        s=DirectionDoubleBottom('v5',{})
        s.states['X']=dict(direction='long')
        p=Position('v5','X',bars[10].date,12,100,11,100,5,'id',1,
                   dict(correction_area=.1,correction_duration=1,correction_range=.1))
        exits,_=s.manage_position(bars,p)
        self.assertTrue(exits)
        self.assertEqual(exits[0].reason,'core_adjustment_expanded')
        self.assertGreaterEqual(s.trailing_stop(bars,p),p.stop)


if __name__=='__main__':
    unittest.main()
