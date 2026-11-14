import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from wave_model_audit import containment,snapshot,node_rows
from test_direction_system import core_data
from trading_system.structure import swings,SwingCache
from trading_system.analysis import adjusted


class WaveAuditTests(unittest.TestCase):
    def test_containment_is_not_semantic_parentage(self):
        child=dict(id='child',start='20240102',end='20240104')
        parent=dict(id='parent',start='20240101',end='20240105')
        relation=containment([child],[parent])[0]
        self.assertEqual(relation['parent'],'parent')
        self.assertFalse(relation['semantic_parent_proven'])
        self.assertIsNone(containment([dict(child,end='20240106')],[parent])[0]['parent'])

    def test_future_append_does_not_change_saved_prefix(self):
        bars=core_data();a=snapshot(bars[:17],set())
        snapshot(bars,set())
        self.assertEqual(a,snapshot(bars[:17],set()))
        self.assertTrue(all(p['confirmed']<=a['as_of'] for points in a['nodes'].values() for p in points))

    def test_stream_and_batch_at_each_prefix(self):
        bars=core_data();cache=SwingCache(2,2)
        for i in range(1,len(bars)+1):
            prefix=adjusted(bars[:i])
            self.assertEqual(cache.get(prefix),swings(prefix,2,2))

    def test_proxy_label_does_not_claim_hourly(self):
        s=snapshot(core_data(),set())
        self.assertIn('daily_nested_proxy',s['nodes'])
        self.assertNotIn('hourly',s['nodes'])


if __name__=='__main__':unittest.main()
