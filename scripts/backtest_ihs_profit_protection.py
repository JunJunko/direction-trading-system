"""Frozen larger structure versus half-peak-profit protection, complete accounts."""
import csv,os,shutil
from backtest_ihs_lifecycle import ROOT,BASE,IHS,load,dump,rows,sha,Bar,save_csv,build_strategies,MainboardUniverse,QualityEntryBacktest,bind_lifecycle

OUT=ROOT/'runs/20261110-ihs-profit-protection'
PREV=ROOT/'runs/20261110-ihs-lifecycle'
CASES={'baseline':'pressure_support_ihs','small':'profit_activated_ihs','larger':'larger_profit_structure_ihs','half':'half_profit_retention_ihs'}

def main():
    OUT.mkdir(exist_ok=True)
    protocol=dict(start='20251009',end='20260930',warmup='20230103',population=3214,signals=1713,bars_sha256=load(PREV/'manifest.json')['data_sha256'],
       baseline='Frozen no-gap-up IHS v7; same original risk gates, hard stop and pressure/weekly support management',
       small='Exact replay of v13 1R-activated daily strict left2/right2 higher-low protection with 0.5 prior ATR buffer',
       larger='Only change daily pivot scale from left2/right2 to left5/right5. Keep 1R activation, all pivot-window bars after entry, pivot date >= activation, higher than preceding same-scale low (first reference entry low), 0.5 prior ATR buffer and next-session effectiveness',
       half='Replace extra daily pivot protection with 50% retention of peak close marked monetary profit after entry fee before hypothetical exit fees. Same 1R activation. Economic price=(adjusted entry+(entry fee+0.5*peak marked profit)/current quantity)*current factor. Only raises old protection, effective next session; close breach then next executable open. Never use intraday highs or future peaks',
       design='2 separate single-mechanism variants, original baseline and v13 small-scale reference, each standard/double commission/slippage; no combinations or threshold tuning',
       limitations='Repeatedly studied development interval, no independent holdout. 603989 known in advance; no special-casing or threshold fitting. Full frozen signal population replay, unchanged daily OHLC/T+1/factor accounting. Original exits retain priority; additional lines cannot loosen original protection.')
    if (OUT/'protocol.json').exists():assert load(OUT/'protocol.json')==protocol
    else:
        dump(OUT/'protocol.json',protocol);shutil.copytree(ROOT/'src',OUT/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('backtest_ihs_profit_protection.py','backtest_ihs_lifecycle.py','backtest_reentry_daily_protection.py','backtest_candidate_policy.py'):shutil.copy2(ROOT/'scripts'/name,OUT/'source'/name)
        for name in ('plans.json','calendar.json','universe.json'):shutil.copy2(PREV/name,OUT/name)
        os.link(PREV/'bars.csv',OUT/'bars.csv')
    plans=load(OUT/'plans.json');assert len(plans)==1713;wanted={p['symbol'] for p in plans};bars=[]
    with (OUT/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in wanted:bars.append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    bars.sort(key=lambda b:(b.date,b.symbol));cal=load(OUT/'calendar.json');u=load(OUT/'universe.json');universe=MainboardUniverse(u['stocks'],u['st_by_date']);summaries=[]
    for rule,kind in CASES.items():
        for cost in (1,2):
            case=f'{rule}_cost{cost}';folder=OUT/case;folder.mkdir(exist_ok=True)
            if (folder/'summary.json').exists():summaries.append(load(folder/'summary.json'));continue
            cfg=load(PREV/f'{"profit" if rule=="small" else "baseline"}_cost{cost}/config.json');cfg['research_experiment_id']='ihs_profit_v14_'+case
            if rule in ('larger','half'):cfg['strategies'][0].update(type=kind,id='inverse_head_shoulders_v14_'+rule)
            dump(folder/'config.json',cfg)
            if cost==1:dump(ROOT/'configs/experiments'/f'ihs_v14_no_gap_{rule}.json',cfg)
            strategy=build_strategies(cfg['strategies'])[0];bind_lifecycle(strategy,plans,False)
            engine=QualityEntryBacktest(cfg,[strategy]).run(bars,cal['open_dates'],set(cal['week_ends']),evaluation_start='20251009',evaluation_end='20260930',universe=universe,
                progress=lambda state:print(case,state['session'],flush=True) if state['session']%250==0 else None)
            for name,data in [('orders',engine.orders),('trades',engine.trades),('entry_audit',engine.entry_audits),('equity',engine.curve),('decisions',engine.events)]:save_csv(folder/(name+'.csv'),data)
            if rule in ('baseline','small'):
                old=PREV/f'{"profit" if rule=="small" else "baseline"}_cost{cost}'
                for name in ('orders','trades','entry_audit','equity','decisions'):assert rows(folder/(name+'.csv'))==rows(old/(name+'.csv')),(case,name)
            summary=engine.summary();summary.update(case=case,profit_activations=sum(e['event']=='profit_protection_activated' for e in engine.events),extra_support_raises=sum(e['event']=='main_protection_raised' and str(e.get('source','')).startswith('profit_') for e in engine.events))
            dump(folder/'summary.json',summary);summaries.append(summary);save_csv(OUT/'comparison.csv',[{k:v for k,v in s.items() if k!='positions'} for s in summaries]);print('DONE',case,summary['total_return'],summary['max_drawdown'],summary['filled_buys'],flush=True)
    save_csv(OUT/'comparison.csv',[{k:v for k,v in s.items() if k!='positions'} for s in summaries]);dump(OUT/'status.json',dict(status='complete',cases=8))

if __name__=='__main__':main()
