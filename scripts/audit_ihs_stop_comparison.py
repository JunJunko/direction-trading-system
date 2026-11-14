"""Independently check paired replay artifacts and render deterministic trade examples."""
import csv
import html
import json
import math
import statistics
from datetime import datetime
from pathlib import Path
from backtest_ihs_stop_comparison import BASE, ROOT, load, dump, sha, MainboardUniverse

def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def main():
    out = ROOT/'runs/20261025-ihs-head-vs-right-shoulder'
    plans = {p['setup_id']:p for p in load(out/'paired-plans.json')}
    curve = rows(out/'right_shoulder/equity.csv')
    assert rows(out/'head/equity.csv') == rows(BASE/'equity.csv')
    trades = rows(out/'right_shoulder/trades.csv')
    audits = rows(out/'right_shoulder/entry_audit.csv')
    filled = [a for a in audits if a['execution_reason']=='filled']
    assert len(filled) == 27 and len(trades)==23 and len(curve)==241
    assert all(float(a['net_rr'])>3 for a in filled)
    assert all(a['signal_date']<a['date'] for a in filled)
    for a in filled:
        assert float(a['stop']) < float(a['fill']) < float(a['target'])
    peak = 1e6
    worst = 0
    for r in curve:
        value = float(r['equity']); peak=max(peak,value)
        worst=min(worst,value/peak-1)
        assert math.isclose(float(r['drawdown']),value/peak-1,abs_tol=1e-12)
    summary = load(out/'right_shoulder/summary.json')
    assert math.isclose(worst,summary['max_drawdown'],abs_tol=1e-12)
    assert float(curve[-1]['equity']) == summary['final_equity']
    ud=load(BASE/'universe.json'); universe=MainboardUniverse(ud['stocks'],ud['st_by_date'])
    screened=rows(out/'isolated-screen.csv')
    eligible=sum(int(r['quantity'])>0 and universe.eligible(r['symbol'],r['date'])
                 for r in screened if r['rule']=='right_shoulder')
    spans=[]
    for a in filled:
        p=plans[a['setup_id']]
        spans.append((datetime.strptime(p['ihs_right_date'],'%Y%m%d')-
                      datetime.strptime(p['ihs_left_date'],'%Y%m%d')).days)
    # First chronological stop and first chronological target, not best/worst chosen after returns.
    examples=[next(t for t in trades if 'break' in t['reason']),
              next(t for t in trades if t['reason']=='ihs_target_close_confirmed')]
    symbols={t['symbol'] for t in examples}
    data={s:[] for s in symbols}
    with (BASE/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in symbols:data[r['symbol']].append(r)
    fragments=[]
    for index,t in enumerate(examples):
        p=plans[t['setup_id']]
        selected=sorted([r for r in data[t['symbol']] if p['ihs_origin_date']<=r['date']<=t['exit_date']],key=lambda r:r['date'])
        values=[float(r['close'])*float(r['factor'])/p['factor'] for r in selected]
        lo=min(values+[p['stop']]); hi=max(values+[p['target']]); pad=(hi-lo)*.08
        lo-=pad; hi+=pad
        x=lambda i: 70+850*i/max(1,len(selected)-1)
        y=lambda price: 330-270*(price-lo)/(hi-lo)
        dates={r['date']:i for i,r in enumerate(selected)}
        svg=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 410" role="img">',
             '<rect width="1000" height="410" fill="#f5f8fc"/>']
        for key,label,color in [('stop','头部止损','#c43c39'),('right_stop','右肩止损','#e68a00'),('ihs_neckline','颈线','#7551ac'),('target','等距目标','#07845b')]:
            v=p[key]
            svg.append(f'<path d="M70 {y(v):.2f} H920" stroke="{color}" stroke-dasharray="6 4"/><text x="74" y="{y(v)-5:.2f}" fill="{color}" font-size="13">{label} {v:.2f}</text>')
        points=' '.join(f'{x(i):.2f},{y(v):.2f}' for i,v in enumerate(values))
        svg.append(f'<polyline points="{points}" fill="none" stroke="#167aaf" stroke-width="1.5"/>')
        for key,label in [('ihs_left_date','左肩'),('ihs_head_date','头部'),('ihs_right_date','右肩')]:
            i=dates[p[key]]; r=selected[i]; v=float(r['low'])*float(r['factor'])/p['factor']
            svg.append(f'<circle cx="{x(i):.2f}" cy="{y(v):.2f}" r="4" fill="#182d44"/><text x="{x(i):.2f}" y="{y(v)+18:.2f}" font-size="13">{label}</text>')
        for date,label in [(t['entry_date'],'买入'),(t['exit_date'],'退出')]:
            i=dates[date]
            svg.append(f'<path d="M{x(i):.2f} 50 V335" stroke="#8b939d"/><text x="{x(i)-35:.2f}" y="{35 if label=="买入" else 365}" font-size="13">{label} {date}</text>')
        svg.append(f'<text x="70" y="390" font-size="13">{selected[0]["date"]} — {selected[-1]["date"]}；收盘价折线，锚点取最低价；按信号日因子统一价格</text></svg>')
        filename=f'example-{index+1}.svg'; (out/filename).write_text(''.join(svg),encoding='utf-8')
        label='首笔止损退出' if index==0 else '首笔目标退出'
        fragments.append(f'<h3>{label}：{t["symbol"]}</h3><p>净损益 {float(t["pnl"]):,.2f} 元；已实现 {float(t["realized_r"]):.2f}R。</p><img style="width:100%" src="{filename}"/>')
    extra=f'<h2>进一步核对</h2><p>固定空账户筛选中，右肩组有 458 个信号通过风险检查，其中 {eligible} 个同时满足信号日股票资格。实际账户批准 61 个计划，最终成交 27 笔；持仓上限、风险预算与次日执行检查影响最终数量。</p><p>27 笔成交的左右肩跨度中位数为 {statistics.median(spans):.0f} 个自然日，最长 {max(spans)} 日。这暴露出当前识别未限制形态持续时间的问题：部分结构横跨多年，不能仅凭空间比例认为与截图完全一致。本次为隔离止损影响，未加入新的时间过滤。</p><h2>实际形态示例</h2><p>按退出日期选取首笔止损和首笔止盈，非挑选最佳与最差交易。</p>'+''.join(fragments)
    report=out/'report.html'
    report.write_text(report.read_text(encoding='utf-8').replace('</html>',extra+'</html>'),encoding='utf-8')
    verification=load(out/'verification.json')
    verification.update(head_equity_all_rows_match=True, all_filled_net_rr_above_3=True,
        filled_entries_after_signal=True, drawdown_independently_recomputed=True,
        right_screen_eligible=eligible, filled_pattern_calendar_days_median=statistics.median(spans),
        filled_pattern_calendar_days_max=max(spans), audit_script_sha256=sha(Path(__file__)))
    dump(out/'verification.json',verification)
    (out/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    print(json.dumps(verification,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
