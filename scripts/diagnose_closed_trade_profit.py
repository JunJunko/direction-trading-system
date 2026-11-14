"""Describe pre-exit daily-close excursions, not hypothetical executable profits."""
import csv,json,sys
from pathlib import Path


def rows(path):
    with path.open(encoding='utf-8-sig') as stream:yield from csv.DictReader(stream)


def main(paths):
    runs=[(Path(path),list(rows(Path(path)/'trades.csv'))) for path in paths]
    symbols={t['symbol'] for _,trades in runs for t in trades}
    history={symbol:[] for symbol in symbols}
    for bar in rows(runs[0][0]/'bars.csv'):
        if bar['symbol'] in history:history[bar['symbol']].append(bar)
    for path,trades in runs:
        diagnostics=[]
        for trade in trades:
            observed=history[trade['symbol']]
            exit_bar=next(b for b in observed if b['date']==trade['exit_date'])
            # Engine records entry and final quantity in the exit day's factor.
            anchor=float(exit_bar['factor'])
            holding=[b for b in observed if trade['entry_date']<=b['date']<trade['exit_date']]
            if not holding:continue
            peak=max(holding,key=lambda b:float(b['close'])*float(b['factor']))
            normalized_close=float(peak['close'])*float(peak['factor'])/anchor
            pnl=float(trade['pnl']);realized_r=float(trade['realized_r'])
            initial_risk=pnl/realized_r if realized_r else None
            peak_gross=(normalized_close-float(trade['entry']))*float(trade['quantity'])
            peak_r=peak_gross/initial_risk if initial_risk else None
            diagnostics.append(dict(symbol=trade['symbol'],entry_date=trade['entry_date'],
                exit_date=trade['exit_date'],exit_reason=trade['reason'],net_pnl=pnl,
                realized_r=realized_r,peak_close_date=peak['date'],peak_close_gross_r=peak_r,
                positive_close_then_net_loss=peak_gross>0 and pnl<0))
        payload=dict(scope='Gross daily-close excursion; excludes exit day and fees; not a realizable optimal exit or intraday MFE',
                     trades=diagnostics)
        (path/'profit-diagnostics.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        if diagnostics:
            with (path/'profit-diagnostics.csv').open('w',encoding='utf-8-sig',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(diagnostics[0]));writer.writeheader();writer.writerows(diagnostics)
        print(json.dumps(dict(run=str(path),trades=diagnostics),ensure_ascii=True))


if __name__=='__main__':main(sys.argv[1:])
