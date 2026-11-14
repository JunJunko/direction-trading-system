"""Post-trade diagnostics; post-exit prices are hindsight, never trading inputs."""
import csv,json,sys
from pathlib import Path
from dataclasses import replace
from collections import defaultdict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.structure import swings,area

def read(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def main(folder):
    p=Path(folder);trades=read(p/'trades.csv')
    events=read(p/'warmup_decisions.csv')+read(p/'decisions.csv')
    plans={e['setup_id']:e for e in events if e['event']=='entry_intent'}
    symbols={t['symbol'] for t in trades};hist=defaultdict(list)
    with (p/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in symbols:
                hist[r['symbol']].append(Bar(r['symbol'],r['date'],*[float(r[k]) for k in
                    ['open','high','low','close','volume','factor','up_limit','down_limit']]))
    results=[];rules=[]
    for t in trades:
        raw=hist[t['symbol']];f=next(x.factor for x in raw if x.date==t['exit_date'])
        # Common exit-date units for comparison only; multiplication does not
        # change the historical ordering or the structural comparisons.
        bs=[replace(x,**{k:getattr(x,k)*x.factor/f for k in ['open','high','low','close']}) for x in raw]
        held=[b for b in bs if t['entry_date']<=b.date<t['exit_date']]
        after=[b for b in bs if b.date>t['exit_date']][:20]
        q=float(t['quantity']);entry=float(t['entry']);risk=float(t['pnl'])/float(t['realized_r'])
        def net(price):
            price*=.999
            return (price-entry)*q-max(5,entry*q*.0003)-max(5,price*q*.0003)-price*q*.0005
        high=max(held,key=lambda b:b.high);close=max(held,key=lambda b:b.close)
        results.append(dict(symbol=t['symbol'],entry_date=t['entry_date'],exit_date=t['exit_date'],
            days=len(held)+1,reason=t['reason'],pnl=round(float(t['pnl']),2),realized_r=round(float(t['realized_r']),2),
            peak_date=high.date,peak_high_r=round(net(high.high)/risk,2),peak_close_r=round(net(close.close)/risk,2),
            giveback_close_r=round(net(close.close)/risk-float(t['realized_r']),2),
            after20_high_pct=round(100*(max(b.high for b in after)/float(t['exit'])-1),2) if after else None,
            after20_close_pct=round(100*(after[-1].close/float(t['exit'])-1),2) if after else None))
        if t['reason']!='core_adjustment_expanded':continue
        ref=plans[t['setup_id']];scale=float(ref['factor'])/f
        duration=float(ref['correction_duration']);ar=float(ref['correction_area'])*scale
        ran=float(ref['correction_range'])*scale;last=None
        signal=next(e['date'] for e in events if e['event']=='exit_intent' and e['setup_id']==t['setup_id'])
        for i,b in enumerate(bs):
            if not t['entry_date']<=b.date<=signal:continue
            prefix=bs[:i+1];points=swings(prefix)
            peaks=[x for x in points if x.kind=='high' and bs[x.index].date>=t['entry_date']]
            expanded=False
            if peaks:
                pk=peaks[-1];d=i-pk.index;drop=pk.price-min(x.low for x in bs[pk.index:i+1]);a=area(prefix,pk.index,i)
                expanded=(d>duration and a>ar) or drop>ran
                if b.date==signal:
                    rules.append(dict(symbol=t['symbol'],entry=t['entry_date'],signal=b.date,peak=bs[pk.index].date,
                        current_days=d,reference_days=duration,current_area=round(a,3),reference_area=round(ar,3),
                        current_drop=round(drop,3),reference_drop=round(ran,3),
                        peak_price=round(pk.price,3),signal_close=round(b.close,3),
                        new_high_after_peak=max(x.high for x in bs[pk.index+1:i+1])>pk.price,
                        signal_close_above_peak=b.close>pk.price,
                        time_and_area=d>duration and a>ar,range_only=drop>ran and not(d>duration and a>ar)))
            lows=[x for x in points if x.kind=='low' and bs[x.index].date>t['entry_date']]
            if lows and not expanded:
                lo=lows[-1];his=[x for x in points if x.kind=='high' and x.index<lo.index]
                if his and bs[lo.index].date!=last:
                    hi=his[-1];duration=lo.index-hi.index;ar=area(prefix,hi.index,lo.index)
                    ran=hi.price-lo.price;last=bs[lo.index].date
    with (p/'holding_audit.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=results[0].keys());w.writeheader();w.writerows(results)
    (p/'exit_rule_audit.json').write_text(json.dumps(rules,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(holding=results,exit_rules=rules),ensure_ascii=False,indent=2))

if __name__=='__main__':main(sys.argv[1])
