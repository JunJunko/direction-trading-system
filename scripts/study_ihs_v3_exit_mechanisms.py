"""Frozen v3 first audit, then pre-registered E0-E3 fixed-lot experiments."""
import copy,csv,hashlib,json,math,shutil,sys
from collections import defaultdict,Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v3-retest'
OUT=ROOT/'runs/20261025-ihs-v3-exit-mechanisms'
sys.path.insert(0,str(BASE/'source/src'))
from trading_system.domain import Bar,Position
from trading_system.engine import Backtest
from trading_system.data import save_csv
from trading_system.universe import MainboardUniverse
from ihs_exit_research import ResearchExit,liquidation_net

def load(p):return json.loads(p.read_text(encoding='utf-8'))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def main():
    OUT.mkdir()
    config=load(BASE/'config.json');cal=load(BASE/'calendar.json');ud=load(BASE/'universe.json')
    entries=[a for a in rows(BASE/'entry_audit.csv') if a['execution_reason']=='filled']
    assert len(entries)==14
    plans={p['setup_id']:p for p in load(BASE/'plans.json')}
    oldtrades={t['setup_id']:t for t in rows(BASE/'trades.csv')}
    dates=[d for d in cal['open_dates'] if '20251009'<=d<='20260930']
    universe=MainboardUniverse(ud['stocks'],ud['st_by_date'])
    protocol=dict(phase_order=['E0 audit and exact regression','fixed-lot E1 E2 E3','entry-failure diagnostics','evaluation'],
        frozen_entries=14,entry_price_and_quantity_frozen=True,initial_R='original v3 expected_loss money, fixed across cost scenarios',
        E0='original right-shoulder stop and close-confirmed measured target',
        E1='estimated close liquidation net >= 1 original R; cost-inclusive breakeven stop from next exchange day',
        E2='higher confirmed post-entry low; left=2 right=2; 0.5 prior ATR14 buffer frozen on selection; from next exchange day',
        E3='E1 and E2, highest active protection',monotonic=True,target_exit='retained in every arm',
        stress={'base':1,'cost_1_5x':1.5,'cost_2x':2},
        cost_scope='commission rate and sell slippage multiplied; original buy fill fixed; entry commission recalculated; min fee5 and tax unchanged',
        MFE='held end-of-day bars only, whole exit day excluded; gross excursions, no claim of peak execution',
        capture=['own closed-lot MFE','same-lot E0 reference MFE over E0 holding horizon'],
        trend_cut_proxy='earlier than E0 end, positive realized PnL, within next20 exchange days (capped E0 end) a close estimated net exceeds realized PnL by >=1R; incomplete windows separate',
        no_parameter_search=True,production_strategy_changed=False,
        development_cutoff='20260930',holdout_accessed=False,
        future_validation=dict(start='20261102',end='20271029',minimum_closed_events=50,minimum_symbols=30,
            rules='freeze before any new data access; all eligible chronological v3 events; one final evaluation, insufficient events means extend without tuning',
            further_rules='no automatic production promotion; compare after-cost netR, drawdown, premature truncation and stock/time concentration'),
        scope='fixed independent lots; shared cash aggregation, account entry gates not re-applied; historical snapshot already studied')
    dump(OUT/'protocol.json',protocol);dump(OUT/'frozen-entries.json',entries)
    (OUT/'source').mkdir();shutil.copytree(BASE/'source/src',OUT/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
    for p in (Path(__file__),ROOT/'scripts/ihs_exit_research.py'):shutil.copy2(p,OUT/'source')
    dump(OUT/'input-hashes.json',{n:sha(BASE/n) for n in ('plans.json','config.json','bars.csv','entry_audit.csv','trades.csv','equity.csv','universe.json')})
    assert sha(BASE/'bars.csv')==load(BASE/'manifest.json')['bars_sha256']
    needed={a['symbol'] for a in entries};by=defaultdict(list)
    # Market context uses only completed signal-day data and its exact prior exchange sessions.
    marketdays={a['signal_date'] for a in entries};marketlook={}
    for d in marketdays:
        i=cal['open_dates'].index(d);marketlook[d]=(cal['open_dates'][i-1],cal['open_dates'][i-20])
    selected_dates=marketdays|{v for pair in marketlook.values() for v in pair};marketprices={}
    with (BASE/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['date']>'20260930':continue
            if r['date'] in selected_dates:
                marketprices[r['symbol'],r['date']]=float(r['close'])*float(r['factor'])
            if r['symbol'] in needed:
                by[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    for b in by.values():b.sort(key=lambda b:b.date)
    market={}
    for d,(prev,old) in marketlook.items():
        ret=[];daily=[]
        for symbol in universe.stocks:
            if not universe.eligible(symbol,d) or (symbol,d) not in marketprices:continue
            value=marketprices[symbol,d]
            if (symbol,old) in marketprices:ret.append(value/marketprices[symbol,old]-1)
            if (symbol,prev) in marketprices:daily.append(value/marketprices[symbol,prev]-1)
        import statistics
        market[d]=dict(market_observed_at=d,stocks_20d=len(ret),positive_20d_fraction=sum(r>0 for r in ret)/len(ret),
            median_20d_return=statistics.median(ret),stocks_daily=len(daily),daily_advancing_fraction=sum(r>0 for r in daily)/len(daily))
    dump(OUT/'market-context.json',market)
    results=[];allpaired=[];base_refs={};signatures=[];violations=[]
    for scenario,mult in protocol['stress'].items():
        c=copy.deepcopy(config);c['execution']['commission_rate']*=mult;c['execution']['slippage']*=mult
        for arm in ('E0','E1','E2','E3'):
            folder=OUT/scenario/arm;folder.mkdir(parents=True)
            records=[];dailyrows=[];events=[];curves=[];orders=[]
            for a in entries:
                pid=a['setup_id'];symbol=a['symbol'];history=by[symbol];daymap={b.date:b for b in history}
                entryday=a['date'];bentry=daymap[entryday];entryfactor=bentry.factor
                fill=float(a['fill']);qty=float(a['filled_quantity']);initialstop=float(a['stop']);risk=float(a['expected_loss'])
                fee=max(5,fill*qty*c['execution']['commission_rate'])
                e=Backtest(copy.deepcopy(c),[]);s=ResearchExit(a['strategy'],arm,c['execution'],cal['open_dates'])
                e.histories[symbol]=[b for b in history if b.date<entryday];e.marks[symbol]=e.histories[symbol][-1].close
                curve={};peak_price_units=fill;peak_close_net=-fee;mfe=0.;daysheld=0;laststate='NOT_ENTERED';lastsource='initial_right_shoulder'
                for d in dates:
                    if d<entryday:curve[d]=(0.,0.,0);continue
                    if d>entryday and symbol not in e.positions:
                        curve[d]=(e.cash-c['initial_cash'],0.,0);continue
                    b=daymap.get(d);today={symbol:b} if b else {};before_trades=len(e.trades);before_events=len(e.events)
                    e.adjust_factors(today,d)
                    if d==entryday:
                        plan=copy.deepcopy(plans[pid]);scale=plan['factor']/b.factor
                        for key in ('ihs_neckline','ihs_floor','ihs_target','ihs_right_low','ihs_retest_low','ihs_entry_ceiling','breakout_reference'):plan[key]*=scale
                        plan['factor']=b.factor
                        e.positions[symbol]=Position(a['strategy'],symbol,d,fill,qty,initialstop,risk,fee,pid,b.factor,plan,fill)
                        e.cash-=fill*qty+fee
                        e.orders.append(dict(date=d,symbol=symbol,side='buy',price=fill,quantity=qty,fee=fee,status='filled',setup_id=pid))
                        if b.low<=initialstop:e.positions[symbol].plan['t1_stop_breached_at']=d
                    p=e.positions[symbol];scale=entryfactor/p.factor;p.plan['research_initial_stop']=initialstop*scale
                    effective=p.stop;prestate=s.state;pre_source=s.source
                    if d!=entryday:e.execute_interval(today,d,universe,e.cash)
                    if b:e.histories[symbol].append(b);e.marks[symbol]=b.close
                    sold=len(e.trades)>before_trades
                    row=dict(scenario=scenario,arm=arm,setup_id=pid,symbol=symbol,date=d,
                        entry_date=entryday,entry_price_current_scale=p.entry,original_entry_fill=fill,
                        initial_stop_current_scale=initialstop*scale,neckline=p.plan['ihs_neckline'],
                        retest_low=p.plan['ihs_retest_low'],target=p.plan['ihs_target'],
                        open=b.open if b else None,high=b.high if b else None,low=b.low if b else None,close=b.close if b else None,
                        effective_stop=effective,stop_source_at_open=pre_source,state_at_open=prestate,
                        quantity=p.quantity,initial_R_money=risk,close_net_R=None,next_session_stop=None,
                        next_session=s.nextday.get(d),exit_trigger=None,simulated_fill=None,
                        known_holding_peak=peak_price_units*scale,close_observed_while_held=False)
                    if sold:
                        trade=e.trades[-1];row.update(state_at_close='EXITED',exit_trigger=trade['reason'],simulated_fill=trade['exit'],
                            realized_pnl=trade['pnl'],price_path_use='exit-day high/close not used for MFE or stop updates')
                        if 'break' in trade['reason']:
                            # Recompute original engine stop price independently, including pending blocked/T+1 stop.
                            deferred=bool(p.plan.get('t1_stop_breached_at') or p.plan.get('blocked_stop_breached_at'))
                            basis=b.open if deferred else min(b.open,effective)
                            expected=max(b.low,basis*(1-c['execution']['slippage']))
                            assert math.isclose(expected,trade['exit'],abs_tol=1e-9)
                        lastsource=pre_source
                    else:
                        if b:
                            daysheld+=1;peak_price_units=max(peak_price_units,b.high*b.factor/entryfactor)
                            mfe=max(mfe,(b.high-p.entry)*p.quantity)
                            exits,ev,net=s.manage(e.histories[symbol],p)
                            peak_close_net=max(peak_close_net,net)
                            for v in ev:
                                v.update(scenario=scenario,arm=arm)
                                if v['valid_from']:assert v['valid_from']>d
                                if 'formed' in v:assert v['formed']<=v['confirmed']<=d
                                if v['reason']=='stop_raised':assert v['new_stop']>v['old_stop']
                            events.extend(ev);e.pending_exits.extend(exits)
                            row.update(close_net_R=net/risk,close_observed_while_held=True,
                                known_holding_peak=peak_price_units*scale,decision_reasons=';'.join(v['reason'] for v in ev))
                        assert p.stop>=effective
                        row.update(next_session_stop=p.stop,state_at_close=s.state,next_stop_source=s.source)
                    row['engine_events']=';'.join(v['event'] for v in e.events[before_events:])
                    dailyrows.append(row)
                    gross=sum(p.quantity*e.marks[sym] for sym,p in e.positions.items())
                    curve[d]=(e.cash-c['initial_cash'],gross,len(e.positions))
                terminal=e.trades[0] if e.trades else None
                assert len(e.trades)<=1
                pnl=terminal['pnl'] if terminal else e.equity()-c['initial_cash']
                end=terminal['exit_date'] if terminal else dates[-1]
                if arm=='E0' and scenario=='base':
                    old=oldtrades.get(pid);assert bool(old)==bool(terminal)
                    if old:
                        for k in ('entry_date','exit_date','reason'):assert terminal[k]==old[k]
                        for k in ('entry','exit','quantity','pnl','realized_r'):assert math.isclose(terminal[k],float(old[k]),abs_tol=1e-7)
                    base_refs[pid]=dict(pnl=pnl,mfe=mfe,end=end)
                base=base_refs[pid]
                # Fixed reference horizon gives an honest denominator when experiments sell earlier.
                post=[];premature=False
                if terminal and end<base['end']:
                    following=[d for d in dates if end<d<=base['end']][:20]
                    for date in following:
                        if date not in daymap:continue
                        bar=daymap[date];value=bar.close*bar.factor/entryfactor*qty*(1-c['execution']['slippage'])
                        future_net=value-fill*qty-fee-max(5,value*c['execution']['commission_rate'])-value*c['execution']['sell_tax_after_20230828']
                        post.append(future_net)
                    premature=pnl>0 and bool(post) and max(post)>=pnl+risk
                record=dict(scenario=scenario,arm=arm,setup_id=pid,symbol=symbol,entry_date=entryday,
                    entry=fill,quantity=qty,entry_fee=fee,initial_stop=initialstop,initial_R=risk,
                    exit_date=terminal['exit_date'] if terminal else None,exit=terminal['exit'] if terminal else None,
                    reason=terminal['reason'] if terminal else 'OPEN_MARKED',exit_source=lastsource if terminal else s.source,
                    net_pnl=pnl,net_R=pnl/risk,closed=bool(terminal),own_MFE=mfe,E0_reference_MFE=base['mfe'],
                    own_MFE_capture=pnl/mfe if mfe>0 else None,reference_MFE_capture=pnl/base['mfe'] if base['mfe']>0 else None,
                    peak_close_net_R=peak_close_net/risk,profit_to_loss=bool(terminal and peak_close_net>0 and pnl<0),
                    at_least_1R_to_loss=bool(terminal and peak_close_net>=risk and pnl<0),
                    early_trend_cut_proxy=premature,post_exit_observations=len(post),
                    full20_post_exit=len(post)==20,post_exit_best_net_R=max(post)/risk if post else None,
                    holding_bars=daysheld,delta_vs_base_E0=pnl-base['pnl'])
                records.append(record);curves.append(curve);orders.extend(e.orders)
                signatures.append((scenario,arm,pid,entryday,fill,qty,initialstop,risk))
            aggregate=[];peak=c['initial_cash']
            for d in dates:
                cash=c['initial_cash']+sum(v[d][0] for v in curves);gross=sum(v[d][1] for v in curves)
                equity=cash+gross;peak=max(peak,equity)
                aggregate.append(dict(date=d,cash=cash,equity=equity,drawdown=equity/peak-1,open_lots=sum(v[d][2] for v in curves),gross_weight=gross/equity))
            if arm=='E0' and scenario=='base':
                for r,old in zip(aggregate,rows(BASE/'equity.csv')):
                    assert r['date']==old['date']
                    for k in ('cash','equity','drawdown'):assert math.isclose(r[k],float(old[k]),abs_tol=1e-7)
                dump(OUT/'phase1-audit.json',dict(E0_exact=True,code_path='static trailing_stop; target-close exit only',
                    moving_stop_exists=False,structure_confirmation_module_active=False,
                    note='No breakeven/structure activation state in original v3; static stop remains until target close. Daily execution independently reconciled.'))
                print('PHASE1 E0 trades and 241 equity/cash rows exact; original stop/target mechanism audited',flush=True)
            closed=[r for r in records if r['closed']]
            totalmfe=sum(r['own_MFE'] for r in closed);refmfe=sum(r['E0_reference_MFE'] for r in closed)
            result=dict(scenario=scenario,arm=arm,entries=14,closed=len(closed),open=14-len(closed),
                net_pnl=sum(r['net_pnl'] for r in records),return_pct=(aggregate[-1]['equity']/c['initial_cash']-1)*100,
                max_drawdown_pct=-min(r['drawdown'] for r in aggregate)*100,
                mean_net_R_all_including_open=sum(r['net_R'] for r in records)/14,
                mean_net_R_closed=sum(r['net_R'] for r in closed)/len(closed) if closed else None,
                win_rate_closed=sum(r['net_pnl']>0 for r in closed)/len(closed) if closed else None,
                own_MFE_capture_closed=sum(r['net_pnl'] for r in closed)/totalmfe if totalmfe else None,
                E0_reference_MFE_capture_closed=sum(r['net_pnl'] for r in closed)/refmfe if refmfe else None,
                profit_to_loss=sum(r['profit_to_loss'] for r in closed),at_least_1R_to_loss=sum(r['at_least_1R_to_loss'] for r in closed),
                early_trend_cut_full20=sum(r['early_trend_cut_proxy'] and r['full20_post_exit'] for r in records),
                early_trend_cut_partial=sum(r['early_trend_cut_proxy'] and not r['full20_post_exit'] for r in records),
                min_cash=min(r['cash'] for r in aggregate),max_open_lots=max(r['open_lots'] for r in aggregate),
                max_gross_weight=max(r['gross_weight'] for r in aggregate))
            for name,data in [('trades',records),('daily-audit',dailyrows),('orders',orders),('equity',aggregate),('events',events)]:save_csv(folder/(name+'.csv'),data)
            dump(folder/'summary.json',result);results.append(result);allpaired.extend(records)
            print(json.dumps(result),flush=True)
    assert len({tuple(v[2:]) for v in signatures})==14
    save_csv(OUT/'paired-trades.csv',allpaired);save_csv(OUT/'comparison.csv',results)
    dump(OUT/'comparison.json',results)
    dump(OUT/'verification.json',dict(E0_exact=True,original_entries_identical_all_12_runs=True,
        source_production_unmodified=True,rows=len(allpaired),audit='stops after close, applied next bar; confirmed structure only',
        snapshot_end='20260930',out_of_sample_data_accessed=False,
        source_hashes={str(p.relative_to(OUT)):sha(p) for p in (OUT/'source').rglob('*.py')}))
    print('COMPLETE',flush=True)

if __name__=='__main__':main()
