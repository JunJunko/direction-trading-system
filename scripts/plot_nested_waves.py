"""Static visual QA of as-of accepted cores and their recorded end dates."""
import csv,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.analysis import adjusted


def main(validation,snapshot):
    out=Path(validation);cases=json.loads((out/'cases.json').read_text(encoding='utf-8'))
    selected=[c for c in cases if c['id'] in ('F01','F02','R14','R24')]
    histories={c['symbol']:[] for c in selected}
    with (Path(snapshot)/'bars.csv').open(encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in histories:
                histories[r['symbol']].append(Bar(r['symbol'],r['date'],
                    *[float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')]))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','DejaVu Sans']
    for c in selected:
        all_bars=adjusted([b for b in histories[c['symbol']] if b.date<=c['as_of']])
        bars=all_bars[-220:];indices={b.date:i for i,b in enumerate(bars)}
        prices={b.date:b for b in all_bars};focus=c['focus']
        fig,(ax,life)=plt.subplots(2,1,figsize=(15,9),gridspec_kw={'height_ratios':[3,1]})
        fig.suptitle(c['id']+' '+c['symbol']+' '+c['as_of']+' · '+focus['reason'])
        for i,b in enumerate(bars):
            color='#c75454' if b.close>=b.open else '#45927c'
            ax.vlines(i,b.low,b.high,color=color,lw=.8)
            ax.add_patch(Rectangle((i-.3,min(b.open,b.close)),.6,max(.005,abs(b.close-b.open)),color=color))
        roots=[r for r in focus['ledger'].values() if r['relation']!='internal'
               and r.get('ended_at',c['as_of'])>=bars[0].date][-4:]
        for row,r in enumerate(roots):
            active=r['state']=='active';color='#252dc2' if active else '#8b8b8b'
            if all(r[k] in indices for k in ('a','b','c')):
                points=[indices[r[k]] for k in ('a','b','c')]
                vals=[getattr(prices[r[k]],'high' if k=='b' else 'low') for k in ('a','b','c')]
                ax.plot(points,vals,'-' if active else '--',color=color,lw=2,label=r['accepted_at']+' '+r['state'])
                for k,i,v in zip(('A','B','C'),points,vals):ax.annotate(k,(i,v),color=color)
            start=next((i for i,b in enumerate(bars) if b.date>=r['accepted_at']),len(bars)-1)
            end=max((i for i,b in enumerate(bars) if b.date<=r.get('ended_at',c['as_of'])),default=0)
            life.plot([start,end],[row,row],color=color,lw=6)
            life.text(start,row+.15,r['state']+' '+r.get('end_reason',''),fontsize=9)
        for event in c['events']:
            if event['event']=='wave_order_unknown' and event['structure_known_at']<=c['as_of']:
                date=event['region_date']
                if date in indices:ax.axvspan(indices[date]-.6,indices[date]+.6,color='#f5be41',alpha=.4)
        if focus['core']:
            ax.axhline(focus['core']['correction_low'],color='#252dc2',ls=':',label='核心失效低点')
        ticks=list(range(0,len(bars),max(1,len(bars)//8)))
        for axis in (ax,life):
            axis.set_xticks(ticks,[bars[i].date for i in ticks]);axis.grid(alpha=.2)
            axis.set_xlim(-1,len(bars))
        ax.legend(loc='upper left',fontsize=8);life.set_yticks([]);life.set_ylim(-.5,max(.5,len(roots)-.3));life.set_title('已接受核心的生命周期；灰色记录已结束，不能复用')
        fig.tight_layout();fig.savefig(out/(c['id']+'-nested.png'),dpi=120);plt.close(fig)
    report=out/'report.html'
    if report.exists():
        marker='<section id="static-wave-examples">'
        content=report.read_text(encoding='utf-8').split(marker)[0]
        content+=marker+'<h2>重点时点图形</h2><p>上方为截至标注日期的日线；下方记录接受与结束时间。蓝色为当时可评估的核心，灰色为已结束的历史核心。这些图未应用周线交易准入，不能当作买入信号。</p>'
        for case_id in ('F02','R14'):
            content+='<img style="width:100%;height:auto" src="'+case_id+'-nested.png" alt="'+case_id+' 波段及生命周期">'
        report.write_text(content+'</section>',encoding='utf-8')
    print('Generated 4 as-of figures')


if __name__=='__main__':main(*sys.argv[1:])
