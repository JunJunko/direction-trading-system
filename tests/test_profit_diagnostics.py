import contextlib,csv,io,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from diagnose_closed_trade_profit import main


class ProfitDiagnosticsTests(unittest.TestCase):
    def test_factor_normalization_and_exit_day_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            def save(name,records):
                with (path/name).open('w',newline='',encoding='utf-8') as stream:
                    writer=csv.DictWriter(stream,fieldnames=records[0]);writer.writeheader();writer.writerows(records)
            save('bars.csv',[
                dict(symbol='X',date='20250102',close=12,factor=1),
                dict(symbol='X',date='20250103',close=7,factor=2),
                dict(symbol='X',date='20250106',close=100,factor=2)])
            save('trades.csv',[dict(symbol='X',entry_date='20250102',exit_date='20250106',
                entry=5,quantity=200,pnl=-100,realized_r=-1,reason='structural_stop')])
            with contextlib.redirect_stdout(io.StringIO()):main([str(path)])
            trade=json.loads((path/'profit-diagnostics.json').read_text())['trades'][0]
            self.assertEqual(trade['peak_close_date'],'20250103')
            self.assertEqual(trade['peak_close_gross_r'],4)
            self.assertTrue(trade['positive_close_then_net_loss'])
