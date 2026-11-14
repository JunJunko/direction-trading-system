"""Run after copying to the experiment's source/ directory; no workspace imports."""
import argparse,csv,json,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'src'))
from backtest_ihs_lifecycle import bind_lifecycle
from trading_system.domain import Bar
from trading_system.data import save_csv
from trading_system.strategies import build_strategies
from trading_system.universe import MainboardUniverse
from trading_system.quality_entry_research import QualityEntryBacktest

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--case',required=True)
    args=parser.parse_args();root=HERE.parent
    allowed={f'{rule}_cost{cost}' for rule in ('baseline','retest','failure','profit') for cost in (1,2)}
    if args.case not in allowed:parser.error('Unknown case')
    load=lambda p:json.loads(p.read_text(encoding='utf-8-sig'))
    cfg=load(root/args.case/'config.json');plans=load(root/'plans.json');symbols={p['symbol'] for p in plans};bars=[]
    with (root/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in symbols:bars.append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    bars.sort(key=lambda b:(b.date,b.symbol));cal=load(root/'calendar.json');u=load(root/'universe.json')
    strategy=build_strategies(cfg['strategies'])[0];bind_lifecycle(strategy,plans,args.case.startswith('retest'))
    engine=QualityEntryBacktest(cfg,[strategy]).run(bars,cal['open_dates'],set(cal['week_ends']),evaluation_start='20251009',evaluation_end='20260930',universe=MainboardUniverse(u['stocks'],u['st_by_date']))
    out=root/'reproduced'/args.case;out.mkdir(parents=True,exist_ok=True)
    for name,data in [('orders',engine.orders),('trades',engine.trades),('entry_audit',engine.entry_audits),('equity',engine.curve),('decisions',engine.events)]:
        save_csv(out/(name+'.csv'),data)
        with (root/args.case/(name+'.csv')).open(encoding='utf-8-sig',newline='') as f:expected=list(csv.DictReader(f))
        with (out/(name+'.csv')).open(encoding='utf-8-sig',newline='') as f:actual=list(csv.DictReader(f))
        assert expected==actual,(args.case,name)
    (out/'summary.json').write_text(json.dumps(engine.summary(),ensure_ascii=False,indent=2),encoding='utf-8')
    print('Exact reproduction:',args.case)

if __name__=='__main__':main()
