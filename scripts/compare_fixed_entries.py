"""Isolate exits on original fills; independent lots, not a portfolio backtest."""
import csv,json,sys
from pathlib import Path
from dataclasses import replace
from collections import defaultdict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar,Position
from trading_system.strategies.direction_double_bottom import DirectionDoubleBottom
from trading_system.strategies.autonomous_double_bottom import AutonomousDoubleBottom

def read(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def main(snapshot,out,mode='active_correction'):
    snapshot,out=Path(snapshot),Path(out)
    trades=read(snapshot/'trades.csv');events=read(snapshot/'warmup_decisions.csv')+read(snapshot/'decisions.csv')
    plans={x['setup_id']:x for x in events if x['event']=='entry_intent'}
    symbols={t['symbol'] for t in trades};raw=defaultdict(list);directions=defaultdict(dict)
    for e in events:
        if e['event'] in ('upper_direction_confirmed','upper_direction_lost'):
            directions[e['symbol']][e['date']]='long' if e['event']=='upper_direction_confirmed' else 'unknown'
    with (snapshot/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in symbols:
                raw[r['symbol']].append(Bar(r['symbol'],r['date'],*[float(r[k]) for k in
                    ('open','high','low','close','volume','factor','up_limit','down_limit')]))
    output=[]
    for t in trades:
        symbol=t['symbol'];original=raw[symbol]
        factor=next(b.factor for b in original if b.date==t['entry_date'])
        final_factor=next(b.factor for b in original if b.date==t['exit_date'])
        # Use original prices and the engine's sequential factor rebasing.
        # Normalizing the whole series once can change strict floating point
        # comparisons at equal adjustment widths, so it is not an exact replay.
        bars=original
        entry=float(t['entry'])*final_factor/factor;q=float(t['quantity'])*factor/final_factor
        risk=float(t['pnl'])/float(t['realized_r']);plan=dict(plans[t['setup_id']])
        scale=float(plan['factor'])/factor
        for k in ('correction_area','correction_range','target','stop'):
            plan[k]=float(plan[k])*scale
        plan['correction_duration']=float(plan['correction_duration'])
        stop=plan['stop'];entryfee=max(5,entry*q*.0003)
        strategy=(AutonomousDoubleBottom('fixed',dict(lower_cycle='daily_nested',protection_mode='live_leg' if mode=='live_leg' else 'entry_scale')) if mode in ('core_owned','live_leg')
                  else DirectionDoubleBottom('fixed',dict(exit_mode=mode)))
        position=Position('fixed',symbol,t['entry_date'],entry,q,stop,risk,entryfee,t['setup_id'],factor,plan)
        pending=None;state='unknown';peak_net=0;result=None
        for i,b in enumerate(bars):
            state=directions[symbol].get(b.date,state)
            if b.date<t['entry_date']:continue
            if b.factor!=position.factor:
                scale=position.factor/b.factor
                position.quantity/=scale;position.entry*=scale;position.stop*=scale
                position.max_price*=scale;position.factor=b.factor
                for key in ('symmetry_target','pressure_target','correction_area','correction_range',
                            'weekly_correction_area','weekly_correction_range'):
                    if position.plan.get(key) not in (None,''):
                        position.plan[key]=float(position.plan[key])*scale
            if b.date>t['entry_date']:
                blocked=b.volume<=0 or (b.down_limit and b.high<=b.down_limit+.00001)
                if b.low<=position.stop and not blocked:
                    price=max(b.low,min(b.open,position.stop)*.999);reason='structural_stop'
                elif pending and not blocked:
                    price=max(b.low,b.open*.999);reason=pending
                else:price=None
                if price is not None:
                    amount=price*position.quantity
                    pnl=(price-position.entry)*position.quantity-entryfee-max(5,amount*.0003)-amount*.0005
                    result=dict(exit_date=b.date,exit_reason=reason,pnl=round(pnl,2),realized_r=round(pnl/risk,3))
                    break
            amount=b.high*.999*position.quantity
            peak_net=max(peak_net,(b.high*.999-position.entry)*position.quantity-entryfee-max(5,amount*.0003)-amount*.0005)
            strategy.states[symbol]=dict(direction=state)
            exits,_=strategy.manage_position(bars[:i+1],position)
            pending=exits[0].reason if exits else None
            position.stop=max(position.stop,strategy.trailing_stop(bars[:i+1],position))
        if result is None:
            price=bars[-1].close
            pnl=(price-position.entry)*position.quantity-entryfee
            result=dict(exit_date='',exit_reason='open_mark',pnl=round(pnl,2),realized_r=round(pnl/risk,3))
        output.append(dict(symbol=symbol,entry_date=t['entry_date'],old_exit=t['exit_date'],old_reason=t['reason'],
            old_pnl=float(t['pnl']),old_r=float(t['realized_r']),**result,
            improvement=round(result['pnl']-float(t['pnl']),2),peak_net_r=round(peak_net/risk,3)))
    out.mkdir(exist_ok=True)
    with (out/'fixed-entry-comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=output[0].keys());w.writeheader();w.writerows(output)
    print(json.dumps(output,ensure_ascii=False,indent=2))

if __name__=='__main__':main(sys.argv[1],sys.argv[2],sys.argv[3] if len(sys.argv)>3 else 'active_correction')
