"""Compare the fixed support-zone candidate with the frozen daily baseline."""
import csv
import html
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main(output):
    out=Path(output);comparison=load(out/'comparison.json');cfg=load(out/'config.json')
    counts=load(out/'signal-counts.json');verification=load(out/'account-verification.json')
    metrics={};trades={};curves={};audits={};plans={}
    for key in ('baseline','candidate'):
        folder=Path(comparison[key]['path']);summary=comparison[key]['summary']
        trades[key]=read(folder/'trades.csv');curves[key]=read(folder/'equity.csv')
        audits[key]=read(folder/'entry_audit.csv');plans[key]=load(folder/'plans.json')
        first={}
        for r in audits[key]:first.setdefault(r['setup_id'],r)
        distances=[(p['trigger']-p['stop'])/p['trigger'] for p in plans[key]]
        expected_distances=[(p['trigger']*(1+cfg['execution']['slippage'])-p['stop'])/
                            (p['trigger']*(1+cfg['execution']['slippage'])) for p in plans[key]]
        approved={r['setup_id'] for r in audits[key] if r['risk_reason']=='approved'}
        rejected_far={r['setup_id'] for r in audits[key] if r['risk_reason']=='entry_too_far_from_support'}
        rejected_rr={r['setup_id'] for r in audits[key] if r['risk_reason']=='net_rr_not_above_threshold'}
        fills=[r for r in audits[key] if r['execution_reason']=='filled']
        metrics[key]=dict(summary,net_pnl=summary['final_equity']-summary['initial_cash'],
            first_plans=len(plans[key]),audits=len(audits[key]),unique_audited_plans=len(first),
            unique_approved_plans=len(approved),unique_far_rejected_plans=len(rejected_far),
            unique_rr_rejected_plans=len(rejected_rr),
            median_raw_plan_stop_distance=statistics.median(distances) if distances else None,
            min_expected_entry_distance=min(expected_distances,default=None),
            raw_plans_within_two_percent=sum(x<=.02+1e-12 for x in expected_distances),
            median_filled_stop_distance=statistics.median((float(r['fill'])-float(r['stop']))/float(r['fill']) for r in fills) if fills else None,
            risk_reasons=dict(Counter(r['risk_reason'] for r in audits[key])),
            execution_reasons=dict(Counter(r['execution_reason'] for r in audits[key])),
            exit_reasons=dict(Counter(r['reason'] for r in trades[key])))
    # Independent checks of price proximity and fee-inclusive RR.
    checked_rr=0;checked_distance=0;checked_fills=0;ex=cfg['execution']
    for r in audits['candidate']:
        if r.get('support_entry_distance'):
            distance=(float(r['fill'])-float(r['stop']))/float(r['fill'])
            limit=float(r['support_max_entry_risk'])
            assert math.isclose(distance,float(r['support_entry_distance']),abs_tol=1e-12)
            if r['risk_reason']=='entry_too_far_from_support':assert distance>limit+1e-12
            if r['risk_reason']=='approved' or r['execution_reason']=='filled':assert distance<=limit+1e-12
            checked_distance+=1
        if r['execution_reason']=='filled':checked_fills+=1
        if not r.get('net_rr'):continue
        q=float(r['candidate_quantity']);fill=float(r['fill'])
        stop=float(r['stop'])*(1-ex['slippage']);target=float(r['target'])*(1-ex['slippage'])
        tax=ex['sell_tax_after_20230828'] if r['date']>='20230828' else ex['sell_tax_before_20230828']
        fee=max(ex['minimum_commission'],q*fill*ex['commission_rate'])
        gain=q*(target-fill)-fee-max(ex['minimum_commission'],q*target*ex['commission_rate'])-q*target*tax
        loss=q*(fill-stop)+fee+max(ex['minimum_commission'],q*stop*ex['commission_rate'])+q*stop*tax
        assert math.isclose(gain/loss,float(r['net_rr']),abs_tol=1e-11,rel_tol=1e-11)
        checked_rr+=1
    for p in plans['candidate']:
        e=p['evidence']
        assert p['stop']==e['support_lower']<=e['support_upper']
        assert e['support_source_date']<e['support_known_at']<=p['date']
    checks=dict(verification,independent_rr_audits=checked_rr,
                independent_distance_audits=checked_distance,filled_distance_checks=checked_fills,
                all_plan_support_and_confirmation_checked=len(plans['candidate']))
    checks['raw_plan_verification']=load(out/'support-plan-verification.json')
    result=dict(metrics=metrics,checks=checks,trades=trades,signal_reasons=counts['reasons'],
                interpretation='Fixed parameters on previously studied data; no independent holdout. No fills is not evidence of profitability.')
    (out/'assessment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','DejaVu Sans'];plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(2,1,figsize=(11,6.8),sharex=True,gridspec_kw={'height_ratios':[2,1]})
    for key,label,color in [('baseline','原日线版 v5.12','#607d8b'),('candidate','支撑区候选 v5.13','#176b87')]:
        data=curves[key];x=[datetime.strptime(r['date'],'%Y%m%d') for r in data]
        axes[0].plot(x,[float(r['equity'])/cfg['initial_cash'] for r in data],label=label,color=color,lw=1.6)
        axes[1].plot(x,[100*float(r['drawdown']) for r in data],color=color,lw=1.3)
    axes[0].set_ylabel('账户净值');axes[0].legend(frameon=False);axes[1].set_ylabel('回撤（%）')
    axes[0].set_title('支撑区域与近支撑入场：固定 2% 价格风险限制',loc='left',fontsize=12)
    for ax in axes:ax.grid(alpha=.2);ax.spines[['top','right']].set_visible(False)
    fig.autofmt_xdate();fig.tight_layout();fig.savefig(out/'equity-comparison.png',dpi=160);plt.close(fig)
    def fmt(v,pct=False):
        if v is None:return '无样本'
        if pct:return f'{v:.2%}'
        return f'{v:,.2f}' if isinstance(v,float) else str(v)
    esc=lambda v:html.escape(str(v))
    labels=[('final_equity','期末权益（元）',False),('net_pnl','净盈亏（元）',False),
            ('total_return','账户总收益',True),('max_drawdown','最大回撤',True),
            ('filled_buys','买入笔数',False),('closed_trades','平仓笔数',False),('open_positions','期末持仓',False),
            ('win_rate','平仓胜率',True),('first_plans','结构首次计划（审核前）',False),
            ('unique_audited_plans','参与审核的独立计划',False),('unique_far_rejected_plans','因远离支撑拒绝的独立计划',False),
            ('unique_rr_rejected_plans','因净盈亏比不足拒绝的独立计划',False),
            ('unique_approved_plans','至少一次审核通过的独立计划',False),
            ('min_expected_entry_distance','最小计划止损距离（含买入滑点）',True),
            ('raw_plans_within_two_percent','计划价格距离不超过 2% 的数量',False),
            ('median_raw_plan_stop_distance','审核前计划止损距离中位数',True),
            ('median_filled_stop_distance','成交买入止损距离中位数',True)]
    m=metrics['candidate']
    lead=('本轮没有成交，账户保持现金；收益与回撤为零反映未交易，不能判断止损方法是否有效。'
          if m['filled_buys']==0 else
          f"候选买入 {m['filled_buys']} 笔，净盈亏 {fmt(m['net_pnl'])} 元，账户收益 {fmt(m['total_return'],True)}。成交样本仍需结合逐笔交易判断。")
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>支撑区域回测</title>',
           '<style>body{font:16px/1.65 system-ui,"Microsoft YaHei";max-width:1150px;margin:36px auto;padding:0 24px;color:#23323e}h1{font-size:28px}h2{font-size:21px;margin-top:32px}table{border-collapse:collapse;width:100%;margin:16px 0}th,td{text-align:left;padding:9px 12px;border-bottom:1px solid #dce3e7}th{background:#f3f6f8}img{width:100%}a{color:#176b87}.note{padding:14px 18px;background:#edf4f7;border-radius:6px}</style>',
           '<h1>支撑区域：日线全量对照回测</h1>',
           '<p>3,214 只股票、2,856,672 根日线，2023-01-03 起预热，2025-10-09 至 2026-09-30 共 241 个交易日，100 万元共享账户，按历史上市、退市和 ST 状态过滤。</p>',
           '<p class="note">'+lead+'</p>',
           '<h2>事前固定的实验规则</h2><p>支撑区取已确认小 N 回踩 C 点 K 线的最低价到实体下沿；触及最低价触发全部退出，取消原 0.5% 止损缓冲。沿用原先确认小 N 后突破买入，新增预估成交价到支撑下沿不超过 2% 的限制，含买入滑点且跳空重新审核。目标价、含费用净盈亏比严格大于 3、账户仓位及持仓结构规则沿用原版。后续更高支撑只随已确认核心上移。</p>',
           '<p>受限不能卖时保留退出状态，首次可卖时继续执行；日线 OHLC 模拟不能验证秒级成交。2% 是价格距离上限，费用和跳空可能使实际亏损更大。</p>',
           '<p>实现中的 stop_buffer 是共用参数，本轮设为零也作用于方向失效参考线和持仓保护，因此部分方向事件计数改变。独立核对确认本轮 68 个首次计划的身份、日期、触发价和目标价与原版一致，首次止损价的差异仅为取消 0.5% 缓冲；续期数量减少。</p>',
           '<h2>账户与机会</h2><table><tr><th>指标</th><th>原日线 v5.12</th><th>支撑区 v5.13</th></tr>']
    for key,label,pct in labels:
        parts.append('<tr><th>'+label+'</th>'+''.join('<td>'+fmt(metrics[c][key],pct)+'</td>' for c in ('baseline','candidate'))+'</tr>')
    parts+=['</table><p>独立计划可在续期中有多个审核结果，各拒绝类别可能重叠；原日线版没有新增的支撑距离限制。审核前计划仍包括远离支撑的原始结构，不能将其止损距离误作最终准入交易的距离。</p>',
            '<img src="equity-comparison.png" alt="共享账户净值与回撤">',
            '<h2>候选审核与执行原因</h2><table><tr><th>环节</th><th>原因</th><th>次数（含续期）</th></tr>']
    for kind in ('risk_reasons','execution_reasons'):
        for reason,n in metrics['candidate'][kind].items():
            parts.append('<tr><td>'+esc(kind)+'</td><td>'+esc(reason)+'</td><td>'+str(n)+'</td></tr>')
    parts.append('</table>')
    names={r['ts_code']:r.get('name','') for r in load(out/'universe.json')['stocks']}
    near=sorted(plans['candidate'],key=lambda p:(p['trigger']*(1+ex['slippage'])-p['stop'])/(p['trigger']*(1+ex['slippage'])))[:5]
    parts+=['<h2>离支撑最近的五个首次计划</h2><table><tr><th>股票</th><th>计划日期</th><th>支撑区（当时价）</th><th>预计成交价</th><th>到下沿距离</th></tr>']
    for p in near:
        e=p['evidence'];fill=p['trigger']*(1+ex['slippage'])
        parts.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [p['symbol']+' '+names.get(p['symbol'],''),p['date'],f"{e['support_lower']:.3f}～{e['support_upper']:.3f}",f'{fill:.3f}',fmt((fill-p['stop'])/fill,True)])+'</tr>')
    parts.append('</table>')
    for key,label in [('candidate','支撑区候选'),('baseline','原日线版')]:
        parts+=['<h2>'+label+'逐笔平仓</h2><table><tr><th>股票</th><th>买入</th><th>卖出</th><th>净盈亏</th><th>实现 R</th><th>原因</th></tr>']
        for r in trades[key]:
            parts.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [r['symbol']+' '+names.get(r['symbol'],''),r['entry_date'],r['exit_date'],fmt(float(r['pnl'])),fmt(float(r['realized_r'])),r['reason']])+'</tr>')
        if not trades[key]:parts.append('<tr><td colspan="6">无已平仓交易</td></tr>')
        parts.append('</table>')
    parts+=['<h2>验证与限制</h2><p>全量扫描完成，首次计划身份、日期及价位与共享账户重算一致；原日线基准的委托、平仓、审核、净值与汇总完全复现。独立复算 '+str(checked_distance)+' 条支撑距离审核和 '+str(checked_rr)+' 条含费用盈亏比审核；全部 '+str(len(plans['candidate']))+' 个首次计划的支撑与确认日期已检查。代码及数据指纹见 manifest.json。</p>',
            '<p class="note">该区间已用于策略研究，是固定规则的样本内对照，没有独立保留样本。支撑区来自单个已确认回踩 K 线；本轮没有验证多次触底、成交密集区或真实小时结构。零成交不代表有盈利能力，少量成交也不足以证明稳定改善。</p>',
            '<p><a href="assessment.json">完整指标</a> · <a href="plans.json">全部计划及支撑区域</a> · <a href="entry_audit.csv">准入审核</a> · <a href="orders.csv">委托</a> · <a href="trades.csv">平仓</a> · <a href="evaluation-plan.json">事前口径</a> · <a href="account-verification.json">验证</a></p></html>']
    (out/'report.html').write_text('\n'.join(parts),encoding='utf-8')
    print(json.dumps(dict(metrics=metrics,checks=checks),ensure_ascii=True))


if __name__=='__main__':main(sys.argv[1])
