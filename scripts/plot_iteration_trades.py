"""Known-at-plan structure charts and explicitly retrospective holding charts."""
import csv,json,sys,html
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.analysis import adjusted,weekly


def main(run):
    out=Path(run);trades=json.loads((out/'trade-timeline.json').read_text(encoding='utf-8'))
    history={t['symbol']:[] for t in trades}
    with (out/'bars.csv').open(encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in history:
                history[r['symbol']].append(Bar(r['symbol'],r['date'],*[float(r[k]) for k in
                    ('open','high','low','close','volume','factor','up_limit','down_limit')]))
    with (out/'decisions.csv').open(encoding='utf-8-sig') as f:
        promotions=[e for e in csv.DictReader(f) if e['event']=='core_protection_promoted']
    calendar=json.loads((out/'calendar.json').read_text(encoding='utf-8'))
    params=json.loads((out/'config.json').read_text(encoding='utf-8'))['strategies'][0]['params']
    diagnostic=json.loads((out/'profit-diagnostics.json').read_text(encoding='utf-8'))
    peak={t['symbol']:t for t in diagnostic['trades']}
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','DejaVu Sans']
    def candles(ax,bars):
        for i,b in enumerate(bars):
            color='#c75454' if b.close>=b.open else '#45927c'
            ax.vlines(i,b.low,b.high,color=color,lw=.8)
            ax.add_patch(Rectangle((i-.3,min(b.open,b.close)),.6,max(.004,abs(b.close-b.open)),color=color))
        ticks=list(range(0,len(bars),max(1,len(bars)//8)))
        ax.set_xticks(ticks,[bars[i].date for i in ticks]);ax.set_xlim(-1,len(bars));ax.grid(alpha=.2)
        return {b.date:i for i,b in enumerate(bars)}
    def poly(ax,bars,indices,dates,kinds,color,label):
        if not all(d in indices for d in dates):return
        vals=[getattr(bars[indices[d]],kind) for d,kind in zip(dates,kinds)]
        ax.plot([indices[d] for d in dates],vals,color=color,lw=2,label=label)
    page=['<!doctype html><meta charset="utf-8"><title>交易结构与保护位</title><style>body{font:16px system-ui;max-width:1600px;margin:30px auto}img{width:100%;height:auto}pre{white-space:pre-wrap}</style>',
          '<h1>交易结构与保护位</h1><p>第一张图截止首次计划当日，不含后来行情；第二张图为完整交易回顾，包含买入后的价格，不能用作当时的信号证据。所有价格按各自图的最后已知因子归一。</p>']
    for t in trades:
        raw=history[t['symbol']];plan=t['first_planned_at']
        known=adjusted([b for b in raw if b.date<=plan]);days=known[-250:]
        weeks=weekly(known,set(calendar['week_ends']))[-110:]
        fig,(upper,core)=plt.subplots(2,1,figsize=(15,9))
        fig.suptitle(t['symbol']+' · 截至首次计划 '+plan+' · 周线方向／日线结构')
        wi=candles(upper,weeks);di=candles(core,days)
        first,second=t['direction_first'],t['direction_second']
        if first in wi and second in wi:
            middle=max(range(wi[first]+1,wi[second]),key=lambda i:weeks[i].high)
            poly(upper,weeks,wi,[first,weeks[middle].date,second],['low','high','low'],'#c12638','周线双底')
            upper.axhline(weeks[middle].high,color='#c12638',ls='--',label='颈线')
        for date,label,color in ((t['direction_breakout'],'首次收盘突破','#7043a0'),
                                 (t['direction_retest_started'],'反抽起点','#b97b13'),
                                 (t['direction_confirmed'],'方向确认','#1b7985')):
            if date in wi:upper.axvline(wi[date],color=color,ls=':',label=label+' '+date)
        poly(core,days,di,[t[k] for k in ('core_a','core_b','core_c')],['low','high','low'],'#252dc2','日线核心 A/B/C')
        poly(core,days,di,[t[k][:8] for k in ('small_a','small_b','small_c')],['low','high','low'],'#d98816','日线小结构代理 A/B/C')
        core.axhline(float(t['trigger']),color='#7043a0',ls='--',label='计划触发价')
        core.axhline(float(t['stop']),color='#be3030',ls=':',label='初始节奏止损')
        core.set_title('核心C '+t['core_c']+'；小结构确认 '+t['small_confirmed']+'；目标 '+f"{float(t['target']):.3f}")
        for axis in (upper,core):axis.legend(loc='upper left',fontsize=8)
        stem=t['symbol'].replace('.','-');signal=stem+'-signal.png'
        fig.tight_layout();fig.savefig(out/signal,dpi=120);plt.close(fig)
        complete=adjusted([b for b in raw if b.date<=t['exit_date']])
        hold=[b for b in complete if b.date>=t['core_c']]
        fig,ax=plt.subplots(figsize=(15,5));hi=candles(ax,hold)
        measured_from=t['core_c'] if params.get('holding_scale_mode')=='owned_core' else t['small_c'][:8]
        if measured_from in hi:
            ax.axvline(hi[measured_from],color='#718096',ls=':',label='持仓计量起点 '+measured_from)
        anchor=complete[-1].factor;factors={b.date:b.factor for b in raw}
        steps=[(hi[t['entry_date']],float(t['stop'])*factors[plan]/anchor)]
        for e in promotions:
            if e['setup_id']==t['setup_id'] and e['date'] in hi:
                steps.append((hi[e['date']],float(e['new_stop'])*factors[e['date']]/anchor))
        steps.append((len(hold)-1,steps[-1][1]));ax.step([x for x,y in steps],[y for x,y in steps],where='post',color='#be3030',lw=2,label='有效保护位')
        for date,price,label,color in ((t['entry_date'],float(t['entry']),'买入','#7043a0'),(t['exit_date'],float(t['exit']),'卖出','#222222')):
            ax.scatter(hi[date],price,color=color,s=45);ax.annotate(label+' '+date,(hi[date],price),xytext=(3,12),textcoords='offset points',color=color)
        q=peak.get(t['symbol']);extra='' if not q else '；峰值收盘毛浮盈 '+f"{q['peak_close_gross_r']:.2f}R"
        ax.set_title(t['symbol']+' · 交易回顾（含后来行情） · 核心C '+t['core_c']+extra+'；净实现 '+f"{float(t['realized_r']):.2f}R")
        ax.legend(loc='upper left',fontsize=9);fig.tight_layout();holding=stem+'-holding.png'
        fig.savefig(out/holding,dpi=120);plt.close(fig)
        page+=['<h2>'+html.escape(t['symbol'])+'</h2><img src="'+signal+'" alt="首次计划时已知结构"><img src="'+holding+'" alt="交易回顾与保护位">']
    (out/'trade-structure.html').write_text('\n'.join(page),encoding='utf-8')
    print('Generated structure and holding charts for',len(trades),'closed trades')


if __name__=='__main__':main(sys.argv[1])
