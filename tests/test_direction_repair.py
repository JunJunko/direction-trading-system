import sys,unittest,json
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_direction_system import core_data
from trading_system.strategies.direction_double_bottom import DirectionDoubleBottom
from trading_system.engine import Backtest
from trading_system.strategies import build_strategies
from trading_system.analysis import adjusted,AdjustedCache
from trading_system.structure import swings,SwingCache
from trading_system.structure import n_structure,rhythm

class DirectionRepairTests(unittest.TestCase):
    def fixture(self,days=5):
        s=DirectionDoubleBottom('double_bottom_v5',{'lower_cycle':'daily_nested','plan_valid_days':days})
        s.states['X']=dict(direction='long',processed='',pending=None,factor=1,floor=9,confirmed_date='20240101')
        return s,core_data()

    def test_unfilled_plan_keeps_original_levels_and_direction(self):
        s,bars=self.fixture()
        first,_=s.on_close(bars,set());first=first[0]
        tail=replace(bars[-1],date='20240129',open=13.1,high=13.3,low=13.0,close=13.2)
        second,events=s.on_close(bars+[tail],set())
        self.assertEqual(second[0].setup_id,first.setup_id)
        self.assertEqual((second[0].trigger,second[0].stop,second[0].target),(first.trigger,first.stop,first.target))
        self.assertEqual(second[0].date,tail.date)
        self.assertEqual(s.states['X']['direction'],'long')
        self.assertEqual(events[-1]['event'],'entry_plan_renewed')

    def test_expiry_removes_opportunity_not_direction(self):
        s,bars=self.fixture(days=1);s.on_close(bars,set())
        tail=replace(bars[-1],date='20240129',high=13.3,low=13,close=13.2)
        intents,events=s.on_close(bars+[tail],set())
        self.assertFalse(intents)
        self.assertNotIn('X',s.opportunities)
        self.assertEqual(s.states['X']['direction'],'long')
        self.assertTrue(any(e.get('reason')=='plan_expired' for e in events))

    def test_broken_rhythm_not_renewed(self):
        s,bars=self.fixture();first,_=s.on_close(bars,set())
        tail=replace(bars[-1],date='20240129',low=first[0].stop-.1)
        intents,events=s.on_close(bars+[tail],set())
        self.assertFalse(intents)
        self.assertTrue(any(e.get('reason')=='rhythm_failed' for e in events))

    def test_retry_rescales_known_factor_without_changing_rr(self):
        s,bars=self.fixture();first=s.on_close(bars,set())[0][0]
        last=bars[-1]
        tail=replace(last,date='20240129',open=6.55,high=6.65,low=6.5,close=6.6,factor=2)
        retry=s.on_close(bars+[tail],set())[0][0]
        self.assertAlmostEqual(retry.trigger,first.trigger/2)
        self.assertAlmostEqual(retry.target,first.target/2)
        self.assertAlmostEqual(retry.stop,first.stop/2)

    def test_missing_phase_cannot_be_silently_bypassed(self):
        config=json.loads((Path(__file__).resolve().parents[1]/'configs/double_bottom_v3.json').read_text())
        config['strategies']=[dict(type='direction_double_bottom',id='double_bottom_v5',params={})]
        with self.assertRaises(ValueError):Backtest(config,build_strategies(config['strategies']))
        config['research_scope']='structure_only'
        Backtest(config,build_strategies(config['strategies']))

    def test_later_n_can_trade_in_same_upper_direction(self):
        from datetime import date
        s,bars=self.fixture(days=1)
        first=s.on_close(bars,set())[0][0]
        later=core_data(date(2024,2,1),offset=4)
        second=s.on_close(bars+later,set())[0][0]
        self.assertNotEqual(first.setup_id,second.setup_id)
        self.assertEqual(s.states['X']['direction'],'long')
        self.assertAlmostEqual(second.target,20.05)

    def test_suspension_does_not_extend_market_day_validity(self):
        s,bars=self.fixture(days=5)
        s.set_calendar(['20240126','20240129','20240130','20240131','20240201','20240202'])
        s.on_close(bars,set())
        resumed=replace(bars[-1],date='20240202',high=13.3,low=13,close=13.2)
        intents,events=s.on_close(bars+[resumed],set())
        self.assertFalse(intents)
        self.assertTrue(any(e.get('reason')=='plan_expired' for e in events))

    def test_incremental_swings_match_every_prefix_with_plateaus_and_factors(self):
        import random
        from datetime import date,timedelta
        from trading_system.domain import Bar
        random.seed(901)
        bars=[]
        for i in range(150):
            low=round(random.uniform(9,12),2)
            high=round(random.uniform(12,16),2)
            if i%9 in (1,2) and bars:
                low,high=bars[-1].low,bars[-1].high
            bars.append(Bar('X',(date(2024,1,1)+timedelta(days=i)).strftime('%Y%m%d'),12,high,low,12,100,
                            1 if i<80 else 1.7))
        price_cache=AdjustedCache();caches=[SwingCache(1,1),SwingCache(2,2)]
        for count in range(1,len(bars)+1):
            observed=price_cache.get(bars[:count])
            self.assertEqual(observed,adjusted(bars[:count]))
            for cache in caches:
                self.assertEqual(cache.get(observed),swings(observed,cache.left,cache.right))
        observed=price_cache.get(bars[:25])
        for cache in caches:
            self.assertEqual(cache.get(observed),swings(observed,cache.left,cache.right))

    def test_real_hourly_path_and_missing_session_gate(self):
        bars=core_data()
        lower=[replace(b,date=b.date+time,volume=b.volume/4) for b in bars[11:]
               for time in ('103000','113000','140000','150000')]
        def run(known):
            s=DirectionDoubleBottom('v5',{'lower_cycle':'hourly'})
            s.states['X']=dict(direction='long',processed='',pending=None,factor=1,floor=9,confirmed_date='20240101')
            s.set_context(dict(lower_histories={'X':known}))
            return s.on_close(bars,set())
        intents,events=run(lower)
        self.assertEqual(len(intents),1)
        self.assertEqual(intents[0].evidence['lower_cycle'],'hourly')
        self.assertAlmostEqual(intents[0].target,16.05)
        self.assertAlmostEqual(intents[0].stop,12.75*.995)
        missing=[b for b in lower if b.date[:8]!=bars[14].date]
        self.assertFalse(run(missing)[0])
        self.assertTrue(any(e.get('reason')=='incomplete_lower_cycle_history' for e in run(missing)[1]))
        future=replace(lower[-1],date='20240201150000',high=99,close=98,open=97,low=96)
        self.assertEqual(run(lower+[future])[0],intents)

    def test_broken_core_c_does_not_recycle_old_n(self):
        bars=core_data()
        self.assertIsNotNone(n_structure(bars)[0])
        failed=replace(bars[-1],date='20240129',open=12,high=12.1,low=11.8,close=12)
        self.assertIsNone(n_structure(bars+[failed])[0])

    def test_already_reached_projection_is_not_new_space(self):
        bars=core_data()
        reached=replace(bars[-1],date='20240129',open=16.2,high=16.4,low=16.1,close=16.3)
        back=replace(bars[-1],date='20240130')
        self.assertIsNone(n_structure(bars+[reached,back])[0])

    def test_failed_small_rhythm_cannot_be_revived_by_bullish_close(self):
        bars=core_data();core=n_structure(bars)[0]
        self.assertIsNotNone(rhythm(bars,core)[0])
        failed=replace(bars[-1],date='20240129',open=13.3,high=13.6,low=12.7,close=13.5)
        small,reason=rhythm(bars+[failed],core)
        self.assertIsNone(small)
        self.assertEqual(reason,'small_rhythm_failed')

if __name__=='__main__':unittest.main()
