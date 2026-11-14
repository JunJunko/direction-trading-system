"""Two independent single-variable full-universe account comparisons."""
import copy
import csv
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Bar, Intent
from trading_system.engine import Backtest
from trading_system.data import save_csv
from trading_system.strategies import build_strategies
from trading_system.universe import MainboardUniverse
from backtest_candidate_policy import load, dump, rows, sha

OUT=ROOT/'runs/20261110-reentry-daily-protection'
OLD=ROOT/'runs/20261109-algorithm-combination-comparison'
W=ROOT/'runs/20261025-mainboard-qualified-w-v519-signals'
IHS=ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v7-pressure-support'


def bind(strategy, plans, retry):
    book=defaultdict(list)
    for plan in plans:
        evidence={k:copy.deepcopy(v) for k,v in plan.items() if k not in ('date','symbol','setup_id','trigger','stop','target')}
        evidence['target_exit_rule']='reference_only'
        pid=strategy.name+':'+plan['setup_id'].split(':',1)[1]
        if 'w_owner' in evidence:
            evidence['w_owner']=pid
        intent=Intent(strategy.name,plan['symbol'],plan['date'],plan['trigger'],plan['stop'],plan['target'],pid,
                      'direct_w' if 'w_floor' in evidence else 'inverse_head_shoulders',evidence)
        event=dict(date=plan['date'],symbol=plan['symbol'],strategy=strategy.name,setup_id=pid,
                   event='entry_intent',trigger=plan['trigger'],stop=plan['stop'],target=plan['target'],**evidence)
        book[plan['symbol'],plan['date']].append((intent,event))
    def on_close(history,weekends):
        values=book.get((history[-1].symbol,history[-1].date),[])
        intents=[copy.deepcopy(i) for i,e in values]
        events=[copy.deepcopy(e) for i,e in values]
        if retry:
            extra,logs=strategy.retry_on_close(history)
            intents.extend(extra)
            events.extend(logs)
        return intents,events
    strategy.on_close=on_close


def main():
    OUT.mkdir(exist_ok=True)
    sources={'W':load(W/'plans.json'),'IHS':load(IHS/'plans.json')}
    protocol=dict(population=3214,bars_sha256=sha(IHS/'bars.csv'),signals={k:len(v) for k,v in sources.items()},
        start='20251009',end='20260930',warmup='20230103',
        W='one retry only after an actually filled W stop exits; next 14 stock bars; fresh strict 2-left/2-right confirmed low formed after exit; intact original W floor; original target not touched; green close above prior close and original neckline; next-open entry, new low stop, unchanged target and all risk gates',
        IHS='original v7 exits plus confirmed daily higher low, strict 2-left/2-right entirely after entry; first reference is entry-day low; higher than prior post-entry pivot low; subtract 0.5 prior ATR; support only rises, effective next session, close breach then next open',
        design='W baseline vs retry; IHS baseline vs daily support; each independently at standard and doubled commission/slippage; no threshold search',
        limitations='Previously studied interval; daily execution and synthetic factor accounting retained; no holdout claim')
    if (OUT/'protocol.json').exists():
        assert load(OUT/'protocol.json')==protocol
    else:
        dump(OUT/'protocol.json',protocol)
        shutil.copytree(ROOT/'src',OUT/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(__file__,OUT/'source'/Path(__file__).name)
        os.link(IHS/'bars.csv',OUT/'bars.csv')
        for name in ('calendar.json','universe.json'):
            shutil.copy2(IHS/name,OUT/name)
    wanted={p['symbol'] for plans in sources.values() for p in plans}
    bars=[]
    with (OUT/'bars.csv').open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            if row['symbol'] in wanted:
                bars.append(Bar(row['symbol'],row['date'],**{k:float(row[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    bars.sort(key=lambda b:(b.date,b.symbol))
    cal=load(OUT/'calendar.json');u=load(OUT/'universe.json')
    universe=MainboardUniverse(u['stocks'],u['st_by_date'])
    summaries=[]
    for family,oldname,newtype in [('W','W_v7_only','reconfirmed_w'),('IHS','IHS_v7_only','daily_protected_ihs')]:
        symbols={p['symbol'] for p in sources[family]}
        current=[b for b in bars if b.symbol in symbols]
        for cost in (1,2):
            for candidate in (False,True):
                label=f'{family}_{"candidate" if candidate else "baseline"}_cost{cost}'
                folder=OUT/label
                if (folder/'summary.json').exists():
                    summaries.append(load(folder/'summary.json'));continue
                folder.mkdir(exist_ok=True)
                cfg=load(OLD/oldname/'config.json')
                cfg['execution']['commission_rate']*=cost
                cfg['execution']['slippage']*=cost
                if candidate:cfg['strategies'][0]['type']=newtype
                strategy=build_strategies(cfg['strategies'])[0]
                bind(strategy,sources[family],family=='W' and candidate)
                dump(folder/'config.json',cfg)
                def progress(state):
                    if state['session']%200==0:print(label,state['session'],flush=True)
                engine=Backtest(cfg,[strategy]).run(current,cal['open_dates'],set(cal['week_ends']),
                    evaluation_start='20251009',evaluation_end='20260930',universe=universe,progress=progress)
                for name,data in [('orders',engine.orders),('trades',engine.trades),('entry_audit',engine.entry_audits),('equity',engine.curve),('decisions',engine.events)]:
                    save_csv(folder/(name+'.csv'),data)
                if cost==1 and not candidate:
                    for name in ('orders','trades','entry_audit','equity'):
                        assert rows(folder/(name+'.csv'))==rows(OLD/oldname/(name+'.csv')),(label,name)
                summary=engine.summary();summary['case']=label
                summary['retry_signals']=sum(e['event']=='entry_intent' and bool(e.get('retry_origin')) for e in engine.events)
                summary['daily_support_raises']=sum(e['event']=='main_protection_raised' and e.get('source')=='confirmed_daily_higher_low' for e in engine.events)
                dump(folder/'summary.json',summary);summaries.append(summary)
                print('DONE',label,summary['total_return'],summary['filled_buys'],flush=True)
    save_csv(OUT/'comparison.csv',[{k:v for k,v in s.items() if k!='positions'} for s in summaries])
    dump(OUT/'status.json',dict(status='complete',cases=len(summaries)))


if __name__=='__main__':main()
