"""Nonblind examples: rejected losers, missed winners, capacity effects and retained winner."""
from dataclasses import replace
from backtest_quality_entry import OUT,rows,dump
from audit_pattern_trade_paths import history
from audit_candidate_policy import candles,plt

CASES=[('W','002201.SZ','20251031'),('W','001229.SZ','20251229'),('W','000422.SZ','20260114'),('IHS','002006.SZ','20251119'),('IHS','002518.SZ','20251010'),('IHS','603989.SH','20260508')]

def main():
    pairs=rows(OUT/'paired-trades.csv');hist=history({s for _,s,_ in CASES});dest=OUT/'charts';dest.mkdir(exist_ok=True);index=[]
    for family,symbol,entry in CASES:
        case=family+'_no_gap_up_cost1';p=next(r for r in pairs if r['case']==case and r['symbol']==symbol and r['old_entry']==entry)
        folder=OUT/(family+'_baseline_cost1');a=next(r for r in rows(folder/'entry_audit.csv') if r['setup_id']==p['setup_id'] and r['execution_reason']=='filled')
        t=next(r for r in rows(folder/'trades.csv') if r['setup_id']==p['setup_id']);h=hist[symbol];lookup={b.date:i for i,b in enumerate(h)};i=lookup[entry];end=lookup[t['exit_date']];factor=h[i].factor
        scale=lambda b:replace(b,**{k:getattr(b,k)*b.factor/factor for k in ('open','high','low','close')})
        fig,axes=plt.subplots(2,1,figsize=(12,7),layout='constrained')
        for ax,lo,hi,title in [(axes[0],max(0,i-10),min(len(h),i+9),'Opening decision (later candles for review only)'),(axes[1],max(0,i-4),min(len(h),end+11),'Baseline holding and missed/retained outcome')]:
            v=[scale(b) for b in h[lo:hi]];candles(ax,v)
            ax.axvline(i-lo,color='#2457ac',ls=':',label='Entry date '+entry)
            ax.scatter(i-lo,float(a['fill']),marker='^',s=55,color='#2457ac',label='Baseline actual buy')
            if lo<=end<hi:ax.scatter(end-lo,float(t['exit'])*h[end].factor/factor,marker='v',s=55,color='#222',label='Baseline sell '+t['exit_date'])
            ax.axhline(scale(h[i-1]).close,color='#bb862d',ls='--',label='Previous adjusted close')
            ax.axhline(float(a['stop']),color='#b64f7c',ls=':',label='Initial stop')
            ax.set_title(title);ax.legend(fontsize=8,ncols=2)
        fig.suptitle(f"{family} {symbol} | raw open gap {float(p['baseline_gate_value']):+.3%} | {p['category']}\nBaseline P/L {float(p['old_pnl']):+,.2f} | Candidate P/L {float(p['new_pnl']):+,.2f} CNY",fontsize=12)
        name=f'{family}-{symbol}.png';fig.savefig(dest/name,dpi=120);plt.close(fig)
        index.append(dict(family=family,symbol=symbol,entry=entry,chart='charts/'+name,**{k:p[k] for k in ('category','baseline_gate_value','old_pnl','new_pnl')}))
    dump(dest/'index.json',index);print('Rendered six gate review charts')

if __name__=='__main__':main()
