"""Show every traded shape, all actual entry dates and all changed exits/supports."""
from dataclasses import replace
from PIL import Image
from backtest_ihs_profit_protection import OUT,rows,load,dump,CASES
from audit_pattern_trade_paths import history
from audit_candidate_policy import candles,plt
from audit_ihs_profit_protection import key,economic_neck

COLORS={'baseline':'#444444','small':'#a52b95','larger':'#216bc2','half':'#bb7400'}

def main():
    records=rows(OUT/'trade-paths.csv');groups={}
    for r in records:groups.setdefault(r['canonical_id'],[]).append(r)
    plans={key(p['setup_id']):p for p in load(OUT/'plans.json')}
    events={f'{case}_cost{cost}':rows(OUT/f'{case}_cost{cost}'/'decisions.csv') for case in CASES for cost in (1,2)}
    hist=history({r['symbol'] for r in records});dest=OUT/'charts';dest.mkdir(exist_ok=True);index=[]
    for number,(pid,items) in enumerate(sorted(groups.items(),key=lambda kv:(min(x['entry'] for x in kv[1]),kv[0])),1):
        items.sort(key=lambda r:(not r['case'].endswith('cost1'),not r['case'].startswith('baseline')));r=items[0];p=plans[pid]
        h=hist[r['symbol']];lookup={b.date:i for i,b in enumerate(h)};entry=min(lookup[x['entry']] for x in items);end=max(lookup[x['exit'] or '20260930'] for x in items);factor=h[entry].factor
        def scaled(b):return replace(b,**{k:getattr(b,k)*b.factor/factor for k in ('open','high','low','close')})
        fig,(left,right)=plt.subplots(1,2,figsize=(15,6.4),layout='constrained')
        lo=max(0,lookup[p['ihs_left_date']]-7);hi=min(len(h),max(lookup[x['entry']] for x in items)+5);v=[scaled(b) for b in h[lo:hi]];candles(left,v)
        dates=[p[k] for k in ('ihs_left_date','ihs_peak1_date','ihs_head_date','ihs_peak2_date','ihs_right_date')]
        prices=[(h[lookup[d]].low if i%2==0 else h[lookup[d]].high)*h[lookup[d]].factor/factor for i,d in enumerate(dates)]
        left.plot([lookup[d]-lo for d in dates],prices,'--',color='#226792',lw=1)
        for d,y,label in zip(dates,prices,('L','P1','H','P2','R')):left.annotate(label,(lookup[d]-lo,y),fontsize=8)
        left.plot(range(len(v)),[economic_neck(p,h,b.date)/factor for b in h[lo:hi]],color='#c39126',lw=1,label='Frozen neckline')
        left.axvline(lookup[p['date']]-lo,color='#c39126',ls=':',label='Original signal '+p['date'])
        lo2=max(0,entry-4);hi2=min(len(h),end+9);held=[scaled(b) for b in h[lo2:hi2]];candles(right,held)
        right.plot(range(len(held)),[economic_neck(p,h,b.date)/factor for b in h[lo2:hi2]],color='#c39126',alpha=.55,label='Frozen neckline')
        stop=float(p['stop'])*h[lookup[p['date']]].factor/factor;right.axhline(stop,color='#d35454',ls=':',label='Initial hard stop')
        seen=set();support_seen=set();event_seen=set()
        for x in items:
            case=x['case'];rule=case.split('_')[0];color=COLORS[rule];label=rule+(' c2' if case.endswith('2') else '')
            y=float(x['fill'])*h[lookup[x['entry']]].factor/factor;signature=(rule,x['entry'])
            if signature not in seen:
                left.scatter(lookup[x['entry']]-lo,y,marker='^',s=48,color=color,label=label+' buy '+x['entry'],zorder=6)
                right.scatter(lookup[x['entry']]-lo2,y,marker='^',s=48,color=color,zorder=6);seen.add(signature)
            ev=[e for e in events[case] if key(e['setup_id'])==pid]
            levels=[e for e in ev if e['event']=='main_protection_raised'];last=stop
            for i,e in enumerate(levels):
                start=lookup[e['date']]+1;finish=lookup[levels[i+1]['date']]+1 if i+1<len(levels) else lookup[x['exit'] or '20260930']
                level=float(e['new'])/factor;signature=(rule,start,finish,round(level,8))
                if signature not in support_seen:
                    right.plot([start-lo2,finish-lo2],[level,level],color=color,lw=1.1,ls='--' if case.endswith('2') else '-',alpha=.75);support_seen.add(signature)
            for e in ev:
                if e['event'] not in ('retest_touch','entry_intent','ihs_breakout_failure_confirmed','profit_protection_activated'):continue
                if e['event']=='entry_intent' and not e.get('retest_confirmed_at'):continue
                d=e['date'];sig=(rule,e['event'],d)
                if sig in event_seen:continue
                event_seen.add(sig);ax=left if rule=='retest' else right;offset=lo if rule=='retest' else lo2
                if not 0<=lookup[d]-offset<(len(v) if ax==left else len(held)):continue
                tag={'retest_touch':'Touch','entry_intent':'Confirm','ihs_breakout_failure_confirmed':'Fail x2','profit_protection_activated':'1R active'}[e['event']]
                ax.axvline(lookup[d]-offset,color=color,ls=':',lw=.8);ax.annotate(tag,(lookup[d]-offset,h[lookup[d]].high*h[lookup[d]].factor/factor),fontsize=7,color=color,rotation=60)
            if x['exit']:
                d=x['exit'];signature=(rule,d)
                if signature not in seen:
                    right.axvline(lookup[d]-lo2,color=color,ls='--',lw=1,label=label+' sell '+d);seen.add(signature)
        left.set_title('Frozen shape / signal / actual entries',fontsize=10);right.set_title('Holding candles / active supports / actual exits',fontsize=10)
        left.legend(fontsize=7,loc='best');right.legend(fontsize=7,loc='best')
        subtitle=' | '.join(f"{x['case'].replace('_cost',' c')} {float(x['pnl']):+,.0f}" for x in items)
        fig.suptitle(f"{number:02d} {r['symbol']} | original signal {p['date']} | prices in {h[entry].date} factor basis\n{subtitle}",fontsize=9)
        name=f'{number:02d}-{r["symbol"]}-{p["date"]}.png';fig.savefig(dest/name,dpi=110);plt.close(fig)
        index.append(dict(number=number,canonical_id=pid,symbol=r['symbol'],original_signal=p['date'],chart='charts/'+name,entries=sorted({x['entry'] for x in items}),cases={x['case']:float(x['pnl']) for x in items}))
    contacts=[]
    for i in range(0,len(index),2):
        ims=[Image.open(OUT/r['chart']).convert('RGB') for r in index[i:i+2]];canvas=Image.new('RGB',(max(im.width for im in ims),sum(im.height for im in ims)),'white');y=0
        for im in ims:canvas.paste(im,(0,y));y+=im.height;im.close()
        name=f'contact-{i//2+1:02d}.png';canvas.save(dest/name);contacts.append(dict(chart='charts/'+name,numbers=[r['number'] for r in index[i:i+2]]))
    dump(dest/'index.json',index);dump(dest/'contacts.json',contacts);print('CHARTS',len(index),'CONTACTS',len(contacts))

if __name__=='__main__':main()
