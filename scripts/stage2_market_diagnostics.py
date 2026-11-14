"""Descriptive market breadth, never a strategy input or validation set."""
import csv,json,sys
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trading_system.universe import MainboardUniverse

def main():
    base=ROOT/'runs/20261025-w-ihs-v7-shared-account'
    raw=json.loads((base/'universe.json').read_text(encoding='utf-8'))
    u=MainboardUniverse(raw['stocks'],raw['st_by_date'])
    cal=json.loads((base/'calendar.json').read_text(encoding='utf-8'))['open_dates']
    idx={d:i for i,d in enumerate(cal)};prev={};agg=defaultdict(lambda:[0,0.,0])
    with (base/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            s,d=r['symbol'],r['date'];v=float(r['close'])*float(r['factor'])
            if s in prev:
                pd,pv=prev[s];assert pd<d
                if ('20250901'<=d<='20260930' and idx.get(d,-9)==idx.get(pd,-99)+1
                        and u.eligible(s,d) and u.eligible(s,pd) and float(r['volume'])>0):
                    ret=v/pv-1;a=agg[d];a[0]+=1;a[1]+=ret;a[2]+=ret>0
            prev[s]=(d,v)
    rows=[];value=1.;values=[]
    for d,(n,total,up) in sorted(agg.items()):
        value*=1+total/n;values.append(value)
        rows.append(dict(date=d,stocks=n,equal_weight_return=total/n,advancing_share=up/n,
                         index=value,return20=value/values[-21]-1 if len(values)>20 else None))
    out=ROOT/'runs/20261026-book-stage2-market';out.mkdir(exist_ok=True)
    with (out/'market-proxy.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    (out/'method.json').write_text(json.dumps(dict(source=str(base/'bars.csv'),
        method='equal weighted economic close returns; consecutive sessions, dated eligibility both days, positive volume today',
        use='descriptive; entry uses previous session only; not an official index or trading input',known_sample=True),indent=2),encoding='utf-8')
    print(len(rows),'market sessions',min(r['stocks'] for r in rows),max(r['stocks'] for r in rows))
if __name__=='__main__':main()
