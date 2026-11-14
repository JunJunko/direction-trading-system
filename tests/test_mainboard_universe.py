import sys, unittest, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.universe import MainboardUniverse
from trading_system.analysis import WeeklyCache, weekly, adjusted, week_key
from trading_system.domain import Bar, Intent
from trading_system.engine import Backtest

class Fixture:
    name='fixture'
    def on_close(self,history,week_ends):
        b=history[-1]
        return [Intent(self.name,b.symbol,b.date,10.01,9.8,12,b.date,'fixture')],[]
    def trailing_stop(self,history,position): return position.stop

class MainboardTests(unittest.TestCase):
    def test_listing_st_and_missing_coverage(self):
        u=MainboardUniverse([dict(ts_code='X',list_date='20240102',delist_date='20240105')],
            {'20240101':[],'20240102':[],'20240103':['X'],'20240105':[]})
        self.assertFalse(u.eligible('X','20240101'))
        self.assertTrue(u.eligible('X','20240102'))
        for date in ('20240103','20240104','20240105'):
            self.assertFalse(u.eligible('X',date))

    def test_execution_rechecks_st_and_keeps_history(self):
        config=json.loads((Path(__file__).resolve().parents[1]/'configs/double_bottom_v3.json').read_text())
        dates=['20240102','20240103']
        bars=[Bar('X',d,10,10.2,9.95,10.1,100) for d in dates]
        u=MainboardUniverse([dict(ts_code='X',list_date='20240101')],{dates[0]:[],dates[1]:['X']})
        e=Backtest(config,[Fixture()]).run(bars,dates,set(),universe=u)
        self.assertFalse(e.orders)
        self.assertEqual(len(e.histories['X']),2)
        self.assertEqual([r['reason'] for r in e.events],['universe_ineligible_execution','universe_ineligible_signal'])

    def test_incremental_weekly_exact_equivalence(self):
        dates=['20240102','20240103','20240105','20240108','20240112','20240115','20240119']
        ends={'20240105','20240112','20240119'}
        mapping={week_key(d):d for d in ends}; cache=WeeklyCache()
        bars=[Bar('X',d,9.35,10.21,9.11,9.77,100.1,2.447 if i<4 else 2.81) for i,d in enumerate(dates)]
        for count in (1,2,4,5,7):
            self.assertEqual(cache.get(bars[:count],mapping),weekly(adjusted(bars[:count]),ends))
        self.assertEqual(cache.get(bars[:3],mapping),weekly(adjusted(bars[:3]),ends))

if __name__=='__main__': unittest.main()
