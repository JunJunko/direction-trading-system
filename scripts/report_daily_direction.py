"""Summarize the completed all-stock daily/weekly comparison from saved artifacts."""
import csv
import html
import json
import statistics
import sys
from collections import Counter
from pathlib import Path


def read(path):
    with path.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def main(output):
    out=Path(output)
    comparison=json.loads((out/'comparison.json').read_text(encoding='utf-8'))
    counts=json.loads((out/'signal-counts.json').read_text(encoding='utf-8'))
    verification=json.loads((out/'account-verification.json').read_text(encoding='utf-8'))
    universe=json.loads((out/'universe.json').read_text(encoding='utf-8'))
    names={r['ts_code']:r.get('name','') for r in universe['stocks']}
    metrics={};trades={};curves={};audits={}
    for cycle in ('weekly','daily'):
        directory=Path(comparison[cycle]['path']);summary=comparison[cycle]['summary']
        trades[cycle]=read(directory/'trades.csv');curves[cycle]=read(directory/'equity.csv')
        audits[cycle]=read(directory/'entry_audit.csv')
        orders=read(directory/'orders.csv')
        pnl=[float(r['pnl']) for r in trades[cycle]];rs=[float(r['realized_r']) for r in trades[cycle]]
        profits=[x for x in pnl if x>0];losses=[x for x in pnl if x<0]
        metrics[cycle]=dict(summary,net_pnl=summary['final_equity']-summary['initial_cash'],
            realized_pnl=sum(pnl),unrealized_pnl=summary['final_equity']-summary['initial_cash']-sum(pnl),
            average_win=statistics.mean(profits) if profits else None,
            average_loss=statistics.mean(losses) if losses else None,
            best_r=max(rs,default=None),worst_r=min(rs,default=None),average_r=statistics.mean(rs) if rs else None,
            total_fees=sum(float(r.get('fee') or 0) for r in orders if r['status']=='filled'),
            max_gross_weight=max(float(r['gross_weight']) for r in curves[cycle]),
            audit_reasons=dict(Counter(r.get('risk_reason') or r.get('execution_reason') for r in audits[cycle])),
            net_rr_above_3_audits=sum(bool(r.get('net_rr')) and float(r['net_rr'])>3 for r in audits[cycle]),
            closed_wins=len(profits),closed_losses=len(losses),exit_reasons=dict(Counter(r['reason'] for r in trades[cycle])))
    # Independent fee-inclusive planned RR verification for every recorded audit.
    config=json.loads((out/'config.json').read_text(encoding='utf-8'));ex=config['execution'];checked=0
    import math
    for r in audits['daily']:
        if not r.get('net_rr'):continue
        q=float(r['candidate_quantity']);fill=float(r['fill']);stop=float(r['stop'])*(1-ex['slippage']);target=float(r['target'])*(1-ex['slippage'])
        tax=ex['sell_tax_after_20230828'] if r['date']>='20230828' else ex['sell_tax_before_20230828']
        fee=max(ex['minimum_commission'],q*fill*ex['commission_rate'])
        gain=q*(target-fill)-fee-max(ex['minimum_commission'],q*target*ex['commission_rate'])-q*target*tax
        loss=q*(fill-stop)+fee+max(ex['minimum_commission'],q*stop*ex['commission_rate'])+q*stop*tax
        assert math.isclose(gain/loss,float(r['net_rr']),rel_tol=1e-11,abs_tol=1e-11)
        checked+=1
    detail=dict(metrics=metrics,verification=verification,independently_verified_rr_audits=checked,
        signal_reasons=counts['reasons'],trades=trades)
    (out/'assessment.json').write_text(json.dumps(detail,ensure_ascii=False,indent=2),encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from datetime import datetime
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','DejaVu Sans'];plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(2,1,figsize=(11,6.8),sharex=True,gridspec_kw={'height_ratios':[2,1]})
    for cycle,label,color in [('weekly','周线双底','#607d8b'),('daily','日线双底','#176b87')]:
        data=curves[cycle];x=[datetime.strptime(r['date'],'%Y%m%d') for r in data]
        axes[0].plot(x,[float(r['equity'])/config['initial_cash'] for r in data],label=label,color=color,lw=1.6)
        axes[1].plot(x,[100*float(r['drawdown']) for r in data],label=label,color=color,lw=1.3)
    axes[0].set_ylabel('账户净值');axes[0].legend(frameon=False);axes[1].set_ylabel('回撤（%）')
    axes[0].set_title('主板非ST共享账户：方向周期对照（2025-10-09—2026-09-30）',loc='left',fontsize=12)
    for ax in axes:ax.grid(alpha=.2);ax.spines[['top','right']].set_visible(False)
    fig.autofmt_xdate();fig.tight_layout();fig.savefig(out/'equity-comparison.png',dpi=160);plt.close(fig)
    def fmt(value,kind='number'):
        if value is None:return '无样本'
        if kind=='percent':return f'{value:.2%}'
        return f'{value:,.2f}' if isinstance(value,float) else str(value)
    esc=lambda x:html.escape(str(x))
    labels=[('final_equity','期末权益（元）','number'),('net_pnl','净盈亏（元）','number'),
        ('total_return','账户总收益','percent'),('max_drawdown','最大回撤','percent'),
        ('filled_buys','买入笔数','number'),('closed_trades','已平仓笔数','number'),('open_positions','期末持仓数','number'),
        ('win_rate','平仓胜率','percent'),('profit_factor','利润因子','number'),
        ('realized_pnl','已实现净盈亏（元）','number'),('unrealized_pnl','期末浮盈亏（元）','number'),
        ('average_r','平仓平均R','number'),('best_r','最佳单笔R','number'),('worst_r','最差单笔R','number'),
        ('max_gross_weight','最大总仓位','percent'),('total_fees','已成交佣金及税费（元，滑点另含于成交价）','number')]
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>日线与周线双底全量回测</title>',
        '<style>body{font:16px/1.65 system-ui,"Microsoft YaHei";max-width:1150px;margin:36px auto;padding:0 24px;color:#23323e}h1{font-size:28px}h2{font-size:21px;margin-top:34px}table{border-collapse:collapse;width:100%;margin:16px 0}th,td{text-align:left;padding:9px 12px;border-bottom:1px solid #dce3e7}th{background:#f3f6f8}img{width:100%;height:auto}code{background:#f0f3f5;padding:2px 5px}a{color:#176b87}.note{padding:14px 18px;background:#edf4f7;border-radius:6px}</style>',
        '<h1>日线与周线双底：主板全量回测</h1>',
        '<p>3,214只历史主板候选股票，2,856,672根日K；2023-01-03起因果预热，2025-10-09空仓开始考核，至2026-09-30，共241个交易日。100万元共享账户，按信号日与执行日的上市、退市、ST资格过滤。</p>',
        '<p>日线版仅将双底、突破、反抽及方向失效的周期改为日线。后续核心波段仍为日线，入场使用日线嵌套小结构代理。所有数值参数、费用、风控和持仓规则保持一致。</p>',
        '<p class="note">本次日线版净盈亏 '+fmt(metrics['daily']['net_pnl'])+' 元，账户收益 '+fmt(metrics['daily']['total_return'],'percent')+'，最大回撤 '+fmt(abs(metrics['daily']['max_drawdown']),'percent')+'，仅成交 '+str(metrics['daily']['filled_buys'])+' 笔买入。两组交易集合不同，成交样本不足以判断稳定改善。</p>',
        '<h2>账户表现</h2><table><tr><th>指标</th><th>周线版 v5.11.2</th><th>日线方向版 v5.12</th></tr>']
    for key,label,kind in labels:
        parts.append('<tr><th>'+label+'</th>'+''.join('<td>'+fmt(metrics[c][key],kind)+'</td>' for c in ('weekly','daily'))+'</tr>')
    parts+=['</table><img src="equity-comparison.png" alt="两个共享账户的净值与回撤曲线">',
        '<h2>信号到成交</h2><table><tr><th>事件</th><th>周线版</th><th>日线版</th></tr>']
    funnel=[('reversal_candidate','双底候选'),('layout_confirmed','确认双底布局'),('upper_direction_confirmed','新方向确认'),
        ('wave_core_accepted','接受日线核心'),('entry_intent','首次入场计划'),('plan_rejected','计划审核拒绝'),('plan_approved','计划审核通过'),('filled','买入成交事件')]
    for event,label in funnel:
        values=[]
        for cycle,prefix in [('weekly','weekly_'),('daily','daily_')]:
            key=prefix+event if event in ('reversal_candidate','layout_confirmed') else event
            values.append(metrics[cycle]['event_counts'].get(key,0))
        parts.append('<tr><th>'+label+'</th>'+''.join('<td>'+str(v)+'</td>' for v in values)+'</tr>')
    parts+=['</table><p>事件可能属于同一结构的不同观察时点，不能把事件数量直接当成独立交易数。计划续期审核与首次入场计划分开计数。</p>',
        '<h2>日线版等待与拒绝原因</h2><table><tr><th>事件</th><th>原因</th><th>次数</th></tr>']
    for r in counts['reasons'][:25]:
        parts.append('<tr><td>'+esc(r['event'])+'</td><td>'+esc(r['reason'])+'</td><td>'+str(r['count'])+'</td></tr>')
    parts+=['</table><p>入场审核原因：'+esc(json.dumps(metrics['daily']['audit_reasons'],ensure_ascii=False))+'</p>']
    for cycle,title in [('daily','日线版'),('weekly','周线版')]:
        parts+=['<h2>'+title+'逐笔平仓交易</h2><table><tr><th>股票</th><th>买入</th><th>卖出</th><th>净盈亏（元）</th><th>实现R</th><th>退出原因</th></tr>']
        for r in trades[cycle]:
            parts.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [r['symbol']+' '+names.get(r['symbol'],''),r['entry_date'],r['exit_date'],fmt(float(r['pnl'])),fmt(float(r['realized_r'])),r['reason']])+'</tr>')
        parts.append('</table>')
    parts+=['<h2>验证与适用范围</h2><p>全部3,214只股票已参与信号扫描。所有产生评估期入场计划的股票重新进入原始共享账户引擎，首次计划身份、日期、价位逐项一致；周线投影账户的全部委托、逐笔交易、入场审核、241天净值和汇总与原全量基准一致。全量信号逐股保存在压缩事件文件中；decisions.csv记录产生入场计划股票的决策及账户事件。</p>',
        '<p>本次有'+str(checked)+'条日线入场审核完成独立含费用净盈亏比复核。费用包含佣金、最低5元佣金、卖出印花税、双边滑点；涨跌停、停牌和T+1继续按原引擎处理。</p>',
        '<p class="note">该历史区间已用于策略研究，本次为固定参数的样本内对照；没有独立留出样本验证。日线内部结构代理不能代表真实小时入场；日线OHLC使用保守成交约定，复权采用合成总收益调整。收益差异只能描述本次样本，不能说明未来表现。</p>',
        '<p><a href="assessment.json">完整指标与交易</a> · <a href="plans.json">全部首次入场计划</a> · <a href="entry_audit.csv">入场审核</a> · <a href="orders.csv">委托</a> · <a href="trades.csv">成交</a> · <a href="evaluation-plan.json">事前口径</a> · <a href="account-verification.json">账户验证</a></p></html>']
    (out/'report.html').write_text('\n'.join(parts),encoding='utf-8')
    print(json.dumps({c:{k:metrics[c][k] for k in ('final_equity','total_return','max_drawdown','filled_buys','closed_trades','open_positions','win_rate','net_pnl')} for c in metrics},ensure_ascii=True))


if __name__=='__main__':main(sys.argv[1])
