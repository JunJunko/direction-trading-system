"""Four fixed single-variable filters layered on the no-gap-up baseline."""
import csv,os,shutil
from backtest_reentry_daily_protection import ROOT,IHS,bind,load,dump,rows,sha,Bar,save_csv,build_strategies,MainboardUniverse
from trading_system.ihs_entry_quality_research import IHSEntryQualityBacktest

OUT=ROOT/'runs/20261110-ihs-entry-quality'
BASE=ROOT/'runs/20261110-quality-entry'
RULES=['baseline','solid_close','volume_confirmed','rising_ma20','limited_gap_down']

def main():
    OUT.mkdir(exist_ok=True)
    protocol=dict(start='20251009',end='20260930',warmup='20230103',population=3214,signals=1713,
        bars_sha256=load(BASE/'manifest.json')['data_sha256'],
        base='IHS v7 exits and all entry risk gates, actual open <= adjusted previous close; no early daily protection',
        rules=dict(solid_close='signal close in upper half of daily high-low range (>=0.5)',volume_confirmed='signal volume >= arithmetic mean of preceding 20 stock bars, signal excluded from mean',rising_ma20='20-bar adjusted close mean at signal >= same mean five stock bars earlier',limited_gap_down='actual open at most 0.5 prior ATR14 below adjusted previous close (>= -0.5)'),
        hypothesis='Weak signal close, unconfirmed volume, declining medium-term trend, or excessive overnight deterioration may indicate poor entry quality; each may also reject trend winners.',
        design='four separate extra filters on no_gap_up, plus rerun baseline; two costs each; thresholds frozen before account outcomes, no grid or combinations',
        timing='new gates at execution only, no signal rescheduling or future OHLC; standard and doubled commission/slippage inherited from base configs',
        limits='previously studied development interval; no unused holdout; daily execution and synthetic factor accounting retained')
    if (OUT/'protocol.json').exists():assert load(OUT/'protocol.json')==protocol
    else:
        dump(OUT/'protocol.json',protocol)
        shutil.copytree(ROOT/'src',OUT/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('backtest_ihs_entry_quality.py','backtest_reentry_daily_protection.py','backtest_candidate_policy.py'):
            shutil.copy2(ROOT/'scripts'/name,OUT/'source'/name)
        for name in ('calendar.json','universe.json'):shutil.copy2(BASE/name,OUT/name)
        os.link(BASE/'bars.csv',OUT/'bars.csv')
    plans=load(IHS/'plans.json');assert len(plans)==1713
    wanted={p['symbol'] for p in plans};bars=[]
    with (OUT/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in wanted:bars.append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    bars.sort(key=lambda b:(b.date,b.symbol));cal=load(OUT/'calendar.json');u=load(OUT/'universe.json');universe=MainboardUniverse(u['stocks'],u['st_by_date'])
    summaries=[]
    for rule in RULES:
        for cost in (1,2):
            label=f'{rule}_cost{cost}';folder=OUT/label;folder.mkdir(exist_ok=True)
            if (folder/'summary.json').exists():summaries.append(load(folder/'summary.json'));continue
            cfg=load(BASE/f'IHS_no_gap_up_cost{cost}/config.json')
            cfg['research_experiment_id']='ihs_entry_quality_v12_'+label
            if rule!='baseline':
                cfg['ihs_entry_quality_filter']=rule
                cfg['strategies'][0]['id']='inverse_head_shoulders_v12_'+rule
            dump(folder/'config.json',cfg)
            if cost==1:dump(ROOT/'configs/experiments'/f'ihs_v12_no_gap_{rule}.json',cfg)
            strategy=build_strategies(cfg['strategies'])[0];bind(strategy,plans,False)
            engine=IHSEntryQualityBacktest(cfg,[strategy]).run(bars,cal['open_dates'],set(cal['week_ends']),evaluation_start='20251009',evaluation_end='20260930',universe=universe,
                progress=lambda state:print(label,state['session'],flush=True) if state['session']%250==0 else None)
            for name,data in [('orders',engine.orders),('trades',engine.trades),('entry_audit',engine.entry_audits),('equity',engine.curve),('decisions',engine.events)]:save_csv(folder/(name+'.csv'),data)
            if rule=='baseline':
                for name in ('orders','trades','entry_audit','equity'):
                    assert rows(folder/(name+'.csv'))==rows(BASE/f'IHS_no_gap_up_cost{cost}'/(name+'.csv')),(label,name)
            summary=engine.summary();summary['case']=label
            summary['extra_rejections']=sum(a.get('risk_reason','').startswith('ihs_quality_') for a in engine.entry_audits)
            dump(folder/'summary.json',summary);summaries.append(summary)
            save_csv(OUT/'comparison.csv',[{k:v for k,v in s.items() if k!='positions'} for s in summaries])
            print('DONE',label,summary['total_return'],summary['max_drawdown'],summary['filled_buys'],flush=True)
    save_csv(OUT/'comparison.csv',[{k:v for k,v in s.items() if k!='positions'} for s in summaries])
    dump(OUT/'status.json',dict(status='complete',cases=len(summaries)))

if __name__=='__main__':main()
