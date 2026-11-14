import sys, unittest, math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_rr_kelly import kelly, metrics

class KellyTests(unittest.TestCase):
    def test_known_binary(self):
        self.assertAlmostEqual(kelly([2,-1]),.25)
        self.assertAlmostEqual(kelly([1,1,1,-1,-1]),.2)
    def test_nonpositive_and_empty(self):
        for rs in ([],[-1],[-1,1],[-2,1]):self.assertEqual(kelly(rs),0)
    def test_loss_scale_units(self):
        ts=[dict(realized_r=r,pnl=r*100) for r in [4,-2]]
        m=metrics(ts)
        self.assertAlmostEqual(m['binary_kelly_loss_units'],.25)
        self.assertAlmostEqual(m['binary_kelly_initial_r'],.125)
        self.assertAlmostEqual(m['empirical_kelly_initial_r'],.125)
    def test_variable_outcome_optimum(self):
        rs=[3,2,.3,-.5,-1,-2];f=kelly(rs)
        g=lambda x:sum(math.log1p(x*r) for r in rs)
        self.assertGreater(g(f),g(f-.001));self.assertGreater(g(f),g(f+.001))
        self.assertTrue(all(1+f*r>0 for r in rs))

if __name__=='__main__':unittest.main()
