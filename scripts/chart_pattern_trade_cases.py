"""Render the selected audit cases from their original plans and observed daily bars."""
import json
from dataclasses import replace

from audit_candidate_policy import candles, plt, neckline_at
from audit_pattern_trade_paths import OUT, IHS_SCAN, W_SCAN, history, load, rows, tail

CASES = [
    ('W', '001206.SZ', '20260417'),  # tight stop and no follow-through
    ('W', '600397.SH', '20251215'),  # stop, later recovery
    ('W', '002180.SZ', '20251229'),  # successful short W
    ('W', '603270.SH', '20260529'),  # long W with ambiguous larger context
    ('IHS', '002800.SZ', '20260819'),  # proportionate shoulders
    ('IHS', '002541.SZ', '20260202'),  # gain before protection loss
    ('IHS', '603989.SH', '20260508'),  # profitable long shape with tiny shoulders
]


def scaled(bar, base_factor):
    return replace(bar, **{key: getattr(bar, key)*bar.factor/base_factor
                           for key in ('open','high','low','close')})


def draw(record, plan, stock, path):
    lookup = {bar.date: i for i,bar in enumerate(stock)}
    left, right, signal, entry, exit_date = (lookup[record[k]] for k in ('left','right','signal','entry','exit'))
    reference = stock[signal].factor
    start = max(0,left-24)
    structure = [scaled(bar,reference) for bar in stock[start:signal+1]]
    fig,(ax,hold) = plt.subplots(2,1,figsize=(12,7),layout='constrained')
    candles(ax,structure)
    if record['family']=='W':
        peak = max(range(left+1,right),key=lambda i:stock[i].high*stock[i].factor)
        points = [(left,'L','low'),(peak,'mid high','high'),(right,'R','low')]
        ax.axhline(plan['w_neckline'],color='#bc8827',label='Signal neckline')
    else:
        points = [(lookup[plan[f'ihs_{key}_date']],label,kind) for key,label,kind in (
            ('left','L','low'),('peak1','P1','high'),('head','H','low'),('peak2','P2','high'),('right','R','low'))]
        ax.plot(range(len(structure)),[neckline_at(plan,bar.date) for bar in structure],color='#bc8827',label='Signal neckline')
    anchors = [(i-start,getattr(structure[i-start],kind),label) for i,label,kind in points]
    ax.plot([i for i,_,_ in anchors],[p for _,p,_ in anchors],marker='o',ls='--',color='#245bad',lw=1)
    for i,p,label in anchors:
        ax.annotate(label+' '+structure[i].date,(i,p),xytext=(4,6),textcoords='offset points',fontsize=7)
    ax.axvline(signal-start,color='#5e6774',ls=':',label='Signal close')
    ax.set_title(f"{record['symbol']} | {record['family']} | signal {record['signal']} | span {record['span']} stock sessions")
    ax.legend(loc='upper right',fontsize=8)

    start = max(0,entry-4)
    end = max(exit_date+1,min(entry+20,len(stock)))
    held = [scaled(bar,stock[entry].factor) for bar in stock[start:end]]
    candles(hold,held)
    buy, stop, out = (float(record[k]) for k in ('entry_price','initial_stop','exit_price'))
    hold.axhline(stop,color='#ba466a',ls='--',label='Initial stop')
    hold.axhline(buy,color='#245bad',alpha=.6,label='Entry price')
    hold.axvspan(exit_date-start-.5,len(held)-.5,color='#e7eaf0',alpha=.6,label='Exit session and after')
    hold.scatter(entry-start,buy,marker='^',s=45,zorder=6,color='#245bad',label='Buy at open')
    exit_factor = stock[exit_date].factor/stock[entry].factor
    hold.scatter(exit_date-start,out*exit_factor,marker='v',s=45,zorder=6,color='#202939',label='Recorded sell')
    hold.set_title(f"{record['entry']} – {record['exit']} | {record['reason']} | net P/L {float(record['pnl']):+,.0f} CNY")
    hold.legend(loc='best',fontsize=8,ncols=2)
    fig.savefig(path,dpi=115)
    plt.close(fig)


def main():
    selected = {(r['family'],r['symbol'],r['entry']):r for r in rows(OUT/'trade-features.csv')}
    plans = {family:{(tail(p['setup_id']),p['date']):p for p in load(run/'plans.json')}
             for family,run in [('W',W_SCAN),('IHS',IHS_SCAN)]}
    chart_dir = OUT/'charts'
    chart_dir.mkdir(exist_ok=True)
    hist = history({symbol for _,symbol,_ in CASES})
    index = []
    for family,symbol,entry in CASES:
        record = selected[family,symbol,entry]
        plan = plans[family][tail(record['setup_id']),record['signal']]
        name = f'{family}-{symbol}-{entry}.png'
        draw(record,plan,hist[symbol],chart_dir/name)
        index.append(dict(family=family,symbol=symbol,entry=entry,chart=f'charts/{name}'))
    (chart_dir/'index.json').write_text(json.dumps(index,indent=2),encoding='utf-8')
    print(f'Rendered {len(index)} paired structure and holding charts')


if __name__=='__main__':
    main()
