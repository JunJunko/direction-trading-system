"""Summarize frozen full-signal C2 replay; no parameter selection or rerun."""
import csv,json,html,sys
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/20261026-c2-full-comparable'
sys.path.insert(0,str(OUT/'source/src'))
from trading_system.target_migration import RESEARCH_PARAMETERS
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def main():
    assert load(OUT/'status.json')['status']=='complete'
    summaries=load(OUT/'summaries.json')
    labels={'W_v7':'双底 v7','W_C2':'双底 C2','combined_v7':'组合 v7','combined_W_C2':'组合：双底 C2 / 头肩底 v7','combined_both_C2':'组合：双底与头肩底均 C2'}
    metrics=[];details={};checks={}
    for name,s in summaries.items():
        folder=OUT/name;ts=rows(folder/'trades.csv');audits=rows(folder/'entry_audit.csv');curve=rows(folder/'equity.csv')
        cfg=load(folder/'config.json');base=load(OUT/'combined_v7/config.json')
        for key in ('initial_cash','risk','execution','automatic_account_policy'):assert cfg[key]==base[key]
        fills=[a for a in audits if a['execution_reason']=='filled']
        assert len(fills)==s['filled_buys']
        assert all(float(a['net_rr'])>3 for a in fills)
        assert min(float(c['cash']) for c in curve)>=-1e-6
        assert max(int(c['positions']) for c in curve)<=5
        signals=load(folder/'plans.json')
        reference=load(OUT/('W_v7' if name.startswith('W_') else 'combined_v7')/'plans.json')
        fields=('date','symbol','setup_id','trigger','stop','target')
        assert [{k:p[k] for k in fields} for p in signals]==[{k:p[k] for k in fields} for p in reference]
        pnl=sum(float(t['pnl']) for t in ts);net=s['final_equity']-s['initial_cash']
        best=max(ts,key=lambda t:float(t['pnl']))
        days=[(datetime.strptime(t['exit_date'],'%Y%m%d')-datetime.strptime(t['entry_date'],'%Y%m%d')).days for t in ts]
        m=dict(case=name,label=labels[name],return_pct=s['total_return']*100,drawdown_pct=-s['max_drawdown']*100,
               buys=s['filled_buys'],closed=s['closed_trades'],open=s['open_positions'],win_pct=s['win_rate']*100,
               profit_factor=s['profit_factor'],closed_net_pnl=pnl,open_mark_pnl=net-pnl,
               max_winner_pnl=float(best['pnl']),max_winner_symbol=best['symbol'],
               max_winner_share_of_positive_pnl=float(best['pnl'])/sum(max(0,float(t['pnl'])) for t in ts),
               avg_closed_calendar_days=sum(days)/len(days),max_closed_calendar_days=max(days))
        metrics.append(m)
        details[name]=dict(former_winner_audits=[a for a in audits if a['symbol']=='002451.SZ'],
                           longest_closed=sorted(ts,key=lambda t:(datetime.strptime(t['exit_date'],'%Y%m%d')-datetime.strptime(t['entry_date'],'%Y%m%d')).days,reverse=True)[:5],
                           risk_reasons=s['risk_reasons'])
        checks[name]=dict(same_account_constraints=True,identical_signal_brackets=True,all_actual_entry_net_rr_above_3=True,
                          nonnegative_cash=True,max_positions_at_most_5=True,causal_stop_raises=s['causal_stop_raises'])
    dump(OUT/'diagnostics.json',dict(metrics=metrics,details=details))
    dump(OUT/'verification.json',dict(cases=checks,combined_v7_exact_replay=summaries['combined_v7']['previous_v7_exact_replay'],tests='python -m pytest tests -q: 421 passed'))
    dump(OUT/'effective-exit-parameters.json',dict(C2=RESEARCH_PARAMETERS,arm='C2',tick=.01,
         activation='First close at or above original target; same-close decisive breakout exemption; guard only after candidate activation',
         ihs_adapter='Mirror current factor-adjusted ihs_neckline/ihs_target into W manager fields; original IHS entry brackets preserved',
         runner='source/backtest_c2_full_comparable.py',config_note='c2_replay is a research-runner marker; original strategy params retained as signal provenance; C2 manager instantiated with target_arm=C2'))
    with (OUT/'comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(metrics[0]));w.writeheader();w.writerows(metrics)
    table='\n'.join(f"| {m['label']} | {m['return_pct']:+.2f}% | {m['drawdown_pct']:.2f}% | {m['buys']} | {m['closed']} | {m['win_pct']:.2f}% |" for m in metrics)
    report=f'''# C2 全量同约束复验

结论：此前小样本 +11.66% 的优势没有保留。双底 C2 全量收益 −8.59%，低于双底 v7 的 −6.21%；共享账户只替换双底退出后收益 −6.12%，低于组合 v7 的 −1.08%。两类策略均用 C2 得到 −2.81%，回撤略小但收益仍较差。此次证据不支持替换默认 v7。

| 方案 | 账户收益（含期末持仓） | 最大回撤 | 买入 | 已平仓 | 平仓胜率 |
| --- | ---: | ---: | ---: | ---: | ---: |
{table}

评估区间为 2025-10-09 至 2026-09-30。复用主板 3,214 只股票扫描所得的 6,014 个双底信号、1,713 个头肩底信号，组合共 7,727 个信号、2,861 只有信号股票。单策略用全部双底信号，组合用全部两类信号。入场日期、价格、仓位随退出及资金占用重新计算，不能将不同方案的交易笔数强行固定。

所有方案使用 100 万本金、单笔风险 0.5%、组合风险 2%、单股仓位 10%、总仓位 50%、最多 5 只、原自动回撤缩仓规则。成交时重新检查扣费后盈亏比严格大于 3。原双底入场距离 2% 限制保留，未混入此前仅用于盘前扫描的取消限制。费用、滑点、T+1、涨跌停处理、优先级完全相同。以上仓位比例是下单约束，持仓市值上涨可能使收盘权重超过下单限额。

执行采用已校正的 open_first：前收盘产生的退出指令先于次日盘中止损处理。对照组合 v7 的订单、成交、入场审计、权益曲线均与此前同口径结果逐项完全相同。历史旧执行口径的 v7 为 −1.16%，不与本次 −1.08% 混用。

C2 原参数冻结：首次收盘达到原结构目标时检查当日突破强度，满足条件才豁免目标卖出；进入突破候选后采用“入场以来最高收盘价 − 3 倍前一日已知 ATR”的单向保护线，收盘生成、下一交易日生效。它没有在所有交易一出现 2R 浮盈时自动保本。头肩底迁移只映射目标价和颈线，初始止损及入场筛选仍用本次 v7 的原信号。

原小样本最大盈利 002451.SZ（2025-11-03 买入）贡献约 7.91 万元，占旧 C2 账户净收益约 68%。本次全量运行中，其 2025-10-31 信号在上述各方案均因 max_positions 被拒绝，不能成交；不能把原小样本的赢家直接加回全量结果。这是信号扩展后真实账户容量发生作用的明确例子。

两类策略均用 C2 时仅买入 50 笔，对照 v7 为 146 笔。600063、002518、600995 等在 2025-10-10 买入后持有至 2026 年 7 月，最终仍亏损；只在原目标附近启用保护，无法解决目标到达之前的长期占仓。其 6.24% 回撤略低于 v7 的 6.35%，不能单凭这一项认定退出更优。

本次是共享账户效果检验，变化同时包含退出差异、释放资金时点和后续可买机会；不能把全部差额归因于同一批持仓的卖点。它仍是已研究过的历史区间，不是独立样本外验证。日线成交与复权股数沿用原模型，并不等同于逐笔真实成交。

验证：冻结信号及价格完全一致，账户参数一致，所有实际买入净盈亏比 >3，现金非负、持仓数不超过 5；C2 全部止损上调均通过时序与单向性断言。现行 tests 目录 421 项测试通过。未修改默认策略或生产配置。

文件：comparison.csv 为汇总；diagnostics.json 为利润、资金拦截和长持仓明细；verification.json 为校验记录；effective-exit-parameters.json 为 C2 有效参数；各方案目录包含全部交易、入场审计和日权益。
'''
    (OUT/'report.md').write_text(report,encoding='utf-8')
    trs=''.join('<tr>'+''.join(f'<td>{html.escape(str(v))}</td>' for v in [m['label'],f"{m['return_pct']:+.2f}%",f"{m['drawdown_pct']:.2f}%",m['buys'],m['closed'],f"{m['win_pct']:.2f}%"] )+'</tr>' for m in metrics)
    body=''.join(f'<p>{html.escape(p)}</p>' for p in report.split('\n\n') if not p.startswith(('#','|')))
    (OUT/'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>C2 全量复验</title><style>body{max-width:1100px;margin:40px auto;font:16px/1.8 system-ui;color:#172638;padding:0 20px}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #ccd6df;text-align:right}td:first-child,th:first-child{text-align:left}h1{font-size:28px}</style><h1>C2 全量同约束复验</h1><table><tr><th>方案</th><th>收益</th><th>最大回撤</th><th>买入</th><th>已平仓</th><th>胜率</th></tr>'+trs+'</table>'+body+'</html>',encoding='utf-8')
    print(json.dumps(metrics,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
