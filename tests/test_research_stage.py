import copy
from dataclasses import replace
from datetime import date,timedelta
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'scripts'))
from research_stage_core import (event_from_prefix,match_events,path_outcome,
    summarize_contrast,simple_protection,cluster_interval)
from run_research_stage import upper_replay,import_review,dump,sha
from trading_system.domain import Bar
from trading_system.analysis import adjusted
from trading_system.structure import SwingCache
from test_direction_system import core_data,reversal_data


def protocol():
    return json.loads((ROOT/'configs/research/next_stage_v1.json').read_text(encoding='utf-8'))


def event(identity,weekly,**changes):
    e=dict(event_id=identity,symbol=identity,exchange='SH',date='20260105',weekly=weekly,
           zone=False,trigger=True,return20=.03,atr_pct=.02,log_turnover=15)
    e.update(changes)
    return e


class ResearchStageTests(unittest.TestCase):
    def test_matching_is_outcome_blind_and_no_control_reuse(self):
        es=[event('A',True),event('B',True),event('C',False),event('D',False,return20=.04)]
        before=match_events(es,'weekly',protocol())
        changed=copy.deepcopy(es)
        for i,e in enumerate(changed):e.update(future_return=1000*(-1)**i,trade_pnl=-9999*i)
        self.assertEqual(before,match_events(list(reversed(changed)),'weekly',protocol()))
        self.assertEqual(len(before),2)
        self.assertEqual(len({p['control'] for p in before}),2)

    def test_exact_context_and_calipers_are_required(self):
        es=[event('A',True),event('B',False,date='20260106'),event('C',False,zone=True),
            event('D',False,exchange='SZ'),event('E',False,return20=.2)]
        self.assertEqual(match_events(es,'weekly',protocol()),[])

    def test_latest_n_requires_causal_confirmation_and_actual_floor(self):
        prefix=[Bar('X',(date(2023,11,1)+timedelta(days=i)).strftime('%Y%m%d'),11,11.1,10.9,11,100) for i in range(30)]
        bars=prefix+core_data()[:15]
        p=protocol();p['minimum_history']=21
        cache=SwingCache(2,2);points=cache.get(bars)
        e=event_from_prefix(bars,points,cache.ambiguous,p)
        self.assertIsNotNone(e)
        self.assertEqual(e['c_confirmed'],bars[-1].date)
        shorter=bars[:-1];cache=SwingCache(2,2)
        self.assertIsNone(event_from_prefix(shorter,cache.get(shorter),cache.ambiguous,p))
        future=bars+[replace(bars[-1],date='20990101',low=.1,high=1000,close=900)]
        known=[b for b in future if b.date<=e['date']];cache=SwingCache(2,2)
        self.assertEqual(e,event_from_prefix(known,cache.get(known),cache.ambiguous,p))

    def test_outcomes_freeze_event_atr_and_factor_not_future_signal(self):
        ev=dict(date='20260101',factor=1,close=100,atr=2)
        b=Bar('X','20260102',50,52,49,51,100,factor=2)
        out=path_outcome(ev,{b.date:b},['20260101','20260102'],[1,2])
        self.assertEqual(out['1']['change_atr'],1)
        self.assertEqual(out['1']['mfe_atr'],2)
        self.assertEqual(out['1']['mae_atr'],-1)
        self.assertEqual(out['2']['status'],'immature')

    def test_missing_endpoint_is_not_replaced_by_later_price(self):
        ev=dict(date='20260101',factor=1,close=100,atr=2)
        b=Bar('X','20260103',100,110,99,109,100)
        out=path_outcome(ev,{b.date:b},['20260101','20260102','20260103'],[1])
        self.assertEqual(out['1']['status'],'missing_endpoint')
        self.assertIsNone(out['1']['change_atr'])

    def test_missing_pairs_stay_in_registered_denominator(self):
        es=[event('A',True),event('C',False)]
        pairs=match_events(es,'weekly',protocol())
        outcomes={e['event_id']:{str(h):dict(status='immature',change_atr=None) for h in (5,10,20)} for e in es}
        result=summarize_contrast(es,pairs,outcomes,'weekly',protocol())
        self.assertEqual(result['pairs'],1)
        self.assertEqual(result['complete_pairs'],0)
        self.assertEqual(result['conclusion'],'insufficient_coverage')
        self.assertEqual(result['clipped_10atr_missing_sensitivity'],[-20,20])

    def test_single_time_cluster_has_no_invented_interval(self):
        self.assertIsNone(cluster_interval([1,2],['202601','202601'],1,100))

    def test_simple_protection_cannot_use_unconfirmed_trough_and_exit_wins(self):
        from test_autonomous_system import AutonomousTests
        _,position,bars=AutonomousTests().fixture()
        s=SimpleNamespace(p=dict(left=2,right=2,stop_buffer=.005),
            event=lambda b,kind,**kw:dict(date=b.date,event=kind,**kw))
        method=simple_protection(lambda *args:([],[]))
        method(s,bars[:9],position);self.assertEqual(position.stop,9)
        method(s,bars[:10],position);self.assertGreater(position.stop,12)
        previous=position.stop
        method(s,bars,position);self.assertGreaterEqual(position.stop,previous)
        method=simple_protection(lambda *args:([object()],[]))
        position.stop=9;method(s,bars,position);self.assertEqual(position.stop,9)

    def test_weekly_extraction_matches_original_direction_events(self):
        from trading_system.strategies.direction_double_bottom import DirectionDoubleBottom
        bars,ends=reversal_data()
        params=dict(lower_cycle='daily_nested',structure_mode='hierarchy',candidate_mode='pool',retest_mode='boundary')
        states,events=upper_replay(bars,ends,params)
        original=DirectionDoubleBottom('reference',params);expected=[]
        for i in range(len(bars)):
            _,es=original.on_close(bars[:i+1],ends)
            expected.extend(e for e in es if e['event'] in ('upper_direction_confirmed','upper_direction_lost'))
            self.assertEqual(states[bars[i].date],original.states['X']['direction']=='long')
        key=lambda e:(e['date'],e['event'],e.get('candidate_id'))
        self.assertEqual(list(map(key,events)),list(map(key,expected)))

    def test_review_import_rejects_wrong_case_hash_and_does_not_create_labels(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);dump(out/'blind-cases.json',[dict(case_id='N001',as_of='20260101')])
            payload=dict(run=out.name,case_hash='wrong',reviewer='test',labels={})
            export=out/'export.json';dump(export,payload)
            with self.assertRaises(ValueError):import_review(out,export)
            payload['case_hash']=sha(out/'blind-cases.json');dump(export,payload)
            import_review(out,export)
            result=json.loads((out/'review-import.json').read_text())
            self.assertEqual(result['completed_in_this_file'],0)
            self.assertEqual(result['independent_reviewer_attestations'],0)


if __name__=='__main__':unittest.main()
