"""Causal pivot scale differences and full/zoomed trade protection charts."""
from dataclasses import replace
from backtest_ihs_profit_protection import OUT,rows,dump,CASES
from audit_pattern_trade_paths import history
from audit_ihs_profit_protection import key
from audit_candidate_policy import candles,plt
COLORS={'baseline':'#444444','small':'#a52b95','larger':'#216bc2','half':'#bb7400'}

def main():
    hist=history({'603989.SH','001326.SZ','002928.SZ'});paths=rows(OUT/'trade-paths.csv')
    events={case:rows(OUT/f'{case}_cost1/decisions.csv') for case in CASES};diagnostics=[]
    for e in events['small']:
        if e.get('source')!='profit_activated_daily_higher_low':continue
        h=hist[e['symbol']];idx={b.date:i for i,b in enumerate(h)};i=idx[e['formed']];low=h[i].low*h[i].factor
        neighbours=h[i-5:i]+h[i+1:i+6]
        diagnostics.append(dict(symbol=e['symbol'],pivot=e['formed'],old_confirmed=e['confirmed'],larger_confirmed=h[i+5].date,pivot_economic_low=low,
            disqualifying_neighbours=[dict(date=b.date,economic_low=b.low*b.factor) for b in neighbours if b.low*b.factor<=low]))
    dump(OUT/'pivot-scale-diagnostic.json',diagnostics)
    for symbol,zoom_start,zoom_end in [('603989.SH','20260520','20260618'),('001326.SZ','20260204','20260325')]:
        own=[r for r in paths if r['symbol']==symbol and r['case'].endswith('cost1')];h=hist[symbol];idx={b.date:i for i,b in enumerate(h)};base=next(r for r in own if r['case']=='baseline_cost1');factor=h[idx[base['entry']]].factor
        fig,axes=plt.subplots(1,2,figsize=(15,5.7),layout='constrained')
        for axis,(start,end),title in zip(axes,[(h[max(0,idx[base['entry']]-3)].date,h[min(len(h)-1,idx[base['exit']]+4)].date),(zoom_start,zoom_end)],['Full holding path','Protection detail (same entry-factor prices)']):
            view=[b for b in h if start<=b.date<=end];local={b.date:i for i,b in enumerate(view)}
            candles(axis,[replace(b,**{k:getattr(b,k)*b.factor/factor for k in ('open','high','low','close')}) for b in view])
            axis.axhline(float(base['fill']),ls=':',color='#666',label='Entry fill')
            for r in own:
                case=r['case'].split('_')[0];color=COLORS[case];ev=[e for e in events[case] if key(e['setup_id'])==r['canonical_id']];raises=[e for e in ev if e['event']=='main_protection_raised']
                for i,e in enumerate(raises):
                    a=idx[e['date']]+1;z=idx[raises[i+1]['date']]+1 if i+1<len(raises) else idx[r['exit']]
                    a=max(a,idx[view[0].date]);z=min(z,idx[view[-1].date])
                    if a>z:continue
                    axis.plot([a-idx[view[0].date],z-idx[view[0].date]],[float(e['new'])/factor]*2,color=color,lw=1.4,ls='--' if case=='larger' else '-')
                if r['exit'] in local:axis.axvline(local[r['exit']],color=color,ls='--',label=f"{case} sell {r['exit']} P/L {float(r['pnl']):+,.0f}")
            axis.set_title(title,fontsize=10);axis.legend(fontsize=7)
        if symbol=='603989.SH':
            axis=axes[1];view=[b for b in h if zoom_start<=b.date<=zoom_end];local={b.date:i for i,b in enumerate(view)}
            for d,label in [('20260526','Lower low within left5'),('20260602','Valid left2 low, invalid left5')]:
                b=h[idx[d]];axis.annotate(label,(local[d],b.low*b.factor/factor),xytext=(0,-28),textcoords='offset points',fontsize=7,arrowprops=dict(arrowstyle='->',color='#555'))
        fig.suptitle(symbol+' | frozen baseline / small2 / larger5 / half-peak profit',fontsize=11);fig.savefig(OUT/f'charts/focus-{symbol}.png',dpi=125);plt.close(fig)
    print('DIAGNOSTICS 3 old pivots and 2 focus charts')

if __name__=='__main__':main()
