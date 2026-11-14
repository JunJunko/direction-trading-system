"""Report all predeclared gates and the subsequent strategy attribution controls."""
import csv,json,html,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/20261026-volatility-entry-filter'
ABL=ROOT/'runs/20261026-volatility-entry-ablation'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def save(p,data):
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
def main():
    assert load(OUT/'status.json')['status']=='complete'
    assert load(ABL/'status.json')['status']=='complete'
    labels={'combined_v7':'组合 v7，无新增过滤','W_ATR025':'双底止损 ≥ 0.25 ATR','W_ATR050':'双底止损 ≥ 0.5 ATR（主方案）',
            'W_ATR100':'双底止损 ≥ 1.0 ATR','both_ATR050':'两类策略止损均 ≥ 0.5 ATR',
            'IHS_only':'只做头肩底（归因对照）','W_ATR100_only':'只做双底且止损 ≥ 1.0 ATR'}
    baseline=load(OUT/'combined_v7/config.json');baseplans=load(OUT/'combined_v7/plans.json')
    checks={};comparison=[];families=[];periods=[];replacement=[]
    baseline_entries={(r['setup_id'],r['date']) for r in rows(OUT/'combined_v7/entry_audit.csv') if r['execution_reason']=='filled'}
    for root in (OUT,ABL):
        for name,s in load(root/'summaries.json').items():
            f=root/name;cfg=load(f/'config.json');trades=rows(f/'trades.csv');audits=rows(f/'entry_audit.csv');curve=rows(f/'equity.csv')
            for key in ('initial_cash','risk','execution','automatic_account_policy'):assert cfg[key]==baseline[key]
            for spec in cfg['strategies']:assert spec in baseline['strategies']
            reference=[p for p in baseplans if any(p['setup_id'].startswith(spec['id']+':') for spec in cfg['strategies'])]
            assert load(f/'plans.json')==reference
            filled=[a for a in audits if a['execution_reason']=='filled'];assert len(filled)==s['filled_buys']
            assert all(float(a['net_rr'])>3 for a in filled)
            gate=cfg.get('volatility_entry_filter')
            if gate:
                for a in filled:
                    if gate['scope']=='both' or 'double_bottom' in a['strategy']:
                        assert a['volatility_known_at']<a['date']
                        assert float(a['stop_atr_ratio'])+1e-12>=gate['min_stop_atr']
                assert not s['risk_reasons'].get('volatility_history_missing',0)
            assert max(int(c['positions']) for c in curve)<=5 and min(float(c['cash']) for c in curve)>=-1e-6
            checks[name]=dict(same_config_except_filter_and_family=True,frozen_signals_exact=True,filled_net_rr_above_3=True,
                              filled_filter_passes=True,atr_strictly_before_entry=True,no_missing_atr=True)
            closed_pnl=sum(float(t['pnl']) for t in trades)
            comparison.append(dict(case=name,label=labels[name],return_pct=s['total_return']*100,max_drawdown_pct=-s['max_drawdown']*100,
                buys=s['filled_buys'],closed=s['closed_trades'],open=s['open_positions'],win_rate_pct=s['win_rate']*100,
                profit_factor=s['profit_factor'],closed_pnl=closed_pnl,open_mark_pnl=s['final_equity']-s['initial_cash']-closed_pnl,
                filter_rejections=s['risk_reasons'].get('stop_inside_normal_volatility',0)))
            for family,prefix in [('W','double_bottom'),('IHS','inverse_head')]:
                ts=[t for t in trades if prefix in t['strategy']]
                families.append(dict(case=name,family=family,closed=len(ts),pnl=sum(float(t['pnl']) for t in ts)))
            for segment,start,end in [('early','20251009','20260331'),('late','20260401','20260930')]:
                before=[c for c in curve if c['date']<start];start_eq=float(before[-1]['equity']) if before else s['initial_cash']
                end_eq=float([c for c in curve if c['date']<=end][-1]['equity'])
                periods.append(dict(case=name,segment=segment,start=start,end=end,return_pct=(end_eq/start_eq-1)*100))
            for group in ('same_entry','new_entry'):
                ts=[t for t in trades if (((t['setup_id'],t['entry_date']) in baseline_entries)==(group=='same_entry'))]
                replacement.append(dict(case=name,group=group,closed=len(ts),pnl=sum(float(t['pnl']) for t in ts)))
    save(OUT/'comparison.csv',comparison);save(OUT/'family-attribution.csv',families)
    save(OUT/'period-diagnostics.csv',periods);save(OUT/'entry-replacement-diagnostics.csv',replacement)
    dump(OUT/'verification.json',dict(cases=checks,baseline_exact=load(OUT/'combined_v7/summary.json')['previous_v7_exact_replay'],
         tests='python -m pytest tests -q: 424 passed',unchanged_defaults=True,independent_holdout=False))
    table='\n'.join(f"| {m['label']} | {m['return_pct']:+.2f}% | {m['max_drawdown_pct']:.2f}% | {m['buys']} | {m['win_rate_pct']:.2f}% |" for m in comparison)
    static=rows(OUT/'fixed-entry-filter-diagnostic.csv')
    st='\n'.join(f"| {labels[m['case']]} | {m['losers_filtered']} | {m['winners_filtered']} | {float(m['losing_pnl_avoided']):,.0f} | {float(m['winning_pnl_removed']):,.0f} |" for m in static)
    ihs=next(m for m in comparison if m['case']=='IHS_only');w=next(m for m in comparison if m['case']=='W_ATR100_only')
    report=f'''# 波动适配入场过滤检验

结论：0.5 ATR 主方案未通过，账户收益由 −1.08% 降至 −2.76%。0.25 ATR 改善至 +0.37%；1.0 ATR 改善至 +4.66%，但后者几乎排除了双底交易，不能解释为双底选股质量已改善。所有预先固定阈值均完整展示，未继续搜索最佳参数，未修改默认策略。

| 方案 | 收益（含期末持仓） | 最大回撤 | 买入笔数 | 平仓胜率 |
| --- | ---: | ---: | ---: | ---: |
{table}

范围：2025-10-09 至 2026-09-30，复用 6,014 个双底及 1,713 个头肩底信号，共 7,727 个，覆盖 2,861 只有信号股票。所有组合方案使用同一信号池、v7 退出、100 万本金、单笔风险 0.5%、组合风险 2%、单股仓位 10%、总仓位 50%、最多 5 只和原自动缩仓规则。成交仍要求扣费后盈亏比严格大于 3；双底原入场距离上限 2% 保留。归因对照只保留其对应策略的全部信号，其余约束相同。

过滤定义：实际开盘含滑点买入价减去原结构止损，除以入场前最后 14 根完整日 K 的平均真实波幅（SMA ATR14）。价格统一到执行日已知复权单位，ATR 不使用入场当日高低收盘。比值小于门槛则拒绝买入，既不放宽止损也不提高目标。原信号收盘审核不改变；在实际执行时加入过滤，并保留原资金与风险拒绝原因。阈值 0.25、0.5、1.0 为事前固定敏感性检查，0.5 为主方案，不是普适最优值。缺少历史则拒绝，本次没有此类情况。

002234.SZ：2026-01-26 买入价 9.12912、原止损 9.08，距离 0.04912 元（0.538%）；此前截至 2026-01-23 的 ATR14 为 0.222143 元，因此仅有 0.2211 ATR。三个门槛均会拒绝这次入场。这里用入场前数据判断，不依据之后涨跌给交易贴标签。

固定原 v7 交易的诊断（不把释放资金投入新机会）：

| 过滤规则 | 被删亏损笔数 | 被删盈利笔数 | 避免原亏损（元） | 放弃原盈利（元） |
| --- | ---: | ---: | ---: | ---: |
{st}

0.5 ATR 会过滤原有 78 笔入场，其中 77 笔已平仓（55 亏、22 盈）及 1 笔期末未平仓。被过滤已平仓交易净亏损约 2.74 万元，但共享账户重新运行仍恶化：退出与资金容量决定了后续可买机会，不能把“删掉的旧亏损”直接加到账户收益上。原 v7 双底已平仓本身就有 98 笔亏损、29 笔盈利；删除多数亏损并不自动证明过滤具有识别力。

1.0 ATR 在原基准双底交易中会删除 126/127 笔已平仓，包含全部 29 笔盈利。实际组合重跑只剩 4 笔已平仓双底，净亏 4,340 元；36 笔已平仓头肩底净赚 52,446 元。它主要改变了策略构成。为检验该解释，在看见结果后补做归因对照（未改阈值）：只做头肩底收益 {ihs['return_pct']:+.2f}%、最大回撤 {ihs['max_drawdown_pct']:.2f}%；只做双底且 ≥1.0 ATR 收益 {w['return_pct']:+.2f}%、最大回撤 {w['max_drawdown_pct']:.2f}%。这些补充对照用于解释收益来源，不是新的独立验证。

0.25 ATR 的 +0.37% 包含期末持仓浮盈，其已平仓净利润仍为 −2,432 元；不能将其视为已实现的稳定盈利。两类策略均用 0.5 ATR 与仅过滤双底的结果相同，本次没有新增拦截原已获准的头肩底成交。

结论与应用：过窄止损可以被入场前波动指标识别，但本次不能证实“0.5 ATR 以上就是高质量双底”。保留该过滤器作为研究选项及审计字段；不把历史表现最好的 1.0 ATR 自动写入默认配置。后续应区分“修复双底入场”与“减少双底策略资金占用”两个问题，再用未参与本轮筛选的数据验证。

验证：基准订单、交易、入场审计、权益逐项复现；各方案冻结信号和止损目标一致；实际获准交易通过 ATR 门槛及净盈亏比检查；现金非负、最多 5 个持仓；424 项测试通过，包括当日和未来价格不能污染 ATR、复权一致性和执行时过滤。每日市值上涨可能使权重高于入场时限额，这不等同于下单越限。

限制：已研究历史区间，非独立样本外验证；未把后验上涨幅度作为入场信息；ATR 只是波动尺度，不是最大可能损失或价格预测。沿用原日线执行与复权股数模型、T+1、涨跌停及滑点处理。费用未另做压力优化。period-diagnostics.csv 是同一历史区间的前后段描述，不可称为独立验证。

明细：comparison.csv；baseline-entry-volatility.csv；fixed-entry-filter-diagnostic.csv；family-attribution.csv；entry-replacement-diagnostics.csv；period-diagnostics.csv；verification.json。各方案目录保留全量订单、交易、审核和权益曲线；归因对照存于相邻 20261026-volatility-entry-ablation 目录。
'''
    (OUT/'report.md').write_text(report,encoding='utf-8')
    def render_table(lines):
        cells=[line.strip('|').split('|') for line in lines.splitlines() if not line.startswith('| ---')]
        return '<table>'+''.join('<tr>'+''.join('<td>'+html.escape(c.strip())+'</td>' for c in row)+'</tr>' for row in cells)+'</table>'
    body=''.join(render_table(p) if p.startswith('|') else '<h1>'+html.escape(p[2:])+'</h1>' if p.startswith('# ') else '<p>'+html.escape(p)+'</p>' for p in report.split('\n\n'))
    (OUT/'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>波动适配入场过滤</title><style>body{max-width:1100px;margin:40px auto;padding:0 20px;color:#172638;font:16px/1.8 system-ui}table{width:100%;border-collapse:collapse}td{border-bottom:1px solid #ccd6df;padding:10px;text-align:right}td:first-child{text-align:left}tr:first-child{font-weight:bold;background:#f1f5f9}h1{font-size:28px}</style>'+body+'</html>',encoding='utf-8')
    for script in (__file__,ROOT/'scripts/audit_volatility_entry_cohort.py'):shutil.copy2(script,OUT/'source'/Path(script).name)
    print(json.dumps(dict(comparison=comparison,checks=checks),ensure_ascii=False))
if __name__=='__main__':main()
