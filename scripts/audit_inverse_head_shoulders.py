"""Diagram conformance audit; diagnostic cutoffs are not new trading rules."""
import csv
import hashlib
import html
import json
import shutil
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from trading_system.domain import Bar
from trading_system.analysis import adjusted
from trading_system.strategies.inverse_head_shoulders import InverseHeadShoulders
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def synthetic(knots):
    values = [a+(b-a)*j/3 for a,b in zip(knots, knots[1:]) for j in range(3)] + knots[-1:]
    return [Bar('SYNTHETIC', (date(2025,1,1)+timedelta(days=i)).strftime('%Y%m%d'),
                v, v+.1, v-.1, v, 100) for i,v in enumerate(values)]


def main():
    snapshot = ROOT / 'runs/20261024-mainboard-inverse-head-shoulders-v1-cached'
    out = ROOT / 'audits/20261025-inverse-head-shoulders-diagram'
    out.mkdir(exist_ok=True)
    cases = [
        ('clean', 'Clean major structure: detected', [16,18,10,13,8,13,10,14], (2,4,6), 1),
        ('nested', 'Same major structure + inner swings: MISSED',
         [16,18,10,13,11.5,12,8,9.6,9.1,11.1,10.5,13,10,14], (2,6,12), 0),
        ('shallow', 'Head only 0.01 below shoulders: accepted', [16,18,10,13,9.99,13,10,14], (2,4,6), 1),
        ('uneven', 'Uneven shoulders at high price level: accepted', [101,102,100,100.5,98,100.5,98.1,100.8], (2,4,6), 1),
        ('uptrend', 'Higher highs/lows before formation: accepted',
         [5,8,7,10,9,13,11,16,12,14,11.9,14,12,14.3], (8,10,12), 1),
    ]
    outcomes = []
    fig, axes = plt.subplots(3, 2, figsize=(15, 13))
    for ax, (name, title, knots, key_points, expected_current) in zip(axes.flat, cases):
        bars = synthetic(knots)
        strategy = InverseHeadShoulders('audit', {})
        signals = []
        for end in range(1, len(bars)+1):
            signals.extend(strategy.on_close(bars[:end], set())[0])
        assert len(signals) == expected_current, name
        result = dict(case=name, knots=knots, observed_signals=len(signals),
                      declared_major_trough_indices=[i*3 for i in key_points],
                      observed_layouts=[i.evidence for i in signals])
        outcomes.append(result)
        ax.plot([b.close for b in bars], color='#19799a', linewidth=2)
        for label, k in zip(('LS', 'HEAD', 'RS'), key_points):
            x = k*3
            ax.scatter(x, bars[x].low, s=55, facecolor='white', edgecolor='#dc6132', zorder=3)
            ax.annotate(label, (x, bars[x].low), xytext=(0,-20), textcoords='offset points', ha='center')
        ax.set_title(title, fontsize=11)
        ax.grid(alpha=.2)
        ax.margins(y=.2)
    axes.flat[-1].axis('off')
    axes.flat[-1].text(.02,.8,'Diagnostic constructions, not market returns.\n\n'
        'All fixtures use the unchanged default detector.\nEach prefix is processed chronologically.\n'
        'Nested swings preserve the three major trough prices.\n'
        'No performance-based selection or parameter tuning.', fontsize=12, va='top')
    fig.tight_layout()
    fig.savefig(out/'synthetic-cases.png', dpi=130)
    plt.close(fig)
    dump(out/'synthetic-cases.json', outcomes)

    plans = json.loads((snapshot/'plans.json').read_text(encoding='utf-8'))
    date_fields = ['ihs_left_date','ihs_peak1_date','ihs_head_date','ihs_peak2_date','ihs_right_date','date']
    needed = {(p['symbol'], p[k]) for p in plans for k in date_fields}
    lookup, counts = {}, defaultdict(int)
    with (snapshot/'bars.csv').open(encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            symbol = r['symbol']; index = counts[symbol]; counts[symbol] += 1
            if (symbol,r['date']) in needed:
                lookup[symbol,r['date']] = dict(index=index, **{k:float(r[k]) for k in ('low','high','close','factor')})
    metrics = []
    for p in plans:
        points = [lookup[p['symbol'],p[k]] for k in date_fields]
        lows = [q['low']*q['factor']/p['factor'] for q in points]
        highs = [q['high']*q['factor']/p['factor'] for q in points]
        left, head, right = lows[0], lows[2], lows[4]
        height = p['ihs_neckline'] - p['ihs_floor']
        assert abs(head-p['ihs_floor']) < 1e-9
        metrics.append(dict(setup_id=p['setup_id'], symbol=p['symbol'], date=p['date'],
            height=height, head_prominence=min(left-head,right-head)/height,
            shoulder_imbalance=abs(left-right)/height, neck_imbalance=abs(highs[1]-highs[3])/height,
            left_span=points[2]['index']-points[0]['index'], right_span=points[4]['index']-points[2]['index']))
    stats = dict(signals=len(plans),
        head_prominence_below_10pct=sum(m['head_prominence']<.1 for m in metrics),
        shoulder_imbalance_above_50pct=sum(m['shoulder_imbalance']>.5 for m in metrics),
        neckline_imbalance_above_25pct=sum(m['neck_imbalance']>.25 for m in metrics),
        diagnostic_note='Illustrative normalized diagnostics, overlapping categories; not validated rejection rules or a false-positive rate.')
    dump(out/'metrics-summary.json',stats)
    with (out/'candidate-metrics.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(metrics[0]));writer.writeheader();writer.writerows(metrics)
    examples = [('least_head_prominence', min(metrics,key=lambda m:(m['head_prominence'],m['setup_id']))),
                ('largest_shoulder_imbalance', max(metrics,key=lambda m:(m['shoulder_imbalance'],m['setup_id']))),
                ('largest_neckline_imbalance', max(metrics,key=lambda m:(m['neck_imbalance'],m['setup_id'])))]
    chosen = {m['symbol'] for _,m in examples}
    histories = defaultdict(list)
    with (snapshot/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in chosen:
                histories[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in
                    ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    plan_map={p['setup_id']:p for p in plans}
    for label,m in examples:
        p=plan_map[m['setup_id']]
        bars=adjusted(sorted([b for b in histories[p['symbol']] if b.date<=p['date']],key=lambda b:b.date))
        dates={b.date:i for i,b in enumerate(bars)}
        start=max(0,dates[p['ihs_left_date']]-12)
        fig,ax=plt.subplots(figsize=(12,4.5))
        ax.plot(range(start,len(bars)),[b.close for b in bars[start:]],color='#748a9b',lw=1)
        for i in range(start,len(bars)):
            ax.vlines(i,bars[i].low,bars[i].high,color='#748a9b',lw=.8)
        xs=[dates[p[k]] for k in date_fields]
        ys=[bars[x].low if i in (0,2,4) else bars[x].high if i in (1,3) else bars[x].close for i,x in enumerate(xs)]
        ax.plot(xs,ys,'o-',color='#da6a23',label='Algorithm-selected pivots',lw=1.5)
        for i,name in ((0,'LS'),(2,'HEAD'),(4,'RS')):
            ax.annotate(name,(xs[i],ys[i]),xytext=(0,-18),textcoords='offset points',ha='center')
        ax.axhline(p['ihs_neckline'],color='#bf831b',ls='--',label='Neckline')
        ax.axhline(p['ihs_floor'],color='#c64949',ls=':',label='Head floor')
        ticks=list(range(start,len(bars),max(1,(len(bars)-start)//9)))
        ax.set_xticks(ticks,[bars[i].date for i in ticks],rotation=30)
        ax.set_title(f"{label} | {p['symbol']} | signal {p['date']} (no future bars)")
        ax.grid(alpha=.2);ax.legend(fontsize=8);ax.margins(y=.15)
        fig.tight_layout();fig.savefig(out/(label+'.png'),dpi=125);plt.close(fig)
    dump(out/'real-examples.json',[dict(category=k,**m) for k,m in examples])
    code=ROOT/'src/trading_system/strategies/inverse_head_shoulders.py'
    assert code.read_bytes() == (snapshot/'source/src/trading_system/strategies/inverse_head_shoulders.py').read_bytes()
    dump(out/'manifest.json',dict(source_snapshot=str(snapshot),strategy_sha256=hashlib.sha256(code.read_bytes()).hexdigest(),
        code_changed=False,synthetic_cases=len(outcomes),real_signals=len(plans),
        sample_selection='three geometric extrema, not random or representative; no subsequent outcomes used'))
    shutil.copy2(__file__,out/Path(__file__).name)
    shutil.copy2(ROOT/'docs/inverse-head-shoulders-diagram-audit.md', out/'review.md')
    page=['<!doctype html><meta charset="utf-8"><title>头肩底截图算法审查</title>',
          '<style>body{max-width:1200px;margin:32px auto;padding:0 20px;font:16px/1.7 system-ui}img{width:100%}pre{white-space:pre-wrap;background:#f3f5f8;padding:16px}h2{margin-top:36px}</style>',
          '<h1>头肩底：截图与算法审查</h1>',
          '<p>结论：识别存在漏检和形态质量约束不足；当前零成交同时存在独立的盈亏比规则冲突。此次只审查，不修改交易规则。</p>',
          '<p><a href="review.md">完整逐项审查结论</a></p>',
          '<h2>可复现的构造证据</h2><p>蓝线为输入，LS / HEAD / RS 为构造时明确指定的大结构低点。内部小波动会让现有连续五拐点搜索漏检；头部极浅、两肩明显不齐和上升背景仍可通过。</p><img src="synthetic-cases.png">',
          '<h2>全部 2,133 个真实候选的几何诊断</h2><p>以下比例均以“颈线－头部低点”为尺度。10%、50%、25% 仅用于暴露偏差，不是截图给出的阈值，也不是新增交易规则；各类可重叠，不能当作误识别率。</p><pre>'+html.escape(json.dumps(stats,ensure_ascii=False,indent=2))+'</pre>']
    for label,m in examples:
        page.append('<h2>'+html.escape(label+' / '+m['symbol'])+'</h2><p>按该几何指标选取的极端案例，非随机样本。橙色连线是算法标记的形态；灰色为截至信号日的真实价格。</p><img src="'+label+'.png"><pre>'+html.escape(json.dumps(m,ensure_ascii=False,indent=2))+'</pre>')
    page.append('<p>完整诊断：<a href="candidate-metrics.csv">candidate-metrics.csv</a>。详细结论见项目文档 docs/inverse-head-shoulders-diagram-audit.md。</p>')
    (out/'report.html').write_text('\n'.join(page),encoding='utf-8')
    print(json.dumps(stats,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
