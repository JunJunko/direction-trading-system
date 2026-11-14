"""Independently verify frozen retest plans, then write a cohort report."""
import csv
import hashlib
import html
import json
import math
import shutil
import sys
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trading_system.analysis import adjusted
from trading_system.domain import Bar

def load(p):return json.loads(p.read_text(encoding='utf-8'))
def read(p):
    if p.stat().st_size==0:return []
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def main():
    out=ROOT/'runs/20261024-qualified-w-cohort'
    manifest=load(out/'manifest.json')
    assert hashlib.sha256((out/'bars.csv').read_bytes()).hexdigest()==manifest['bars_sha256']
    for name,digest in manifest['source_hashes'].items():
        assert hashlib.sha256((ROOT/'src'/name).read_bytes()).hexdigest()==digest
    histories=defaultdict(list)
    for r in read(out/'bars.csv'):
        histories[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in
            ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    for seq in histories.values():seq.sort(key=lambda b:b.date)
    plans=load(out/'plans.json')
    for p in plans:
        known=adjusted([b for b in histories[p['symbol']] if b.date<=p['date']])
        seq=[b for b in known if b.date>p['w_known_at']]
        assert 1<=len(seq)<=14
        assert math.isclose(min(b.low for b in seq),p['stop'],rel_tol=1e-12)
        assert min(b.low for b in seq)>=p['w_neckline']*.975
        assert min(b.low for b in seq)<=p['w_neckline']*1.005
        assert max(b.high for b in seq)<p['target']
        assert seq[-1].close>seq[-1].open and seq[-1].close>known[-2].close
        assert seq[-1].close>p['w_neckline'] and p['stop']>p['w_floor']
        left=next(i for i,b in enumerate(known) if b.date==p['w_left_date'])
        right=next(i for i,b in enumerate(known) if b.date==p['w_right_date'])
        prior=known[left-20:left]
        assert len(prior)==20 and prior[-1].date<p['w_left_date']
        prices=[b.close for b in prior];avg=sum(prices)/20
        slope=sum((i-9.5)*(v-avg) for i,v in enumerate(prices))/sum((i-9.5)**2 for i in range(20))
        decline=(prices[0]-prices[-1])/prices[0]
        assert decline>=.05 and slope<0
        assert math.isclose(decline,p['w_prior_decline'],rel_tol=1e-10,abs_tol=1e-10)
        assert abs(known[right].low/known[left].low-1)<=.05+1e-12
        assert (p['w_neckline']-max(known[left].low,known[right].low))/max(known[left].low,known[right].low)>=.03-1e-12
        assert p['w_structure_invalidation']=='close_below_W_floor'
    audits=read(out/'candidate/entry_audit.csv')
    trades=read(out/'candidate/trades.csv')
    events=read(out/'candidate/decisions.csv')
    filled=[r for r in audits if r['execution_reason']=='filled']
    ids={p['setup_id']:p for p in plans}
    for r in filled:
        assert r['signal_date']<r['date']
        assert math.isclose(float(r['fill']),float(r['open'])*1.001,rel_tol=1e-12)
        assert float(r['w_entry_distance'])<=.02+1e-12 and float(r['net_rr'])>3
        assert r['setup_id'] in ids
    summaries={
        'v5.18 颈线回踩':load(out/'baseline/summary.json'),
        'v5.17 颈线突破':load(ROOT/'runs/20261024-direct-w-corrected/summary.json')['summary'],
        'v5.19 完整定义':load(out/'candidate/summary.json')}
    checks=dict(independent_plan_checks=len(plans),filled_order_checks=len(filled),
        baseline_v518_exact=manifest['baseline_v518_exact'],source_and_bars_hashes_match=True,
        event_counts=dict(Counter(r['event'] for r in events)),
        invalidations=dict(Counter(r['reason'] for r in events if r['event']=='w_retest_invalidated')),
        quality_reasons=dict(Counter(r['reason'] for r in events if r['event']=='w_quality_checked')),
        risk_reasons=dict(Counter(r['risk_reason'] for r in audits)),
        execution_reasons=dict(Counter(r['execution_reason'] for r in audits)),
        total_closed_net_pnl=sum(float(t['pnl']) for t in trades))
    (out/'verification.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    esc=lambda v:html.escape(str(v))
    def table(headers,rows):
        return '<table><thead><tr>'+''.join('<th>'+esc(x)+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table>'
    metrics=table(['版本','成交','胜率','账户收益','最大回撤'],[
        [name,s['filled_buys'],'无样本' if s['win_rate'] is None else f"{s['win_rate']:.2%}",f"{s['total_return']:.4%}",f"{abs(s['max_drawdown']):.4%}"] for name,s in summaries.items()])
    details=table(['股票','买入日','卖出日','入场价','退出价','净盈亏','R','退出原因'],[
        [t['symbol'],t['entry_date'],t['exit_date'],f"{float(t['entry']):.4f}",f"{float(t['exit']):.4f}",f"{float(t['pnl']):.2f}",f"{float(t['realized_r']):.2f}",t['reason']] for t in trades])
    reasons=table(['审核原因（含重复执行审核）','次数'],checks['risk_reasons'].items())
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>v5.19 完整定义实验</title><style>body{font:16px/1.7 system-ui;max-width:1150px;margin:40px auto;padding:20px;color:#162233}table{border-collapse:collapse;width:100%;margin:20px 0}th,td{border-bottom:1px solid #ccd4df;padding:9px;text-align:left}th{background:#edf3f9}h1{font-size:28px}</style><h1>完整双底识别：同一结构的颈线回踩</h1><p>固定 62 股研究样本；2025-10-09 至 2026-09-30，100 万共享账户。非全市场、非独立保留样本。</p><p>新增左底前20根日线至少下跌5%且斜率向下、中间反弹至少3%、两底容差5%。突破确认后 14 根日线内回踩颈线附近并收阳恢复，次日开盘买入。止损取实际回踩低点，原 W 底线单独保留。止损距离 ≤2%，含费用净 RR &gt;3；目标沿用一个 W 高度，收盘达到后次日退出。参数未按本轮结果调整。</p>'''
    page+=metrics+f'<p>恢复入场计划 {len(plans)} 个，实际买入 {len(filled)} 笔；逐计划回踩低点、因果日期和原目标均已独立核验。v5.18 旧账户精确复现，源码及行情指纹一致。日线无法证明秒级成交，保留 T+1 和滑点假设。</p>'+reasons+details+'</html>'
    (out/'report.html').write_text(page,encoding='utf-8')
    shutil.copy2(__file__,out/'source/report_qualified_w.py')
    print(json.dumps(dict(summaries=summaries,verification=checks),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
