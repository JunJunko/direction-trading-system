"""Zoom into all five baseline winners missed by the retest arm."""
from dataclasses import replace
from backtest_ihs_lifecycle import OUT,rows,load,dump
from audit_pattern_trade_paths import history
from audit_candidate_policy import candles,plt
from audit_ihs_lifecycle import key,economic_neck

def main():
    paths=rows(OUT/'trade-paths.csv');top=sorted([r for r in paths if r['case']=='baseline_cost1'],key=lambda r:float(r['pnl']),reverse=True)[:5]
    hist=history({r['symbol'] for r in top});events=rows(OUT/'retest_cost1/decisions.csv');audits=rows(OUT/'retest_cost1/entry_audit.csv');plans={key(p['setup_id']):p for p in load(OUT/'plans.json')};out=[]
    for num,r in enumerate(top,1):
        pid=r['canonical_id'];p=plans[pid];h=hist[r['symbol']];idx={b.date:i for i,b in enumerate(h)};i=idx[p['date']];factor=h[i].factor;lo=i-4;view=h[lo:i+15]
        ev=[e for e in events if key(e['setup_id'])==pid and e['event'] in ('retest_touch','entry_intent','retest_cancelled')];aa=[a for a in audits if key(a['setup_id'])==pid]
        fig,ax=plt.subplots(figsize=(11,4.6),layout='constrained');candles(ax,[replace(b,**{k:getattr(b,k)*b.factor/factor for k in ('open','high','low','close')}) for b in view])
        ax.plot(range(len(view)),[economic_neck(p,h,b.date)/factor for b in view],color='#bd891f',label='Frozen neckline')
        atr=float(p['ihs_entry_atr']);ax.plot(range(len(view)),[economic_neck(p,h,b.date)/factor+atr for b in view],color='#bd891f',ls=':',label='Maximum entry: neck + 1 original ATR')
        ax.axhline(float(p['ihs_right_low']),color='#cf5656',ls=':',label='Original right shoulder')
        ax.axvline(i-lo,color='#666',ls='--',label='Original signal '+p['date'])
        for e in ev:
            d=e['date'];ax.axvline(idx[d]-lo,color='#286cbb',ls=':',label=e['event']+' '+d)
        reason=';'.join(sorted({a['risk_reason'] or a['execution_reason'] for a in aa}|{e.get('reason','') for e in ev if e['event']=='retest_cancelled'}))
        for a in aa:
            ax.scatter(idx[a['date']]-lo,float(a['fill'])*h[idx[a['date']]].factor/factor,marker='x',s=65,color='#c22',label=a['execution_reason']+' '+a['date'])
        ax.set_title(r['symbol']+' | baseline profit '+f"{float(r['pnl']):,.2f}"+' | retest missed\n'+reason,fontsize=10);ax.legend(fontsize=7)
        name=f'charts/excluded-top{num}-{r["symbol"]}.png';fig.savefig(OUT/name,dpi=115);plt.close(fig);out.append(dict(symbol=r['symbol'],canonical_id=pid,reason=reason,chart=name))
    dump(OUT/'charts/exclusions.json',out);print('EXCLUSIONS',len(out))

if __name__=='__main__':main()
