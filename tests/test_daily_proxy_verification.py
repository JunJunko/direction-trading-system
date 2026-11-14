import copy
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'scripts'))
from trading_system.domain import Bar
from trading_system.data import validate_intraday
from trading_system.risk import RiskManager
from verify_daily_proxy import recovery_candidate,plan_metrics
from verify_real_hourly_proxy import merge_hourly_session,research_engine_source


class DailyProxyTests(unittest.TestCase):
    def test_recovery_entry_preserves_qualified_floor_and_points(self):
        bars=[Bar('X','20260101',9.5,10,9,9.7,100),
              Bar('X','20260102',9.8,10.5,9.1,10.3,100)]
        small=dict(a=1,b=3,c=4,stop=9,trigger=11,confirmed_date='20260102')
        before=copy.deepcopy(small);r=recovery_candidate(bars,small)
        self.assertEqual(r['trigger'],10.5)
        self.assertEqual(r['stop'],9)
        self.assertEqual((r['a'],r['b'],r['c']),(1,3,4))
        self.assertEqual(small,before)

    def test_recovery_requires_completed_strength_and_nonfalling_low(self):
        previous=Bar('X','20260101',9.5,10,9,9.7,100)
        small=dict(stop=9,trigger=11)
        for current in [Bar('X','20260102',9.8,10.5,9.1,9.9,100),
                        Bar('X','20260102',9.8,10.5,8.9,10.3,100),
                        Bar('X','20260102',10.4,10.5,9.1,10.3,100)]:
            self.assertIsNone(recovery_candidate([previous,current],small))

    def test_recovery_does_not_chase_above_original_b(self):
        bars=[Bar('X','20260101',9.5,10,9,9.7,100),
              Bar('X','20260102',9.8,11,9.1,10.3,100)]
        self.assertIsNone(recovery_candidate(bars,dict(stop=9,trigger=11)))
        self.assertIsNone(recovery_candidate(bars,None))

    def test_daily_ohlc_cannot_identify_hourly_extreme_order(self):
        # Synthetic proof of information loss, never used as backtest data.
        times=('103000','113000','140000','150000')
        a=[(10,10.5,9,10),(10,12,9.8,11.5),(11.5,11.7,10.8,11.2),(11.2,11.3,10.9,11)]
        b=[(10,12,9.8,11.6),(11.6,11.7,10.5,10.8),(10.8,11,9,9.5),(9.5,11.1,9.4,11)]
        paths=[[Bar('X','20260105'+t,o,h,l,c,100) for t,(o,h,l,c) in zip(times,values)] for values in (a,b)]
        for path in paths:validate_intraday(path)
        def aggregate(path):
            return (path[0].open,max(x.high for x in path),min(x.low for x in path),path[-1].close,
                    sum(x.volume for x in path))
        self.assertEqual(aggregate(paths[0]),aggregate(paths[1]))
        self.assertLess(min(range(4),key=lambda i:paths[0][i].low),max(range(4),key=lambda i:paths[0][i].high))
        self.assertGreater(min(range(4),key=lambda i:paths[1][i].low),max(range(4),key=lambda i:paths[1][i].high))

    def test_plan_diagnosis_excludes_future_higher_floors_and_factor(self):
        values=[(8.5,9,8,8.8),(10,11,9.8,10.8),(10,10.5,9.7,10),
                (9.5,10,9.2,9.6),(9.3,9.7,9,9.4),(9.7,10.2,9.4,10),
                (9.8,9.9,9.6,9.7),(9.8,10,9.7,9.9)]
        bars=[Bar('X',f'202601{i+1:02}',*v,100) for i,v in enumerate(values)]
        config=dict(initial_cash=1000000,risk=dict(risk_per_trade=.005,max_portfolio_risk=.02,
            max_position_weight=.1,max_gross_weight=.5,max_positions=5,min_rr=3),
            execution=dict(slippage=.001,commission_rate=.0003,sell_tax_after_20230828=.0005))
        p=dict(strategy='s',symbol='X',date='20260108',trigger=10.2102,stop=9.552,target=12,
            setup_id='id',reason='test',evidence=dict(core_a='20260101',core_b='20260102',
            core_c='20260105',core_accepted_at='20260107',core_c_confirmed='20260107',
            small_a='20260105',small_b='20260106',small_c='20260107',small_confirmed='20260108',
            correction_duration=3,symmetry_target=12))
        first=plan_metrics(p,bars,config,RiskManager)
        future=[Bar('X','20260109',5,5.3,4.9,5.2,100,2),Bar('X','20260110',5.2,5.5,5.1,5.3,100,2)]
        self.assertEqual(first,plan_metrics(p,bars+future,config,RiskManager))

    def test_real_auction_is_merged_without_inventing_daily_extremes(self):
        times=['09:30:00','10:30:00','11:30:00','14:00:00','15:00:00']
        rows=[dict(trade_time='2026-01-05 '+t,open=10,high=11,low=9,close=10,vol=100) for t in times]
        rows[0].update(open=8.5,high=12,low=8.5,close=12)
        before=copy.deepcopy(rows);hours=merge_hourly_session(rows)
        self.assertEqual(len(hours),4)
        self.assertEqual((hours[0]['open'],hours[0]['high'],hours[0]['low'],hours[0]['vol']),(8.5,12,8.5,200))
        self.assertEqual(hours[0]['close'],10)
        self.assertEqual(rows,before)

    def test_missing_hour_cannot_be_rebuilt_from_daily_ohlc(self):
        rows=[dict(trade_time='2026-01-05 '+t,open=10,high=11,low=9,close=10,vol=100)
              for t in ('10:30:00','11:30:00','15:00:00')]
        with self.assertRaises(ValueError):merge_hourly_session(rows)

    def test_warmup_hour_visibility_gap_and_daily_signal_clock(self):
        from trading_system import engine as em
        import json
        cfg=json.loads((ROOT/'configs/experiments/double_bottom_v5_11_2_structure.json').read_text())
        class Observer:
            name='observer'
            def __init__(self):self.context={};self.seen=[]
            def set_context(self,context):self.context=context
            def on_close(self,history,ends):
                self.seen.append((history[-1].date,len(self.context.get('lower_histories',{}).get('X',[]))))
                return [],[]
        daily=[Bar('X',d,10,11,9,10,400) for d in ('20260105','20260106')]
        lower=[Bar('X',b.date+t,10,11,9,10,100) for b in daily for t in ('103000','113000','140000','150000')]
        old=Observer();em.Backtest(cfg,[old]).run(daily,[b.date for b in daily],set(),lower,evaluation_start='20260106')
        self.assertEqual(old.seen,[('20260105',0),('20260106',8)])
        namespace=dict(vars(em));exec(compile(research_engine_source(em),'<warmup-visibility-test>','exec'),namespace)
        repaired=Observer();namespace['Backtest'](cfg,[repaired]).run(daily,[b.date for b in daily],set(),lower,evaluation_start='20260106')
        self.assertEqual(repaired.seen,[('20260105',4),('20260106',8)])
        # Four completed hours per day still produce one daily-close callback.
        self.assertEqual(len(repaired.seen),2)


if __name__=='__main__':unittest.main()
