"""Show the roles and timing of each actual strategy line, without proposing fills."""
from dataclasses import replace
from audit_ihs_price_lines import OUT,BASE,rows,load,dump,history
from audit_candidate_policy import candles,plt
from trading_system.ihs_geometry import neckline_at

def main():
    records=rows(OUT/'price-lines.csv');events=rows(BASE/'decisions.csv')
    selected=[r for r in records if r['symbol'] in ('603989.SH','002541.SZ','001326.SZ')]
    hist=history({r['symbol'] for r in selected});dest=OUT/'charts';dest.mkdir(exist_ok=True);index=[]
    for r in selected:
        h=hist[r['symbol']];ix={b.date:i for i,b in enumerate(h)};entry=ix[r['entry']];exit=ix[r['exit']];factor=h[entry].factor
        p=next(e for e in events if e['setup_id']==r['setup_id'] and e['event']=='entry_intent')
        scale=h[ix[r['signal']]].factor/factor
        anchors={k:(float(p[k])*scale if k.endswith('_price') else p[k]) for k in ('ihs_peak1_date','ihs_peak2_date','ihs_peak1_price','ihs_peak2_price')}
        raises=[e for e in events if e['setup_id']==r['setup_id'] and e['event']=='main_protection_raised']
        fig,axes=plt.subplots(2,1,figsize=(12,8),layout='constrained')
        for j,ax in enumerate(axes):
            lo=max(0,entry-6);hi=min(len(h),exit+7 if j==0 else entry+16)
            view=[replace(b,**{k:getattr(b,k)*b.factor/factor for k in ('open','high','low','close')}) for b in h[lo:hi]];candles(ax,view)
            ax.plot(range(len(view)),[neckline_at(anchors,b.date) for b in view],color='#bd8c29',label='Frozen sloped neckline (entry reference)')
            ax.axhline(float(r['initial_stop']),color='#bd4567',ls='--',label='Initial hard stop: right low - 0.5 ATR')
            ax.axhline(float(r['buy']),color='#4872b9',ls=':',label='Actual buy price')
            if j==0:ax.axhline(float(r['target']),color='#657a91',ls='-.',label='Theoretical target (NO automatic sale)')
            levels=[]
            for b in view:
                known=[e for e in raises if e['date']<b.date]
                levels.append(float(known[-1]['new'])/factor if known and r['entry']<=b.date<=r['exit'] else float('nan'))
            ax.step(range(len(view)),levels,where='post',color='#8251af',lw=1.6,label='Active dynamic protection')
            ax.scatter(entry-lo,float(r['buy']),marker='^',s=55,color='#2455a8',zorder=7,label='Buy '+r['entry'])
            if exit<hi:
                ax.scatter(exit-lo,float(r['exit_price_entry_basis']),marker='v',s=55,color='#171b24',zorder=7,label='Sell '+r['exit'])
                ax.axvspan(exit-lo+.5,len(view)-.5,color='#dce2e9',alpha=.4,label='After exit')
            ax.legend(fontsize=7,ncols=2,loc='best')
            ax.set_ylabel('Entry-date factor price basis')
            ax.set_title('Holding path and price lines' if j==0 else 'Entry / early holding detail',fontsize=10)
        fig.suptitle(f"{r['symbol']} | buy {float(r['buy']):.3f} | initial stop {float(r['initial_stop']):.3f} | target {float(r['target']):.3f}\nStop distance {float(r['stop_pct']):.2%} / {float(r['stop_atr']):.2f} ATR | net P/L {float(r['pnl']):+,.2f} CNY",fontsize=11)
        name=r['symbol']+'.png';fig.savefig(dest/name,dpi=115);plt.close(fig)
        index.append(dict(symbol=r['symbol'],chart='charts/'+name))
    dump(dest/'index.json',index);print('Rendered three price-line charts')

if __name__=='__main__':main()
