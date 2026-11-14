"""Flag touches before first executable plan; do not infer intrabar order."""
import csv,json,sys
from pathlib import Path


def main(run,require_fresh=False):
    run=Path(run);trades=json.loads((run/'trade-timeline.json').read_text(encoding='utf-8'))
    history={t['symbol']:[] for t in trades}
    with (run/'bars.csv').open(encoding='utf-8-sig') as f:
        for bar in csv.DictReader(f):
            if bar['symbol'] in history:history[bar['symbol']].append(bar)
    result=[]
    for trade in trades:
        observed=history[trade['symbol']]
        anchor=next(float(b['factor']) for b in observed if b['date']==trade['first_planned_at'])
        trigger=float(trade['trigger'])
        earlier=[b for b in observed if trade['small_confirmed'][:8]<=b['date']<trade['first_planned_at']]
        planned=next(b for b in observed if b['date']==trade['first_planned_at'])
        dates=lambda field:[b['date'] for b in earlier if float(b[field])*float(b['factor'])/anchor>=trigger]
        result.append(dict(symbol=trade['symbol'],small_confirmed=trade['small_confirmed'],
            first_planned_at=trade['first_planned_at'],prior_high_touch_dates=dates('high'),
            prior_close_break_dates=dates('close'),
            first_plan_day_already_touched=float(planned['high'])>=trigger,
            scope='Freshness diagnostic before first plan; known-factor normalization. No inferred intrabar execution.'))
    if require_fresh:
        assert all(not r['prior_high_touch_dates'] and not r['first_plan_day_already_touched'] for r in result),result
    (run/'preplan-trigger-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':main(sys.argv[1],'--require-fresh' in sys.argv[2:])
