"""Chart every distinct filled setup across all ten accounts, including missed winners."""
from dataclasses import replace
from PIL import Image
from backtest_ihs_entry_quality import OUT,rows,dump
from audit_pattern_trade_paths import history
from audit_candidate_policy import candles,plt

def main():
    records=rows(OUT/'trade-paths.csv');groups={}
    for r in records:groups.setdefault(r['canonical_id'],[]).append(r)
    hist=history({r['symbol'] for r in records});dest=OUT/'charts';dest.mkdir(exist_ok=True);index=[]
    for number,(pid,items) in enumerate(sorted(groups.items(),key=lambda kv:(kv[1][0]['entry'],kv[0])),1):
        items.sort(key=lambda r:(not r['case'].endswith('cost1'),not r['case'].startswith('baseline')));r=items[0]
        h=hist[r['symbol']];lookup={b.date:i for i,b in enumerate(h)};entry=lookup[r['entry']];sig=lookup[r['signal']];factor=h[entry].factor
        def scaled(b):return replace(b,**{k:getattr(b,k)*b.factor/factor for k in ('open','high','low','close')})
        fig=plt.figure(figsize=(13,5.8),layout='constrained');grid=fig.add_gridspec(2,2,height_ratios=[3,1]);left=fig.add_subplot(grid[0,0]);vol=fig.add_subplot(grid[1,0],sharex=left);right=fig.add_subplot(grid[:,1])
        lo=max(0,sig-24);hi=min(len(h),entry+5);v=[scaled(b) for b in h[lo:hi]];candles(left,v)
        left.axvline(sig-lo,color='#b98122',ls='--',label='Signal close '+r['signal']);left.axvline(entry-lo,color='#2457ad',ls=':',label='Buy open '+r['entry'])
        left.axvspan(sig-lo+.5,len(v)-.5,color='#e5eaf0',alpha=.35,label='After signal (review only)')
        left.scatter(entry-lo,float(r['fill']),marker='^',s=35,color='#2457ad',zorder=5)
        left.set_title(f"Pre-entry | CLV {float(r['close_location']):.2f} | MA20 change {float(r['ma20_change']):+.2%} | gap {float(r['gap_atr']):+.2f} ATR",fontsize=9)
        left.legend(fontsize=7,loc='best')
        average=sum(b.volume for b in h[sig-20:sig])/20
        vol.bar(range(len(v)),[b.volume/average for b in h[lo:hi]],color=['#d28c37' if i+lo==sig else '#a1b5cf' for i in range(len(v))]);vol.axhline(1,color='#a85e19',ls='--')
        vol.set_ylabel('Vol / prior20 mean',fontsize=7);vol.set_title(f"Signal volume ratio {float(r['volume_ratio']):.3f}; average excludes signal",fontsize=8);vol.tick_params(axis='x',rotation=25,labelsize=7)
        end=max(lookup[x['exit'] or '20260930'] for x in items);lo2=max(0,entry-4);hi2=min(len(h),end+9);held=[scaled(b) for b in h[lo2:hi2]];candles(right,held)
        right.scatter(entry-lo2,float(r['fill']),marker='^',s=40,color='#2457ad',label='Representative buy')
        right.axhline(float(r['initial_stop']),color='#b74f7c',ls=':',label='Initial stop')
        exits={x['exit'] for x in items if x['exit']}
        # Full per-case prices and P/L remain in the table; arrows mark sell sessions.
        for d in sorted(exits):right.axvline(lookup[d]-lo2,color='#343947',ls='--',lw=1,label='Sell '+d)
        right.legend(fontsize=7,loc='best');right.set_title('Holding path and recorded exit sessions',fontsize=9)
        short={x['case']:round(float(x['pnl'])) for x in items}
        subtitle=' | '.join(f"{k.replace('_cost',' c')}: {v:+,}" for k,v in short.items() if k.startswith(('baseline','solid_close','volume_confirmed')))
        fig.suptitle(f"{number:02d} {r['symbol']} | entry {r['entry']} | {r['case']} price basis\n{subtitle}",fontsize=9)
        name=f'{number:02d}-{r["symbol"]}-{r["entry"]}.png';fig.savefig(dest/name,dpi=115);plt.close(fig)
        index.append(dict(number=number,canonical_id=pid,symbol=r['symbol'],entry=r['entry'],chart='charts/'+name,cases=short,close_location=float(r['close_location']),volume_ratio=float(r['volume_ratio']),ma20_change=float(r['ma20_change']),gap_atr=float(r['gap_atr'])))
    contacts=[]
    for i in range(0,len(index),2):
        images=[Image.open(OUT/r['chart']).convert('RGB') for r in index[i:i+2]]
        canvas=Image.new('RGB',(max(im.width for im in images),sum(im.height for im in images)),'white');offset=0
        for im in images:canvas.paste(im,(0,offset));offset+=im.height;im.close()
        name=f'contact-{i//2+1:02d}.png';canvas.save(dest/name);contacts.append(dict(chart='charts/'+name,numbers=[r['number'] for r in index[i:i+2]]))
    dump(dest/'index.json',index);dump(dest/'contacts.json',contacts);print('CHARTS',len(index),'CONTACTS',len(contacts))

if __name__=='__main__':main()
