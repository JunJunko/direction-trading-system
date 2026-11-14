"""Transfer frozen W C0-C4 exit management to IHS: fixed lots and shared accounts."""
import copy
import csv
import hashlib
import json
import math
import shutil
from collections import defaultdict, Counter
from dataclasses import replace
from backtest_ihs_stop_comparison import (ROOT, BASE, FrozenSignals, Bar, Backtest,
    MainboardUniverse, save_csv, load, dump, sha)
from trading_system.domain import Position
from trading_system.strategies.causal_target_w import CausalTargetW
from trading_system.target_migration import RESEARCH_PARAMETERS

OLD=ROOT/'runs/20261025-ihs-head-vs-right-shoulder'
OUT=ROOT/'runs/20261025-ihs-causal-exits'
ARMS=('C0','C1','C2','C3','C4')

def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

class IHSExitReplay(FrozenSignals):
    def __init__(self,name,plans,arm):
        super().__init__(name,plans,'right_shoulder')
        self.manager=CausalTargetW(name,dict(target_arm=arm))
    def set_calendar(self,calendar):
        self.manager.set_calendar(calendar)
    def manage_position(self,history,position):
        # W manager only uses these two price fields. Mirror current IHS levels
        # after engine factor adjustment, never recompute from future bars.
        position.plan['w_neckline']=position.plan['ihs_neckline']
        position.plan['w_target']=position.plan['ihs_target']
        exits,events=self.manager.manage_position(history,position)
        return [replace(e,reason='ihs_target_close_confirmed') if e.reason=='w_target_close_confirmed'
                else e for e in exits],events

def save_engine(folder,e):
    folder.mkdir(parents=True)
    for name,data in [('orders',e.orders),('trades',e.trades),('entry_audit',e.entry_audits),('equity',e.curve)]:
        save_csv(folder/(name+'.csv'),data)
    with (folder/'events.jsonl').open('w',encoding='utf-8') as f:
        for event in e.events:f.write(json.dumps(event,ensure_ascii=False)+'\n')

def audit_events(events):
    changes=0
    for e in events:
        if e.get('event')!='target_migration':continue
        assert e['t_formed']<=e['t_confirmed']<=e['t_detected']<e['valid_from']
        if e['valid_from_date']:assert e['date']<e['valid_from_date']
        if e.get('action')=='raise_stop_next_bar':
            assert e['new_stop']>e['old_stop'];changes+=1
    return changes

def main():
    OUT.mkdir()
    plans=load(OLD/'paired-plans.json');config=load(OLD/'config.json')
    cal=load(BASE/'calendar.json');ud=load(BASE/'universe.json')
    universe=MainboardUniverse(ud['stocks'],ud['st_by_date'])
    assert sha(BASE/'bars.csv')==load(BASE/'manifest.json')['bars_sha256']
    for rel in ('strategies/causal_target_w.py','target_migration.py'):
        assert sha(BASE/'source/src/trading_system'/rel)==sha(ROOT/'src/trading_system'/rel)
    shutil.copytree(BASE/'source/src',OUT/'source/src',ignore=shutil.ignore_patterns('__pycache__'))
    for script in (__file__,ROOT/'scripts/backtest_ihs_stop_comparison.py'):
        shutil.copy2(script,OUT/'source')
    dump(OUT/'protocol.json',dict(parameters=RESEARCH_PARAMETERS,arms=ARMS,
        signal_count=len(plans),stop='confirmed_right_shoulder_low',paired_entries=27,
        baseline=str(OLD),frozen_engine=str(BASE/'source/src'),
        evaluation_start='20251009',evaluation_end='20260930',
        paired='same actual entry date, price, quantity, fee, risk; no account re-gating',
        account='same 2925 signal tape; all original account gates applied; fills may differ',
        limitations=['previously studied snapshot, not independent holdout',
          'daily OHLC; no intraday ordering claims','synthetic factor share adjustment',
          'IHS duration/trend limitations unchanged; original RR threshold unchanged']))
    dump(OUT/'config.json',config)
    needed={p['symbol'] for p in plans};bars=[];by_symbol=defaultdict(list)
    print('Loading frozen population signal-stock bars',flush=True)
    with (BASE/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in needed:
                b=Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in
                    ('open','high','low','close','volume','factor','up_limit','down_limit')})
                bars.append(b);by_symbol[b.symbol].append(b)
    bars.sort(key=lambda b:(b.date,b.symbol))
    for v in by_symbol.values():v.sort(key=lambda b:b.date)
    account={};total_changes=0
    for arm in ARMS:
        strategy=IHSExitReplay(config['strategies'][0]['id'],plans,arm)
        e=Backtest(copy.deepcopy(config),[strategy]).run(bars,cal['open_dates'],set(cal['week_ends']),
            evaluation_start='20251009',evaluation_end='20260930',universe=universe)
        assert sum(x['event']=='entry_intent' for x in e.events)==2925
        folder=OUT/'account'/arm;save_engine(folder,e)
        if arm=='C0':
            for name in ('orders','trades','entry_audit','equity'):
                assert rows(folder/(name+'.csv'))==rows(OLD/'right_shoulder'/(name+'.csv')),name
            baseline=e
        total_changes+=audit_events(e.events)
        summary=e.summary();summary['exit_reasons']=dict(Counter(t['reason'] for t in e.trades))
        summary['candidate_count']=sum(x.get('reason_code')=='breakout_candidate' for x in e.events)
        dump(folder/'summary.json',summary);account[arm]=summary
        print(json.dumps(dict(mode='account',arm=arm,return_pct=summary['total_return']*100,
            drawdown_pct=-summary['max_drawdown']*100,buys=summary['filled_buys'],closed=summary['closed_trades']),ensure_ascii=False),flush=True)
    entries=[a for a in baseline.entry_audits if a['execution_reason']=='filled']
    assert len(entries)==27
    dump(OUT/'frozen-entries.json',entries)
    pmap={p['setup_id']:p for p in plans};oldtrades={t['setup_id']:t for t in baseline.trades}
    dates=[d for d in cal['open_dates'] if '20251009'<=d<='20260930']
    paired={};allrecords=[]
    for arm in ARMS:
        lotcurves=[];records=[];allevents=[];allorders=[]
        for a in entries:
            pid=a['setup_id'];symbol=a['symbol'];p=pmap[pid]
            s=IHSExitReplay(a['strategy'],[],arm);s.set_calendar(cal['open_dates'])
            e=Backtest(copy.deepcopy(config),[s]);history=by_symbol[symbol]
            e.histories[symbol]=[b for b in history if b.date<a['date']]
            e.marks[symbol]=e.histories[symbol][-1].close
            daily={b.date:b for b in history};curve={};mfe=0.;mae=0.;held=0
            stop_source='original';stop_at_exit=None;attribution=None
            for d in dates:
                if d<a['date']:curve[d]=(0.,0.,0);continue
                b=daily.get(d);today={symbol:b} if b else {}
                e.adjust_factors(today,d)
                if d==a['date']:
                    plan={k:v for k,v in p.items() if k!='right_stop'}
                    scale=p['factor']/b.factor
                    for k in ('ihs_neckline','ihs_floor','ihs_target','breakout_reference'):plan[k]*=scale
                    plan['ihs_stop_rule']='right_shoulder'
                    pos=Position(a['strategy'],symbol,d,a['fill'],a['filled_quantity'],a['stop'],
                        a['expected_loss'],a['entry_fee'],pid,b.factor,plan,a['fill'])
                    e.positions[symbol]=pos;e.cash-=pos.entry*pos.quantity+pos.entry_fee
                    e.orders.append(dict(date=d,symbol=symbol,side='buy',price=pos.entry,quantity=pos.quantity,fee=pos.entry_fee,status='filled',setup_id=pid))
                    if b.low<=pos.stop:pos.plan['t1_stop_breached_at']=d
                else:
                    if symbol in e.positions:
                        stop_source=e.positions[symbol].plan.get('c_exit_risk_source','original')
                        stop_at_exit=e.positions[symbol].stop
                    e.execute_interval(today,d,universe,e.cash)
                if b:e.histories[symbol].append(b);e.marks[symbol]=b.close
                if symbol in e.positions and b:
                    pos=e.positions[symbol];held+=1
                    mfe=max(mfe,(b.high-pos.entry)*pos.quantity);mae=min(mae,(b.low-pos.entry)*pos.quantity)
                    exits,events=s.manage_position(e.histories[symbol],pos)
                    e.events.extend(events);e.pending_exits.extend(exits)
                gross=sum(pos.quantity*e.marks[sym] for sym,pos in e.positions.items())
                curve[d]=(e.cash-config['initial_cash'],gross,len(e.positions))
            assert len(e.trades)<=1
            terminal=e.trades[0] if e.trades else None
            pnl=terminal['pnl'] if terminal else e.equity()-config['initial_cash']
            if arm=='C0':
                original=oldtrades.get(pid)
                assert (terminal is None)==(original is None)
                if original:
                    for k in ('entry_date','exit_date','reason'):assert terminal[k]==original[k]
                    for k in ('entry','exit','quantity','pnl','realized_r'):assert math.isclose(terminal[k],original[k],abs_tol=1e-7)
            reason=terminal['reason'] if terminal else 'OPEN_MARKED'
            record=dict(arm=arm,setup_id=pid,symbol=symbol,entry_date=a['date'],entry=a['fill'],
                quantity=a['filled_quantity'],entry_fee=a['entry_fee'],initial_stop=a['stop'],initial_risk=a['expected_loss'],
                exit_date=terminal['exit_date'] if terminal else None,exit=terminal['exit'] if terminal else None,
                net_pnl=pnl,reason=reason,realized_r=terminal['realized_r'] if terminal else None,
                stop_at_exit=stop_at_exit if terminal else None,
                exit_source=stop_source if 'break' in reason else 'target_or_candidate' if terminal else 'open',
                held_bars=held,MFE=mfe,MAE=mae,giveback=max(0,mfe-pnl))
            records.append(record);lotcurves.append(curve)
            allevents.extend(e.events);allorders.extend(e.orders)
        curve=[];peak=config['initial_cash']
        for d in dates:
            cash=config['initial_cash']+sum(c[d][0] for c in lotcurves);gross=sum(c[d][1] for c in lotcurves)
            equity=cash+gross;peak=max(peak,equity)
            curve.append(dict(date=d,cash=cash,equity=equity,drawdown=equity/peak-1,open_lots=sum(c[d][2] for c in lotcurves)))
        if arm=='C0':
            for actual,expected in zip(curve,baseline.curve):
                for k in ('cash','equity','drawdown'):assert math.isclose(actual[k],expected[k],abs_tol=1e-7)
        folder=OUT/'paired'/arm;folder.mkdir(parents=True)
        for name,data in [('trades',records),('equity',curve),('orders',allorders)]:save_csv(folder/(name+'.csv'),data)
        with (folder/'events.jsonl').open('w',encoding='utf-8') as f:
            for event in allevents:f.write(json.dumps(event,ensure_ascii=False)+'\n')
        closed=[r for r in records if r['exit_date']]
        summary=dict(filled_buys=27,closed_trades=len(closed),open_positions=27-len(closed),
            total_return=curve[-1]['equity']/config['initial_cash']-1,max_drawdown=min(r['drawdown'] for r in curve),
            win_rate=sum(r['net_pnl']>0 for r in closed)/len(closed) if closed else None,
            candidate_count=sum(x.get('reason_code')=='breakout_candidate' for x in allevents),
            exit_reasons=dict(Counter(r['reason'] for r in records)),min_cash=min(r['cash'] for r in curve))
        dump(folder/'summary.json',summary);paired[arm]=summary;allrecords.extend(records)
        total_changes+=audit_events(allevents)
        print(json.dumps(dict(mode='paired',arm=arm,**summary),ensure_ascii=False),flush=True)
    signatures={arm:[(r['setup_id'],r['entry_date'],r['entry'],r['quantity'],r['entry_fee'],r['initial_stop'],r['initial_risk']) for r in allrecords if r['arm']==arm] for arm in ARMS}
    assert all(s==signatures['C0'] for s in signatures.values())
    save_csv(OUT/'paired-trades.csv',allrecords)
    dump(OUT/'comparison.json',dict(account=account,paired=paired))
    dump(OUT/'verification.json',dict(account_C0_exact=True,paired_C0_exact=True,
        all_27_entry_signatures_equal=True,all_signal_tapes_equal=True,
        risk_changes_temporally_valid=total_changes,parameters_unchanged=True,
        source_hashes={str(p.relative_to(OUT)):sha(p) for p in (OUT/'source').rglob('*.py')},
        plans_sha256=sha(OLD/'paired-plans.json'),bars_sha256=sha(BASE/'bars.csv')))
    print('COMPLETE '+str(OUT),flush=True)

if __name__=='__main__':main()
