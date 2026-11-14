"""Four frozen entry-only filters, each against the same full signal population."""
import csv,os,shutil
from backtest_reentry_daily_protection import ROOT,OLD,W,IHS,bind,load,dump,rows,Bar,save_csv,build_strategies,MainboardUniverse
from trading_system.quality_entry_research import QualityEntryBacktest

OUT=ROOT/'runs/20261110-quality-entry'
SOURCE=ROOT/'runs/20261110-reentry-daily-protection'
CASES=[('W','span120'),('W','no_gap_up'),('IHS','no_gap_up'),('IHS','neck_half_atr')]

def main():
    OUT.mkdir(exist_ok=True)
    protocol=dict(start='20251009',end='20260930',warmup='20230103',population=3214,
        source_protocol=load(SOURCE/'protocol.json'),cases=[list(c) for c in CASES],
        rules=dict(span120='W bottom separation <=120 observed stock bars',no_gap_up='actual opening <= previous adjusted close; excludes slippage',neck_half_atr='IHS slipped entry less than 0.5 prior ATR14 above execution-date frozen neckline'),
        execution='gate at next-open execution only; original signal consumption, entry/exit, sizing and costs unchanged',
        costs='standard and doubled commission rate/slippage',selection='four fixed exploratory filters based on previously studied trades; no grid search, no holdout claim',
        hypotheses='reject stale W structures or chasing prices; may remove momentum winners; do not use future outcome to veto entry')
    if (OUT/'protocol.json').exists():assert load(OUT/'protocol.json')==protocol
    else:
        # JSON converts tuples to lists, freeze a stable representation.
        dump(OUT/'protocol.json',protocol)
        shutil.copytree(ROOT/'src',OUT/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('backtest_quality_entry.py','backtest_reentry_daily_protection.py','backtest_candidate_policy.py'):
            shutil.copy2(ROOT/'scripts'/name,OUT/'source'/name)
        for name in ('calendar.json','universe.json'):shutil.copy2(SOURCE/name,OUT/name)
        os.link(SOURCE/'bars.csv',OUT/'bars.csv')
    sources={'W':load(W/'plans.json'),'IHS':load(IHS/'plans.json')}
    wanted={p['symbol'] for ps in sources.values() for p in ps};bars=[]
    with (OUT/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in wanted:bars.append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    bars.sort(key=lambda b:(b.date,b.symbol));cal=load(OUT/'calendar.json');u=load(OUT/'universe.json');universe=MainboardUniverse(u['stocks'],u['st_by_date'])
    summaries=[]
    for family in ('W','IHS'):
        for cost in (1,2):
            label=f'{family}_baseline_cost{cost}';folder=OUT/label
            if not folder.exists():shutil.copytree(SOURCE/label,folder)
            summaries.append(load(folder/'summary.json'))
    for family,rule in CASES:
        symbols={p['symbol'] for p in sources[family]};current=[b for b in bars if b.symbol in symbols]
        for cost in (1,2):
            label=f'{family}_{rule}_cost{cost}';folder=OUT/label;folder.mkdir(exist_ok=True)
            if (folder/'summary.json').exists():summaries.append(load(folder/'summary.json'));continue
            cfg=load(SOURCE/f'{family}_baseline_cost{cost}/config.json');cfg['quality_entry_filter']=rule
            cfg['research_experiment_id']='quality_entry_v1_'+label
            dump(folder/'config.json',cfg)
            strategy=build_strategies(cfg['strategies'])[0];bind(strategy,sources[family],False)
            engine=QualityEntryBacktest(cfg,[strategy]).run(current,cal['open_dates'],set(cal['week_ends']),evaluation_start='20251009',evaluation_end='20260930',universe=universe,
                progress=lambda state:print(label,state['session'],flush=True) if state['session']%250==0 else None)
            for name,data in [('orders',engine.orders),('trades',engine.trades),('entry_audit',engine.entry_audits),('equity',engine.curve),('decisions',engine.events)]:save_csv(folder/(name+'.csv'),data)
            summary=engine.summary();summary['case']=label;summary['quality_rejected']=sum(a.get('risk_reason','').startswith('quality_') for a in engine.entry_audits)
            dump(folder/'summary.json',summary);summaries.append(summary)
            save_csv(OUT/'comparison.csv',[{k:v for k,v in s.items() if k!='positions'} for s in summaries])
            print('DONE',label,summary['total_return'],summary['max_drawdown'],summary['filled_buys'],flush=True)
    dump(OUT/'status.json',dict(status='complete',cases=len(summaries)))

if __name__=='__main__':main()
