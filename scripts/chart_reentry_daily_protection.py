"""Observed daily candles with paired actual fills and next-session support lines."""
from dataclasses import replace
from backtest_reentry_daily_protection import OUT, rows, dump
from audit_pattern_trade_paths import history
from audit_candidate_policy import candles, plt

CASES=[('W','600900.SH','20260528'),('W','600397.SH','20251215'),
       ('IHS','002541.SZ','20260202'),('IHS','001326.SZ','20260203'),
       ('IHS','603989.SH','20260508'),('IHS','605117.SH','20251215')]

def main():
    hist=history({s for _,s,_ in CASES});dest=OUT/'charts';dest.mkdir(exist_ok=True)
    index=[]
    for family,symbol,entry in CASES:
        datasets={arm:{key:rows(OUT/f'{family}_{arm}_cost1'/(key+'.csv')) for key in ('trades','entry_audit','decisions')} for arm in ('baseline','candidate')}
        if symbol=='600900.SH':
            retry=next(t for t in datasets['candidate']['trades'] if t['symbol']==symbol and ':retry:' in t['setup_id'])
            pid=retry['setup_id'].split(':retry:')[0]
            entry=next(t['entry_date'] for t in datasets['baseline']['trades'] if t['setup_id']==pid)
        base=next(t for t in datasets['baseline']['trades'] if t['symbol']==symbol and t['entry_date']==entry)
        pid=base['setup_id'];stock=hist[symbol];lookup={b.date:i for i,b in enumerate(stock)};ref=stock[lookup[entry]].factor
        selected={arm:[t for t in data['trades'] if t['setup_id']==pid or t['setup_id'].startswith(pid+':retry:')] for arm,data in datasets.items()}
        start=max(0,lookup[entry]-9);end=min(len(stock),max(lookup[t['exit_date']] for ts in selected.values() for t in ts)+16)
        view=[replace(b,**{k:getattr(b,k)*b.factor/ref for k in ('open','high','low','close')}) for b in stock[start:end]]
        ix={b.date:i for i,b in enumerate(view)}
        fig,axes=plt.subplots(2,1,figsize=(13,8),sharex=True,layout='constrained')
        for ax,(arm,data) in zip(axes,datasets.items()):
            candles(ax,view)
            for t in selected[arm]:
                a=next(a for a in data['entry_audit'] if a['setup_id']==t['setup_id'] and a['execution_reason']=='filled')
                es=stock[lookup[a['date']]].factor/ref
                ax.scatter(ix[a['date']],float(a['fill'])*es,marker='^',s=65,color='#1748b0',zorder=6,label='Buy '+a['date'])
                ax.scatter(ix[t['exit_date']],float(t['exit'])*stock[lookup[t['exit_date']]].factor/ref,marker='v',s=65,color='#171a24',zorder=6,label='Sell '+t['exit_date'])
                ax.hlines(float(a['stop'])*es,ix[a['date']],ix[t['exit_date']],colors='#b6527d',linestyles='--',label='Initial stop')
                events=[e for e in data['decisions'] if e['setup_id']==t['setup_id'] and e['event']=='main_protection_raised']
                levels=[]
                for b in view:
                    known=[e for e in events if e['date']<b.date]
                    levels.append(float(known[-1]['new'])/ref if known and a['date']<=b.date<=t['exit_date'] else float('nan'))
                ax.step(range(len(view)),levels,where='post',color='#8b54be',lw=1.5,label='Active support (next session)')
                for e in events:
                    if e.get('source')=='confirmed_daily_higher_low' and e['date'] in ix:
                        ax.scatter(ix[e['date']],float(e['new'])/ref,marker='o',s=26,color='#e59425',label='Daily support confirmed '+e['date'])
            if family=='W':
                plan=next(e for e in data['decisions'] if e['setup_id']==pid and e['event']=='entry_intent')
                pf=stock[lookup[plan['date']]].factor/ref
                ax.axhline(float(plan['w_neckline'])*pf,color='#c28f28',ls=':',label='Original neckline')
                ax.axhline(float(plan['target'])*pf,color='#758598',ls=':',label='Original target')
                for e in data['decisions']:
                    if e.get('retry_origin')==pid and e['event']=='entry_intent':
                        d=e['retry_low_date'];ax.annotate('New low '+d+'\nconfirmed '+e['retry_confirmed_at'],(ix[d],view[ix[d]].low),xytext=(10,-30),textcoords='offset points',fontsize=8,arrowprops={'arrowstyle':'->'})
            total=sum(float(t['pnl']) for t in selected[arm])
            ax.set_title(f'{symbol} | {family} | {arm} | recorded net P/L {total:+,.2f} CNY')
            ax.legend(fontsize=7,ncols=2,loc='upper left')
            ax.set_ylabel('Price, entry-date factor basis')
        name=f'{family}-{symbol}.png';fig.savefig(dest/name,dpi=125);plt.close(fig)
        index.append(dict(family=family,symbol=symbol,entry=entry,setup_id=pid,chart='charts/'+name))
    dump(dest/'index.json',index);print('Rendered',len(index),'paired charts')

if __name__=='__main__':main()
