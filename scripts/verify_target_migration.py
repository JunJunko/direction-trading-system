"""Frozen actual-entry, isolated-lot exit experiment. Never changes production config."""
import sys,json,csv,copy,hashlib,shutil,random
from pathlib import Path
sys.path.insert(0,'src');sys.path.insert(0,'scripts')
from trading_system.domain import Bar,Intent,Position
from trading_system.engine import Backtest
from trading_system.strategies.qualified_w_retest import QualifiedWRetest
from trading_system.strategies.target_migration_w import TargetMigrationW
from trading_system.target_migration import State,RESEARCH_PARAMETERS
from trading_system.universe import MainboardUniverse
from trading_system.data import save_csv
from backtest_daily_direction import assert_recorded

ROOT=Path('runs/20261024-qualified-w-cohort')
OUT=Path(sys.argv[1] if len(sys.argv)>1 else 'runs/20261024-target-migration-paired')
load=lambda p:json.loads(p.read_text(encoding='utf-8'))
def rows(p):
    with p.open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))
def dump(p,data):p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    OUT.mkdir() # Refuse to overwrite a frozen experiment.
    config=load(ROOT/'candidate/config.json');plans=load(ROOT/'plans.json')
    cal=load(ROOT/'calendar.json');u=load(ROOT/'universe.json')
    bars=[Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}) for r in rows(ROOT/'bars.csv')]
    universe=MainboardUniverse(u['stocks'],u['st_by_date'])
    dates=[d for d in cal['open_dates'] if '20251009'<=d<='20260930']
    class Replay(QualifiedWRetest):
        def on_close(self,history,week_ends):
            b=history[-1]
            return [Intent(self.name,p['symbol'],p['date'],p['trigger'],p['stop'],p['target'],p['setup_id'],'direct_w',dict(p)) for p in plans if p['date']==b.date and p['symbol']==b.symbol],[]
    s=Replay(config['strategies'][0]['id'],config['strategies'][0]['params'])
    old=Backtest(config,[s]).run(bars,cal['open_dates'],set(cal['week_ends']),evaluation_start=dates[0],evaluation_end=dates[-1],universe=universe)
    for name,records in [('orders',old.orders),('trades',old.trades),('entry_audit',old.entry_audits),('equity',old.curve)]:assert_recorded(ROOT/'candidate'/(name+'.csv'),records)
    assert old.summary()==load(ROOT/'candidate/summary.json')
    print('A0 original shared-account exact regression passed',flush=True)
    entries=[a for a in old.entry_audits if a['execution_reason']=='filled']
    by_symbol={symbol:sorted([b for b in bars if b.symbol==symbol],key=lambda b:b.date) for symbol in {a['symbol'] for a in entries}}
    oldtrades={t['setup_id']:t for t in old.trades};results={};allpaired=[]
    dump(OUT/'frozen_entries.json',entries)
    for arm in ('A0','A1','B1','B2','B3'):
        folder=OUT/arm;folder.mkdir();c=copy.deepcopy(config)
        c['strategies'][0]['type']='target_migration_w'
        c['strategies'][0]['params'].update(target_arm=arm,minimum_price_tick=.01,target_parameters=RESEARCH_PARAMETERS)
        dump(folder/'config.json',c)
        events=[];orders=[];trades=[];lots=[]
        for a in entries:
            symbol=a['symbol'];pid=a['setup_id'];s=TargetMigrationW(a['strategy'],c['strategies'][0]['params'])
            e=Backtest(c,[s]);history=by_symbol[symbol];prior=[b for b in history if b.date<a['date']]
            e.histories[symbol]=prior.copy();e.marks[symbol]=prior[-1].close
            daily={b.date:b for b in history};curve={};gap=False;t1=False
            plan=copy.deepcopy(next(p for p in plans if p['setup_id']==pid and p['date']==a['signal_date']))
            risk=a['expected_loss'];fee=a['entry_fee'];q=a['filled_quantity'];fill=a['fill']
            peak_gain=0.;mae=0.;held=0
            for date in dates:
                if date<a['date']:curve[date]=(0.,0.,0,0.);continue
                b=daily.get(date);today={symbol:b} if b else {}
                e.adjust_factors(today,date)
                if date==a['date']:
                    assert b and b.volume>0
                    e.positions[symbol]=Position(a['strategy'],symbol,date,fill,q,a['stop'],risk,fee,pid,b.factor,plan,fill)
                    e.cash-=q*fill+fee
                    e.orders.append(dict(date=date,symbol=symbol,side='buy',price=fill,quantity=q,fee=fee,status='filled',setup_id=pid))
                    if b.low<=a['stop']:
                        t1=True;e.positions[symbol].plan['t1_stop_breached_at']=date
                        e.log(date,symbol,a['strategy'],'stop_deferred_t1',stop=a['stop'])
                else:
                    if symbol in e.positions and b:gap|=b.open<e.positions[symbol].stop
                    e.execute_interval(today,date,universe,e.cash)
                if b:
                    e.histories[symbol].append(b);e.marks[symbol]=b.close
                if symbol in e.positions and b:
                    held+=1;p=e.positions[symbol]
                    # Exit-day extrema are excluded: daily OHLC cannot prove they preceded exit.
                    peak_gain=max(peak_gain,(b.high-p.entry)*p.quantity)
                    mae=min(mae,(b.low-p.entry)*p.quantity)
                    ex,ev=s.manage_position(e.histories[symbol],p);e.events.extend(ev)
                    e.pending_exits.extend(ex)
                gross=sum(p.quantity*e.marks[sym] for sym,p in e.positions.items())
                openrisk=sum(max(0,p.entry-p.stop)*p.quantity for p in e.positions.values())
                curve[date]=(e.cash-c['initial_cash'],gross,len(e.positions),openrisk)
            terminal=e.trades[0] if e.trades else None
            assert len(e.trades)<=1
            ctx=s.contexts[pid]
            ev=[dict(x,trade_id=pid,signal_id=pid) for x in e.events]
            for order in e.orders:
                order.update(trade_id=pid,signal_id=pid)
                if order['side']=='sell':
                    ev.append(dict(event='target_migration',date=order['date'],trade_id=pid,signal_id=pid,symbol=symbol,
                        action='fill_exit',reason_code=terminal['reason'],state='EXITED',qty=order['quantity'],
                        fill_timestamp=order['date'],fill_price=order['price']))
                    ctx.state=State.EXITED
            pnl=terminal['pnl'] if terminal else e.equity()-c['initial_cash']
            exitdate=terminal['exit_date'] if terminal else None
            later=[daily[d] for d in dates[dates.index(exitdate)+1:dates.index(exitdate)+6] if d in daily] if exitdate else []
            miss=(max(0,max(b.high*b.factor for b in later)/(daily[exitdate].factor)-terminal['exit'])*terminal['quantity']) if later else None
            def first(reason):return next((x['date'] for x in ev if x.get('reason_code')==reason),None)
            def dt(idx):return e.histories[symbol][idx].date if idx is not None else None
            record=dict(arm=arm,trade_id=pid,symbol=symbol,entry_date=a['date'],entry_price=fill,quantity=q,
                entry_fee=fee,initial_stop=a['stop'],initial_risk=risk,exit_date=exitdate,
                exit_price=terminal['exit'] if terminal else None,reason=terminal['reason'] if terminal else 'OPEN_MARKED',
                net_pnl=pnl,realized_R_after_fees=pnl/risk if terminal else None,marked_R=pnl/risk,
                MFE=peak_gain,MAE=mae,max_profit_giveback=max(0,peak_gain-pnl),
                mfe_capture=pnl/peak_gain if peak_gain>0 else None,missed_upside_after_exit=miss,
                missed_upside_window=5,missed_upside_observations=len(later),holding_bars=held,
                whether_t1_hit=t1,any_gap_beyond_stop=gap,number_of_orders=len(e.orders),
                total_fees=sum(x['fee'] for x in e.orders),turnover=sum(x['price']*x['quantity'] for x in e.orders),
                target_touch_at=dt(ctx.target_touch_at),decisive_break_at=dt(ctx.breakout_candidate_at),
                acceptance_at=dt(ctx.trend_confirmed_at),retest_at=None,new_support_at=first('confirmed_support_available'),
                stop_raise_at=first('confirmed_support_stop_raised'),first_pressure_watch_at=None,eventual_exit_at=exitdate)
            base=oldtrades[pid]
            record.update(original_pnl=base['pnl'],original_R=base['realized_r'],original_winner=base['pnl']>0,
                delta_net_pnl=pnl-base['pnl'],delta_R=pnl/risk-base['realized_r'],
                delta_win_size=max(0,pnl)-max(0,base['pnl']),delta_loss_size=min(0,pnl)-min(0,base['pnl']))
            if arm=='A0':
                assert terminal and terminal['exit_date']==base['exit_date']
                assert terminal['reason']==base['reason']
                for key in ('entry','exit','quantity','pnl','realized_r'):assert abs(terminal[key]-base[key])<1e-7,(pid,key,terminal[key],base[key])
            trades.append(record);events.extend(ev);orders.extend(e.orders);lots.append(curve)
        curve=[];peak=c['initial_cash']
        for d in dates:
            cash=c['initial_cash']+sum(l[d][0] for l in lots);gross=sum(l[d][1] for l in lots)
            equity=cash+gross;peak=max(peak,equity)
            curve.append(dict(date=d,cash=cash,equity=equity,drawdown=equity/peak-1,gross_weight=gross/equity,
                open_lots=sum(l[d][2] for l in lots),open_risk=sum(l[d][3] for l in lots)/equity))
        if arm=='A0':
            for x,y in zip(curve,old.curve):
                assert x['date']==y['date']
                for key in ('cash','equity','drawdown'):assert abs(x[key]-y[key])<1e-7
        closed=[t for t in trades if t['exit_date']]
        rng=random.Random(20261024);delta=[t['delta_net_pnl'] for t in trades]
        draws=sorted(sum(rng.choices(delta,k=len(delta))) for _ in range(5000))
        summary=dict(arm=arm,entry_count=len(trades),closed_count=len(closed),open_count=len(trades)-len(closed),
            net_pnl=curve[-1]['equity']-c['initial_cash'],return_pct=(curve[-1]['equity']/c['initial_cash']-1)*100,
            max_drawdown_pct=-min(x['drawdown'] for x in curve)*100,win_rate=sum(t['net_pnl']>0 for t in closed)/len(closed),
            total_fees=sum(t['total_fees'] for t in trades),turnover=sum(t['turnover'] for t in trades),
            candidate_count=sum(bool(t['decisive_break_at']) for t in trades),accepted_count=sum(bool(t['acceptance_at']) for t in trades),
            support_trail_count=sum(bool(t['stop_raise_at']) for t in trades),
            min_cash=min(x['cash'] for x in curve),max_gross_weight=max(x['gross_weight'] for x in curve),
            max_open_lots=max(x['open_lots'] for x in curve),max_open_risk=max(x['open_risk'] for x in curve),
            paired_delta=sum(delta),exploratory_iid_trade_bootstrap_95=[draws[125],draws[4874]],
            original_winners_delta=sum(t['delta_net_pnl'] for t in trades if t['original_winner']),
            original_losers_delta=sum(t['delta_net_pnl'] for t in trades if not t['original_winner']),
            cost_sensitivity_fixed_fills={str(mult):sum(t['net_pnl']-(mult-1)*t['total_fees'] for t in trades) for mult in (1,1.5,2)},
            calendar_quarters={quarter:sum(t['delta_net_pnl'] for t in trades if t['entry_date'][:4]+'Q'+str((int(t['entry_date'][4:6])-1)//3+1)==quarter) for quarter in ('2025Q4','2026Q1','2026Q2','2026Q3')})
        symbols=sorted({t['symbol'] for t in trades})
        symbol_deltas={symbol:sum(t['delta_net_pnl'] for t in trades if t['symbol']==symbol) for symbol in symbols}
        cluster=sorted(sum(symbol_deltas[x] for x in rng.choices(symbols,k=len(symbols))) for _ in range(5000))
        summary.update(symbol_cohorts=symbol_deltas,exploratory_symbol_cluster_bootstrap_95=[cluster[125],cluster[4874]],
            delta_vs_soft_A1=summary['net_pnl']-results['A1']['net_pnl'] if 'A1' in results else None,
            frozen_entry_signature=hashlib.sha256(json.dumps([(t['trade_id'],t['entry_date'],t['entry_price'],t['quantity'],t['entry_fee'],t['initial_stop']) for t in trades]).encode()).hexdigest())
        for name,data in [('trades',trades),('orders',orders),('equity',curve)]:save_csv(folder/(name+'.csv'),data)
        with (folder/'events.jsonl').open('w',encoding='utf-8') as f:
            for event in events:f.write(json.dumps(event,ensure_ascii=False)+'\n')
        dump(folder/'summary.json',summary);results[arm]=summary;allpaired.extend(trades)
        print(json.dumps(summary,ensure_ascii=False),flush=True)
    save_csv(OUT/'paired_trades.csv',allpaired)
    dump(OUT/'comparison.json',dict(baseline_exact=True,paired_A0_exact=True,results=results,
        scope='Frozen 14 actual entries; independent lots, shared cash aggregation; account entry gates NOT re-applied.',
        B4='NOT_RUN: missing original V23/V24 momentum definitions',independent_validation='NOT_RUN: repeatedly studied development cohort',
        MFE_MAE='Gross excursions on held end-of-day bars; entire exit-day range excluded to avoid unknowable intraday ordering.',
        cost_sensitivity='Fee-only stress at fixed fills; not a slippage/liquidity rerun. Quarter buckets are not market regimes.',
        bootstrap='Exploratory IID trade bootstrap, only 14 trades with repeated symbols; not independent inference.'))
    shutil.copytree('src',OUT/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree('tests',OUT/'source/tests',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(__file__,OUT/'source/verify_target_migration.py')
    dump(OUT/'sha256.json',{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in list((OUT/'source').rglob('*.py'))+[ROOT/'bars.csv',ROOT/'plans.json',ROOT/'candidate/config.json']})

if __name__=='__main__':main()
