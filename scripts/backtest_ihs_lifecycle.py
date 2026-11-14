"""Frozen timing / failed-breakout / profitable-position protection comparisons."""
import copy,csv,os,shutil
from collections import defaultdict
from backtest_reentry_daily_protection import ROOT,IHS,load,dump,rows,sha,Bar,Intent,save_csv,build_strategies,MainboardUniverse
from trading_system.quality_entry_research import QualityEntryBacktest

OUT=ROOT/'runs/20261110-ihs-lifecycle'
BASE=ROOT/'runs/20261110-quality-entry'
CASES={'baseline':'pressure_support_ihs','retest':'retest_confirmed_ihs','failure':'breakout_failure_ihs','profit':'profit_activated_ihs'}

def bind_lifecycle(strategy,plans,retest):
    book=defaultdict(list)
    for p in plans:
        e={k:copy.deepcopy(v) for k,v in p.items() if k not in ('date','symbol','setup_id','trigger','stop','target')};e['target_exit_rule']='reference_only'
        pid=strategy.name+':'+p['setup_id'].split(':',1)[1]
        intent=Intent(strategy.name,p['symbol'],p['date'],p['trigger'],p['stop'],p['target'],pid,'inverse_head_shoulders',e)
        log=dict(date=p['date'],symbol=p['symbol'],strategy=strategy.name,setup_id=pid,event='retest_seed' if retest else 'entry_intent',trigger=p['trigger'],stop=p['stop'],target=p['target'],**e)
        book[p['symbol'],p['date']].append((intent,log))
    def on_close(history,week_ends):
        values=book.get((history[-1].symbol,history[-1].date),[]);intents=[copy.deepcopy(i) for i,e in values];events=[copy.deepcopy(e) for i,e in values]
        if retest:
            intents,extra=strategy.retest_on_close(history,intents);events.extend(extra)
        return intents,events
    strategy.on_close=on_close

def main():
    OUT.mkdir(exist_ok=True)
    protocol=dict(start='20251009',end='20260930',warmup='20230103',population=3214,signals=1713,bars_sha256=load(BASE/'manifest.json')['data_sha256'],
        baseline='IHS v7 plus no_gap_up; all original risk gates, right-shoulder hard stop, reference target and pressure/weekly support exits retained',
        retest='replace immediate entry with one confirmation in next 10 stock bars; first low <= frozen sloped neckline +0.25 frozen signal ATR; on a LATER bar green close above previous adjusted close and neckline+0.1 frozen ATR; next-open no-gap-up entry; cancel if original right shoulder broken, original target touched, or expired; same anchors/stop/target and frozen signal ATR; every seed consumed once even if entry rejected',
        failure='original management first, otherwise two consecutive held closes < each date frozen sloped neckline -0.5 prior ATR14; next executable open; original hard stop remains',
        profit='activate after marked profit net of entry fee (before exit costs) >= initial monetary risk 1R; after activation, new strict left2/right2 higher daily low with all five bars after entry and pivot date >= activation; low-0.5 prior ATR14 only raises support, below close, effective next stock session; close breach then next open',
        design='3 separate single-mechanism arms plus baseline, standard and doubled commission/slippage; no combinations or threshold tuning',
        limitations='Known development interval, no independent holdout; daily OHLC execution, T+1 and synthetic factor accounting unchanged; fresh seeds replayed on all signal stocks, not only previous fills')
    if (OUT/'protocol.json').exists():assert load(OUT/'protocol.json')==protocol
    else:
        dump(OUT/'protocol.json',protocol);shutil.copytree(ROOT/'src',OUT/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('backtest_ihs_lifecycle.py','backtest_reentry_daily_protection.py','backtest_candidate_policy.py'):shutil.copy2(ROOT/'scripts'/name,OUT/'source'/name)
        for name in ('calendar.json','universe.json'):shutil.copy2(BASE/name,OUT/name)
        os.link(BASE/'bars.csv',OUT/'bars.csv');shutil.copy2(IHS/'plans.json',OUT/'plans.json')
    plans=load(OUT/'plans.json');assert len(plans)==1713;wanted={p['symbol'] for p in plans};bars=[]
    with (OUT/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in wanted:bars.append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    bars.sort(key=lambda b:(b.date,b.symbol));cal=load(OUT/'calendar.json');u=load(OUT/'universe.json');universe=MainboardUniverse(u['stocks'],u['st_by_date']);summaries=[]
    for rule,kind in CASES.items():
        for cost in (1,2):
            case=f'{rule}_cost{cost}';folder=OUT/case;folder.mkdir(exist_ok=True)
            if (folder/'summary.json').exists():summaries.append(load(folder/'summary.json'));continue
            cfg=load(BASE/f'IHS_no_gap_up_cost{cost}/config.json');cfg['research_experiment_id']='ihs_lifecycle_v13_'+case
            if rule!='baseline':cfg['strategies'][0].update(type=kind,id='inverse_head_shoulders_v13_'+rule)
            dump(folder/'config.json',cfg)
            if cost==1:dump(ROOT/'configs/experiments'/f'ihs_v13_no_gap_{rule}.json',cfg)
            strategy=build_strategies(cfg['strategies'])[0];bind_lifecycle(strategy,plans,rule=='retest')
            engine=QualityEntryBacktest(cfg,[strategy]).run(bars,cal['open_dates'],set(cal['week_ends']),evaluation_start='20251009',evaluation_end='20260930',universe=universe,
                progress=lambda state:print(case,state['session'],flush=True) if state['session']%250==0 else None)
            for name,data in [('orders',engine.orders),('trades',engine.trades),('entry_audit',engine.entry_audits),('equity',engine.curve),('decisions',engine.events)]:save_csv(folder/(name+'.csv'),data)
            if rule=='baseline':
                for name in ('orders','trades','entry_audit','equity'):assert rows(folder/(name+'.csv'))==rows(BASE/f'IHS_no_gap_up_cost{cost}'/(name+'.csv')),(case,name)
            summary=engine.summary();summary.update(case=case,retest_signals=sum(e['event']=='entry_intent' and bool(e.get('retest_confirmed_at')) for e in engine.events),failure_signals=sum(e['event']=='ihs_breakout_failure_confirmed' for e in engine.events),profit_activations=sum(e['event']=='profit_protection_activated' for e in engine.events),profit_support_raises=sum(e['event']=='main_protection_raised' and e.get('source')=='profit_activated_daily_higher_low' for e in engine.events))
            dump(folder/'summary.json',summary);summaries.append(summary)
            save_csv(OUT/'comparison.csv',[{k:v for k,v in s.items() if k!='positions'} for s in summaries]);print('DONE',case,summary['total_return'],summary['max_drawdown'],summary['filled_buys'],flush=True)
    save_csv(OUT/'comparison.csv',[{k:v for k,v in s.items() if k!='positions'} for s in summaries]);dump(OUT/'status.json',dict(status='complete',cases=8))

if __name__=='__main__':main()
