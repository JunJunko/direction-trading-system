"""Render frozen examples of layouts suppressed by the old search lifecycle."""
import csv,html,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.analysis import adjusted,weekly
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

snapshot=Path(sys.argv[1]);out=Path(sys.argv[2]);read=lambda p:json.loads(p.read_text(encoding='utf-8'))
audit=read(out/'audit.json');cal=read(snapshot/'calendar.json')
cases=[dict(case,category=category) for category,examples in audit['examples'].items() for case in examples[:2]]
histories={c['symbol']:[] for c in cases}
with (snapshot/'bars.csv').open(encoding='utf-8-sig') as f:
    for r in csv.DictReader(f):
        if r['symbol'] in histories:
            histories[r['symbol']].append(Bar(r['symbol'],r['date'],
                *[float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')]))
page=['<!doctype html><meta charset="utf-8"><title>双底布局搜索审计</title>',
    '<style>body{font:16px system-ui;max-width:1500px;margin:30px auto}img{width:100%}pre{white-space:pre-wrap}section{border-top:1px solid #ddd;padding:20px}</style>',
    '<h1>双底布局搜索审计</h1><p>核对同一冻结主板行情的全部股票。统计是满足当前数学条件的算法布局，不是人工确认的有效双底或可成交机会；同一股票和同一级别的组合可能重复，分类之间也会重叠，不能相加。</p>',
    '<pre>'+html.escape(json.dumps(audit['counts'],ensure_ascii=False,indent=2))+'</pre>',
    '<p>修复方案：所有合格底点组合独立跟踪；首次突破早于右底确认时，在首次可识别日登记，保留真实突破日期；回踩、失效、期限独立判断。原有方向有效期间保持其结构归属，另一个布局不会替换已有交易依据。原始单候选模式与默认实盘配置保留。</p>',
    '<p>价格相近不代表结构级别相同。当前算法的结构级别、前趋势起点选择和日线核心结构替代仍未完整解决；本轮恢复搜索覆盖率，不宣称这些布局就是书中标准答案。</p>']
for n,case in enumerate(cases,1):
    bars=adjusted([b for b in histories[case['symbol']] if b.date<=case['observed_at']])
    w=weekly(bars,set(cal['week_ends']));ix={b.date:i for i,b in enumerate(w)}
    start=max(0,min(ix[c['first']] for c in case['candidates'])-6)
    fig,ax=plt.subplots(figsize=(15,5))
    for i in range(start,len(w)):
        b=w[i];color='#b94141' if b.close>=b.open else '#21846b'
        ax.vlines(i,b.low,b.high,color=color,lw=.7)
        ax.add_patch(Rectangle((i-.3,min(b.open,b.close)),.6,max(abs(b.open-b.close),.002),color=color))
    for j,c in enumerate(case['candidates']):
        a,d,b=ix[c['first']],ix[c['second']],ix[c['breakout']]
        neck=max(range(a+1,d),key=lambda i:w[i].high);color=['blue','orange','purple','green'][j%4]
        ax.plot([a,neck,d,b],[w[a].low,w[neck].high,w[d].low,w[b].close],color=color,lw=1.4,
            label=f"Layout {j+1}: {c['first']} / {c['second']}")
        ax.hlines(w[neck].high,a,len(w)-1,color=color,linestyle=':',alpha=.6)
        if c['bottom_confirmed']>c['breakout']:
            ax.axvline(ix[c['bottom_confirmed']],color=color,linestyle='--',
                       label='First observable '+c['bottom_confirmed'])
    ticks=list(range(start,len(w),max(1,(len(w)-start)//12)))
    ax.set_xticks(ticks,[w[i].date for i in ticks],rotation=35);ax.grid(alpha=.2)
    ax.set_title(case['symbol']+' | '+case['observed_at']+' | '+case['category']);ax.legend(fontsize=8)
    fig.tight_layout();name=f'example-{n}.png';fig.savefig(out/name,dpi=110);plt.close(fig)
    page.append('<section><h2>'+html.escape(case['symbol']+' / '+case['category'])+'</h2><img src="'+name+'"><pre>'+html.escape(json.dumps(case,ensure_ascii=False,indent=2))+'</pre></section>')
(out/'report.html').write_text('\n'.join(page),encoding='utf-8')
print('Rendered six causal search examples')
