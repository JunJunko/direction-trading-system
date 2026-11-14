"""Render the fixed-entry research audit without changing its frozen results."""
import csv,json,html,sys
from pathlib import Path
root=Path(sys.argv[1]);load=lambda p:json.loads(p.read_text(encoding='utf-8'))
def read(p):
    with p.open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))
def table(headers,rows):
    return '<table><thead><tr>'+''.join('<th>'+html.escape(str(x))+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table>'
results=load(root/'comparison.json')['results'];trades=read(root/'paired_trades.csv')
labels={'A0':'原版收盘目标','A1':'首次触及软目标','B1':'强突破延续','B2':'确认波谷支撑','B3':'另加 ATR 风险保护'}
body='<h1>双底目标突破：固定入场配对研究 v0.1</h1><p>2025-10-09 至 2026-09-30 · 14 笔实际入场 / 12 只股票 · 初始资金 100 万元 · 原 v5.19 入场集合</p>'
body+='<div class="notice"><b>研究验收未通过，保留为实验。</b>只有 002451.SZ 一笔进入强突破延续。B2/B3 收益提升，但回撤明显增加；配对增益区间跨零。没有独立样本外验证，未修改默认策略。</div>'
body+=table(['实验','净收益率','最大回撤','胜率','净利润（元）','相对 A0（元）','相对 A1（元）'],[
    [k+' '+labels[k],f'{v["return_pct"]:.4f}%',f'{v["max_drawdown_pct"]:.4f}%',f'{v["win_rate"]:.2%}',f'{v["net_pnl"]:,.2f}',f'{v["paired_delta"]:+,.2f}',f'{v["net_pnl"]-results["A1"]["net_pnl"]:+,.2f}'] for k,v in results.items()])
body+='<h2>现金与权益：相同入场，独立持仓批次汇总</h2><p>A0 原共享账户订单、交易、入场审计和权益全部精确复现；独立批次 A0 的现金及权益也逐日相同。其余实验不重算入场风险门槛，因此是出场归因实验，不是可直接部署的账户绩效。</p>'
colors=['#94a3b8','#fbbf24','#fb7185','#38bdf8','#4ade80']
curves={a:read(root/a/'equity.csv') for a in results}
for field,title in [('equity','权益'),('cash','现金')]:
    values=[float(row[field]) for rows in curves.values() for row in rows];lo=min(values);hi=max(values)
    body+=f'<h3>{title}（万元）</h3><svg viewBox="0 0 1000 290" role="img" aria-label="{title}曲线">'
    for i in range(5):
        value=lo+(hi-lo)*i/4;y=245-i*52
        body+=f'<line x1="70" y1="{y}" x2="975" y2="{y}" stroke="#334155"/><text x="2" y="{y}" fill="#cbd5e1">{value/10000:.1f}</text>'
    for (arm,rows),color in zip(curves.items(),colors):
        points=' '.join(f'{70+i/(len(rows)-1)*905:.1f},{245-(float(row[field])-lo)/(hi-lo)*208:.1f}' for i,row in enumerate(rows))
        body+=f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"><title>{arm}</title></polyline>'
    body+='<text x="70" y="280" fill="#cbd5e1">2025-10-09</text><text x="870" y="280" fill="#cbd5e1">2026-09-30</text></svg>'
body+='<p>'+''.join(f'<span style="color:{c};margin-right:24px">{a}</span>' for a,c in zip(results,colors))+'</p>'
body+='<h2>002451.SZ：延长持仓不是免费收益</h2>'
sample=[t for t in trades if t['symbol']=='002451.SZ' and t['entry_date']=='20251103']
body+=table(['实验','卖出日','卖出价','净利润','最大浮盈*','浮盈回吐*','支撑上移首次日'],[[t['arm'],t['exit_date'],f'{float(t["exit_price"]):.4f}',f'{float(t["net_pnl"]):,.2f}',f'{float(t["MFE"]):,.2f}',f'{float(t["max_profit_giveback"]):,.2f}',t['stop_raise_at'] or '无'] for t in sample])
body+='<p>B1 一直保留原止损，最终从赢家变成亏损；B2 等待确认波谷后才抬保护，仍承受较大回吐；B3 的较早退出来自独立 ATR 风险线，不能归功于支撑识别。</p>'
body+='<h2>失败案例与归因</h2><p>603031.SH 和 603272.SH 在首次盘中触及目标、收盘未满足强突破门槛后退出，分别比 A0 少赚 4,655.61 元、3,166.29 元，共少赚 7,821.90 元。所有原版亏损交易的结果没有改善。剔除 002451.SZ 后，B2/B3 相对 A0 均只剩这两笔损失；不能挑选成功案例得出优势。</p>'
body+='<h2>可核对的状态迁移</h2>'
for arm in ('B2','B3'):
    events=[json.loads(line) for line in (root/arm/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    chosen=[e for e in events if e.get('trade_id')==sample[0]['trade_id'] and e.get('reason_code') in ('first_target_touch','breakout_candidate','acceptance_confirmed','confirmed_support_available','confirmed_support_stop_raised','volatility_guard_raised')]
    body+=f'<details><summary>{arm}：首次触及、接受、支撑/风险线变更（{len(chosen)} 条）</summary>'
    body+=table(['日期','原因','确认 bar','最早生效 bar','支撑价','旧保护','新保护'],[[e['date'],e['reason_code'],e.get('t_confirmed'),e.get('valid_from'),e.get('level_price'),e.get('old_stop'),e.get('new_stop')] for e in chosen])+'</details>'
body+='<h2>不确定性及适用范围</h2>'
body+=table(['实验','按股票聚类的探索性 95% 增益区间（元）','费用×2净利润（固定填价）','最大同时持仓批次'],[[a,str([round(x,2) for x in r['exploratory_symbol_cluster_bootstrap_95']]),f'{r["cost_sensitivity_fixed_fills"]["2"]:,.2f}',r['max_open_lots']] for a,r in results.items()])
body+='<ul><li>费用压力测试只放大显式费用，未改变滑点和成交可得性；季度分组不是市场状态分类。14 笔交易、12 只股票的 bootstrap 仅作探索。</li><li>* MFE/MAE 使用收盘仍持仓交易日的高低价，整根退出日排除，避免把卖出后的高点当成持有浮盈；这是保守范围。回吐为该毛浮盈减最终扣费净利润，含成本。</li><li>missed_upside 为退出后固定 5 个交易日最高价对应的毛机会差，交易日缺失/样本尾部不足的观察数单独记录；不代表可实现交易。</li><li>新止损只在确认后下一可执行时点生效。缺量、停牌及一字跌停由原执行器延期；涨停本身不会强制卖出，也不会取消已触发的风险或失败退出。</li><li>原执行器并无“账户风险超限自动强平”分支；本轮没有擅自补造。账户准入规则保持原样，固定入场实验不重算账户缩放。OHLC 无法还原盘中路径，继续使用原止损优先的保守顺序。</li><li>B4 未执行：仓库缺 SYSTEM_V23_PRESSURE_WARNING.md、SYSTEM_V24_ATTACK_FAILURE.md 及对应原规则。路线 B 回踩接受也未混入本轮。</li><li>600521、000851、601163、600250 指定旧案例未在本 14 笔实际成交集合内，不能冒充已回归；需原研究数据。最终留出未开启，独立后段验证尚未完成。</li></ul>'
body+='<h2>全部 70 行配对记录</h2><p><a href="paired_trades.csv">下载完整逐笔字段 CSV</a> · <a href="comparison.json">汇总 JSON</a> · <a href="sha256.json">源码及输入 SHA256</a></p>'
body+=table(['实验','股票','入场','退出','数量','净利润','净 R','相对原版','原因'],[[t['arm'],t['symbol'],t['entry_date'],t['exit_date'],t['quantity'],f'{float(t["net_pnl"]):,.2f}',f'{float(t["realized_R_after_fees"]):.3f}',f'{float(t["delta_net_pnl"]):+,.2f}',t['reason']] for t in trades])
body+='<h2>原始审计文件</h2><ul>'+''.join(f'<li>{a}：<a href="{a}/config.json">参数</a> · <a href="{a}/orders.csv">订单费用</a> · <a href="{a}/equity.csv">逐日现金权益</a> · <a href="{a}/events.jsonl">关键线事件</a> · <a href="{a}/trades.csv">交易指标</a></li>' for a in results)+'</ul>'
page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>动态关键线迁移配对研究</title><style>body{background:#0f172a;color:#e2e8f0;font:16px/1.7 system-ui;max-width:1250px;margin:36px auto;padding:0 24px}h1,h2{color:#93c5fd}h2{margin-top:36px}table{width:100%;border-collapse:collapse;font-size:14px;margin:20px 0}td,th{padding:9px;border-bottom:1px solid #334155;text-align:right}td:first-child,th:first-child{text-align:left}th{background:#1e293b}.notice{padding:20px;background:#30263a;border-left:4px solid #fbbf24}a{color:#7dd3fc}svg{width:100%;background:#162033}details{padding:12px;background:#1e293b;margin:12px 0}</style>'+body+'</html>'
(root/'report.html').write_text(page,encoding='utf-8')
print(root/'report.html')
