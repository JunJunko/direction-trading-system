"""Consolidate independent C study; no fitting or production changes."""
import sys,json,csv,html,hashlib,shutil,statistics
from pathlib import Path
P=Path('runs/20261024-causal-target-verified');A=Path('runs/20261024-causal-account-verified')
E=Path('runs/20261024-causal-events-final');O=Path('runs/20261024-causal-target-study')
L=Path('runs/20261024-causal-events-long-history')
load=lambda p:json.loads(p.read_text(encoding='utf-8'))
def rows(p):
    with p.open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))
def dump(p,data):p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
def table(headers,rs):
    return '<table><thead><tr>'+''.join('<th>'+html.escape(str(v))+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in r)+'</tr>' for r in rs)+'</tbody></table>'
def save(p,rs):
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
def main():
    results=load(P/'comparison.json')['results'];trades=rows(P/'paired_trades.csv');account=rows(A/'comparison.csv')
    es=load(E/'summary.json');long=load(L/'summary.json');regression=load(P/'regression.json')
    byarm={a:[r for r in trades if r['arm']==a] for a in results};metrics=[]
    for arm,ts in byarm.items():
        profits=sorted(float(t['net_pnl']) for t in ts)
        metrics.append(dict(arm=arm,mean_net_pnl=statistics.mean(profits),median_net_pnl=statistics.median(profits),
            mean_net_R=statistics.mean(float(t['marked_R']) for t in ts),worst_trade=profits[0],worst3_mean=statistics.mean(profits[:3]),
            pnl_stdev=statistics.stdev(profits),mean_MFE=statistics.mean(float(t['MFE']) for t in ts),
            mean_MAE=statistics.mean(float(t['MAE']) for t in ts),mean_giveback=statistics.mean(float(t['max_profit_giveback']) for t in ts),
            mean_holding_bars=statistics.mean(float(t['holding_bars']) for t in ts),
            t1_count=sum(t['whether_t1_hit']=='True' for t in ts),gap_count=sum(t['any_gap_beyond_stop']=='True' for t in ts)))
    save(O/'risk-distribution.csv',metrics)
    c2={r['trade_id']:r for r in byarm['C2']};paired=[]
    for r in byarm['C4']:
        base=c2[r['trade_id']]
        paired.append(dict(trade_id=r['trade_id'],symbol=r['symbol'],entry_date=r['entry_date'],
            C2_exit=base['exit_date'],C4_exit=r['exit_date'],C2_pnl=float(base['net_pnl']),C4_pnl=float(r['net_pnl']),
            delta_net_pnl=float(r['net_pnl'])-float(base['net_pnl']),delta_R=float(r['marked_R'])-float(base['marked_R']),
            delta_giveback=float(r['max_profit_giveback'])-float(base['max_profit_giveback']),
            delta_holding_bars=float(r['holding_bars'])-float(base['holding_bars'])))
    save(O/'C4-minus-C2.csv',paired)
    # Attribute executable stops to prior, already-effective risk lines without rewriting the engine's reason.
    line_changes=[];exit_sources=[]
    for arm in results:
        events=[json.loads(s) for s in (P/arm/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        for t in byarm[arm]:
            changes=[e for e in events if e.get('trade_id')==t['trade_id'] and e.get('reason_code')=='execution_risk_stop_raised' and e['date']<t['exit_date']]
            origin=changes[-1]['line_source'] if changes else 'original'
            exit_sources.append(dict(arm=arm,trade_id=t['trade_id'],symbol=t['symbol'],exit_date=t['exit_date'],
                engine_reason=t['reason'],active_risk_source=origin if 'support_break' in t['reason'] else 'target_or_candidate_decision'))
        for e in events:
            if e.get('reason_code') in ('confirmed_support_available','atr_risk_line_changed','structure_risk_line_changed','execution_risk_stop_raised'):
                line_changes.append(dict(arm=arm,trade_id=e['trade_id'],symbol=e['symbol'],date=e['date'],
                    formed_at=e['formed_at'],confirmed_at=e['confirmed_at'],valid_from_date=e['valid_from_date'],
                    source=e['source'],reason=e['reason_code'],level_id=e.get('level_id'),
                    price=e.get('new_line',e.get('new_stop',e.get('level_price'))),old_price=e.get('old_line',e.get('old_stop'))))
    save(O/'line-changes.csv',line_changes);save(O/'exit-attribution.csv',exit_sources)
    incremental=dict(paired_delta_net_pnl=sum(r['delta_net_pnl'] for r in paired),
        paired_delta_max_drawdown_pct=results['C4']['max_drawdown_pct']-results['C2']['max_drawdown_pct'],
        affected_trades=sum(abs(r['delta_net_pnl'])>1e-6 for r in paired),
        account_deltas={s:next(float(r['net_pnl']) for r in account if r['scenario']==s and r['arm']=='C4')-next(float(r['net_pnl']) for r in account if r['scenario']==s and r['arm']=='C2') for s in ('base','cost_1_5x','cost_2x')},
        conclusion='No demonstrated incremental value of structure module over pure ATR in this sample; worse net PnL, unchanged maximum drawdown. Do not add indicators or promote.')
    incremental['mean_giveback_C2']=next(m['mean_giveback'] for m in metrics if m['arm']=='C2')
    incremental['mean_giveback_C4']=next(m['mean_giveback'] for m in metrics if m['arm']=='C4')
    account_gates=[]
    for arm in results:
        audits=rows(A/'base'/arm/'entry_audit.csv');counts={}
        for row in audits:
            reason=row.get('risk_reason') or row.get('execution_reason');counts[reason]=counts.get(reason,0)+1
        account_gates.extend(dict(arm=arm,reason=reason,audit_rows=count) for reason,count in counts.items())
    save(O/'account-gate-reasons.csv',account_gates)
    dump(O/'incremental-structure-test.json',incremental)
    body='<h1>双底目标突破：独立 C0–C4 研究</h1><p>2026-10-24 · 数值参数冻结 · 正式策略不变 · 固定入场、账户复验与结构事件分开报告</p><p>293 项测试通过，73 条结构/风险线变更通过时序核对。<a href="verification.json">验证记录</a> · <a href="tests.log">完整测试日志</a></p>'
    body+='<div class="notice"><b>反证结论：当前样本没有证明结构模块相对纯 ATR 的增量价值。</b> C4 比 C2 少赚 '+f'{-incremental["paired_delta_net_pnl"]:,.2f}'+' 元，最大回撤相同。真实账户及加大成本后仍落后。纯 ATR 虽提高开发样本收益，也提高了相对原版的回撤，不能据此升级实盘。</div>'
    body+='<h2>目标时序修正</h2><p>普通盘中触及 T0 只记录事件，不提前卖出。到原版首次收盘 ≥ T0 的决策时点，先检查当时已经观察到的强突破证据，再决定是否豁免目标卖单。未来收盘不能撤销旧卖单。候选失败按下一可执行时点退出，保护止损仍优先。</p><p>C2/C4 的 ATR 风险线从候选收盘计算、下一交易日生效；C3/C4 的结构模块在接受确认后启用。新波谷以右侧两根 K 线确认；结构缓冲在激活时冻结。之后 ATR 收缩只影响 ATR 风险线，不记作新支撑。</p>'
    body+='<h2>固定入场：14 笔配对</h2><p>2025-10-09 至 2026-09-30，初始 100 万元。日期、数量、入场价格、费用和初始风险完全相同。C0 逐笔与逐日现金权益精确回归 A0。</p>'
    names={'C0':'原版','C1':'仅豁免目标','C2':'纯 ATR 保护','C3':'纯结构保护','C4':'ATR＋独立结构保护'}
    body+=table(['实验','收益率','最大回撤','胜率','每笔扣费期望（元）','平均净 R','最差三笔均值'],[[a+' '+names[a],f'{r["return_pct"]:.4f}%',f'{r["max_drawdown_pct"]:.4f}%',f'{r["win_rate"]:.2%}',f'{m["mean_net_pnl"]:,.2f}',f'{m["mean_net_R"]:.3f}',f'{m["worst3_mean"]:,.2f}'] for (a,r),m in zip(results.items(),metrics)])
    colors=['#94a3b8','#fb7185','#4ade80','#fbbf24','#38bdf8']
    for field,label in [('equity','权益（万元）'),('drawdown','回撤（%）')]:
        curves={a:rows(P/a/'equity.csv') for a in results};values=[float(x[field]) for rs in curves.values() for x in rs];lo=min(values);hi=max(values)
        body+=f'<h3>{label}</h3><svg viewBox="0 0 1000 280">'
        for i in range(5):
            y=240-50*i;value=lo+(hi-lo)*i/4;display=value/10000 if field=='equity' else value*100
            body+=f'<line x1="70" y1="{y}" x2="975" y2="{y}" stroke="#334155"/><text x="4" y="{y}" fill="#cbd5e1">{display:.2f}</text>'
        for (a,rs),color in zip(curves.items(),colors):
            points=' '.join(f'{70+i/(len(rs)-1)*905:.1f},{240-(float(x[field])-lo)/(hi-lo)*200:.1f}' for i,x in enumerate(rs))
            body+=f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"><title>{a}</title></polyline>'
        body+='<text x="70" y="270" fill="#cbd5e1">2025-10-09</text><text x="860" y="270" fill="#cbd5e1">2026-09-30</text></svg>'
    body+='<p>'+''.join(f'<span style="color:{color};margin-right:25px">{a}</span>' for a,color in zip(results,colors))+'</p>'
    body+='<h2>真实账户约束复验</h2><p>历史模拟账户，使用原 99 个信号、62 只股票；原现金、仓位上限、风险准入、回撤收缩、T+1、费用和成交器全部生效。退出变化会改变后续成交数量与交易集合。它仍是既有信号股票池复验，不是全市场实盘绩效。</p>'
    body+=table(['实验','收益率','最大回撤','成交笔数','胜率','每笔扣费期望'],[[r['arm'],f'{float(r["return_pct"]):.4f}%',f'{float(r["max_drawdown_pct"]):.4f}%',r['trades'],f'{float(r["win_rate"]):.2%}',f'{float(r["mean_net_pnl"]):,.2f}'] for r in account if r['scenario']=='base'])
    body+='<h2>关键回归与错误退出</h2>'
    focus=[t for t in trades if t['symbol'] in ('603031.SH','603272.SH') or (t['symbol']=='002451.SZ' and t['entry_date']=='20251103')]
    body+=table(['股票','实验','首次触及','突破候选','接受','退出日','扣费利润'],[[t['symbol'],t['arm'],t['target_touch_at'],t['decisive_break_at'],t['acceptance_at'],t['exit_date'],f'{float(t["net_pnl"]):,.2f}'] for t in focus])
    body+='<p>603031.SH、603272.SH 均不再比 A0 提前退出，002451.SZ 保留 11-04 候选。603031 的候选失败使它延后一天退出，仍比原版少赚约 1,054 元：修复提前卖出不保证所有交易改善。603272 的结构保护在 01-27 退出，纯 ATR 持有至 03-02；它解释了本轮 C4 对 C2 的全部净利润差。C1 把 002451 和 603272 的原盈利拖成亏损，是保留原宽止损的风险反例。</p>'
    body+='<h2>MFE、MAE 与回吐</h2>'
    body+=table(['实验','平均毛浮盈 MFE','平均毛浮亏 MAE','平均回吐','平均持仓 bars','跳空越止损笔数'],[[m['arm'],f'{m["mean_MFE"]:,.2f}',f'{m["mean_MAE"]:,.2f}',f'{m["mean_giveback"]:,.2f}',f'{m["mean_holding_bars"]:.1f}',m['gap_count']] for m in metrics])
    body+='<p>MFE/MAE 使用收盘仍持仓日期的高低点，排除整根退出日，避免把卖出后高点算进持有浮盈；它是可复核的保守口径。回吐为该毛浮盈减最终净利润，包含成本。持仓 bars 为收盘持仓天数，不含退出日。C4 平均回吐从 C2 的 5,627 元降至 5,134 元，暴露时间也更短；但平均 MAE、最差三笔损失和最大回撤未改善，净收益下降。较早退出截短了可观察 MFE，不能把这一项回吐下降当成整体风险收益优势。</p>'
    body+='<h2>执行成本敏感性：实际重新成交</h2><p>佣金费率与滑点分别按原值的 1、1.5、2 倍重跑账户；最低佣金与印花税不变。会重新经过买入风险和成交检查，因此成交数量也会变化，不是简单从利润扣一个费用数。</p>'
    body+=table(['成本情景','实验','收益率','回撤','成交笔数','总费用'],[[r['scenario'],r['arm'],f'{float(r["return_pct"]):.3f}%',f'{float(r["max_drawdown_pct"]):.3f}%',r['trades'],f'{float(r["total_fees"]):,.2f}'] for r in account])
    body+='<h2>扩展结构事件研究</h2><p>冻结数据包含 '+str(es['input_symbols'])+' 只股票、'+f'{es["input_bars"]:,}'+' 根日线。历史 ST 资格只覆盖 2025-10-09 至 2026-09-30，因此全池可确认资格事件限于该区间；2024 年被过滤为零不代表没有形态。结构后观察 60 根可用日线是否触及目标，候选后固定看 20 根日线。此处不要求真实买入，不受资金筛选，不能当成交易胜率。</p>'
    event_rows=[('全池已知资格区间',es['all'])]+[(y,v) for y,v in es['years'].items() if y!='2024']
    unresolved=es['all']['candidates']-es['all']['accepted']-es['all']['candidate_failed']
    body+=table(['登记期','结构数','股票数','触及目标','强突破候选','接受','候选失败','候选完整20根','20根末在T0上方','20根内曾跌回T0下方'],[[label]+[r[k] for k in ('structures','symbols','touches','candidates','accepted','candidate_failed','candidates_complete20','continued20','failed_below_target20')] for label,r in event_rows])
    body+='<p>“20 根内曾跌回”与“第 20 根站回上方”可以重叠，不是互斥成功/失败标签。目标观察期尾部不足 '+str(es['all']['target_window_censored'])+' 个，候选后不足 20 根 '+str(es['all']['candidates_censored20'])+' 个，均单独标记。重复股票与重叠形态相关，结构数不是独立样本数。股票池来自历史冻结快照，退市样本覆盖尚未另行审计。</p>'
    body+=f'<p>接受/候选失败只统计结构后的 60 根观察窗内，窗末仍未决候选 {unresolved} 个，不算成功或失败；后续 20 根结果另列，不反填前面的状态。</p>'
    body+='<h3>长历史补充：固定哈希抽样 500 只股票</h3><p>从冻结股票池按 SHA256(股票代码) 升序取前 500 只，与收益表现无关；完整扫描 2024-01-01 至 2026-09-30，2023 年预热。数值参数完全不变。此前缺失的交易资格标为未知，不把它们视作历史可交易样本。它与全池研究部分重叠，两组数量不能相加当成独立样本。</p>'
    body+=table(['登记期','结构数','触及目标','强突破候选','候选完整20根','20根末在T0上方','20根收盘均值变化（毛）'],[[y,r['structures'],r['touches'],r['candidates'],r['candidates_complete20'],r['continued20'],f'{r["mean_candidate_forward20"]:.2%}' if r['mean_candidate_forward20'] is not None else '无样本'] for y,r in [('全部',long['all'])]+list(long['years'].items())])
    body+=table(['资格标签','结构数','强突破候选'],[[k,v['structures'],v['candidates']] for k,v in long['eligibility_groups'].items()])
    body+='<p><a href="../20261024-causal-events-long-history/events.csv">长历史全部事件</a> · <a href="../20261024-causal-events-long-history/symbols.json">固定抽样名单</a>。后续 20 根收益是价格事件标签，未扣费用，也未应用止损，不能当成 C2/C4 的回测收益。</p>'
    body+='<h2>证据边界与后续验证</h2><p>C1 在配对和账户模式均恶化。C2 提高开发期扣费期望收益，但回撤高于 C0，增益仍集中少数交易。C3 的配对利润提高、真实账户利润却低于 C0，体现持仓占资和风险收缩影响。C4 比 C2 收益更低且最大回撤相同，当前没有结构模块增量价值证据。</p><p>开发池已反复使用，历史扩展也是机制研究，不能称为全新样本外。前瞻计划锁定 C0/C2/C4、原数值参数和成本压力情景，最早从 2026-11-02 开始，至 2027-10-29 后单次评估；至少 50 个已结束候选、覆盖 30 只股票，不足则结论仍为不充分。按股票及时间分块评估扣费 R、账户收益、回撤和尾部损失；期间不看表现调参，不自动升级正式策略。</p>'
    body+=table(['实验','相对 C0 的股票聚类探索性 95% 增益区间（元）'],[[a,str([round(v,2) for v in r['exploratory_symbol_cluster_bootstrap_95']])] for a,r in results.items()])
    body+='<p>只有 14 笔固定交易、12 只股票；以上区间仅为开发样本的探索性重抽样，不构成独立显著性证明。</p>'
    body+='<h2>复核文件</h2><ul><li><a href="../20261024-causal-target-verified/paired_trades.csv">70 行完整逐笔配对</a> · <a href="C4-minus-C2.csv">C4−C2 专项逐笔反证</a> · <a href="risk-distribution.csv">收益风险分布</a></li><li><a href="line-changes.csv">保护与结构变更：价格、形成、确认、可执行日及来源</a> · <a href="exit-attribution.csv">退出风险线归因</a></li><li><a href="../20261024-causal-account-verified/comparison.csv">账户及成本敏感性</a> · <a href="../20261024-causal-events-final/events.csv">扩展结构事件</a> · <a href="../20261024-causal-events-final/summary.json">事件统计</a></li><li><a href="research-protocol.json">研究与前瞻样本外方案</a> · <a href="../20261024-causal-target-verified/regression.json">重点案例与缓存等价回归</a> · <a href="sha256.json">源码/参数 SHA256</a></li></ul>'
    for arm in results:
        body+=f'<p>{arm}：<a href="../20261024-causal-target-verified/{arm}/equity.csv">配对权益/现金/回撤</a> · <a href="../20261024-causal-account-verified/base/{arm}/equity.csv">账户权益/现金/回撤</a> · <a href="../20261024-causal-target-verified/{arm}/events.jsonl">完整状态与关键线日志</a> · <a href="../20261024-causal-target-verified/{arm}/config.json">参数</a></p>'
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>独立 C0–C4 双底研究</title><style>body{background:#0f172a;color:#e2e8f0;font:16px/1.7 system-ui;max-width:1280px;margin:40px auto;padding:0 24px}h1,h2{color:#93c5fd}h2{margin-top:38px}table{border-collapse:collapse;width:100%;font-size:14px;margin:20px 0}th,td{padding:9px;text-align:right;border-bottom:1px solid #334155}th{background:#1e293b}td:first-child,th:first-child{text-align:left}a{color:#7dd3fc}.notice{padding:20px;border-left:4px solid #fbbf24;background:#30263a}svg{width:100%;background:#162033}</style>'+body+'</html>'
    (O/'report.html').write_text(page,encoding='utf-8')
    src=O/'source';src.mkdir(exist_ok=True)
    for p in [Path('src/trading_system/strategies/causal_target_w.py'),Path('src/trading_system/target_migration.py')]+list(Path('scripts').glob('*causal*.py'))+[Path('tests/test_causal_target.py')]:shutil.copy2(p,src/p.name)
    files=list(src.glob('*.py'))+[O/'research-protocol.json',E/'protocol.json',E/'summary.json',E/'source-study.py',L/'protocol.json',L/'summary.json',P/'comparison.json',A/'protocol.json']
    dump(O/'sha256.json',{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
    dump(O/'conclusion.json',dict(production_promoted=False,independent_validation_completed=False,structural_increment=incremental,
        paired=results,account=account,event_study=es,long_history_event_study=long,regression=regression))
    print(json.dumps(incremental,ensure_ascii=False))
if __name__=='__main__':main()
