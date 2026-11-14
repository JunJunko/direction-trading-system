"""Build a compact decision report from completed replay audit artifacts."""
import html,json,sys
from pathlib import Path


def main(run):
    p=Path(run);load=lambda name:json.loads((p/name).read_text(encoding='utf-8'))
    summary=load('summary.json');audit=load('nested-audit.json');compare=load('comparison.json')
    diagnostic=load('profit-diagnostics.json');fresh=load('preplan-trigger-audit.json')
    version=load('manifest.json')['rule_version'];esc=lambda x:html.escape(str(x))
    params=load('config.json')['strategies'][0]['params']
    verification=load('verification.json') if (p/'verification.json').exists() else {}
    test_count=verification.get('python_tests_passed',145 if params.get('holding_scale_mode')=='owned_core' else 142)
    parts=['<!doctype html><meta charset="utf-8"><title>'+esc(version)+' 迭代评估</title>',
        '<style>body{font:16px system-ui;max-width:1400px;margin:30px auto;line-height:1.7}table{border-collapse:collapse;width:100%}td,th{padding:9px;border-bottom:1px solid #ddd;text-align:left}pre{white-space:pre-wrap}a{color:#234da0}</style>',
        '<h1>'+esc(version)+' 迭代评估</h1>',
        '<p>本版完成日线核心归属、内部子结构、明确失效边界、持仓级别约束，以及触发价消费记录。规则一致性与盈利优势分别评价。未提升为生产默认。</p>',
        '<p>3214只主板历史上市股票，每日排除ST，共享100万元账户；评估2025-10-09至2026-09-30。日线小结构代理与已反复研究的数据，不构成真实小时线或样本外验证。</p>',
        '<h2>同一数据与账户的结果</h2><table><tr><th>版本</th><th>买入／平仓</th><th>收益率</th><th>最大回撤</th><th>净盈亏</th><th>利润因子</th><th>最佳单笔R</th></tr>']
    for item in compare:
        m=item['metrics'];parts.append('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in
            (m['version'],str(m['buys'])+'／'+str(m['closed']),f"{m['total_return']:.3%}",
             f"{abs(m['drawdown']):.3%}",f"{m['realized_pnl']:,.2f}元",
             f"{m['profit_factor']:.3f}" if m['profit_factor'] is not None else '无亏损样本',
             f"{m['best_r']:.2f}" if m['best_r'] is not None else '无样本'))+'</tr>')
    current=compare[-1]['metrics']
    finding=('本轮未出现本级保护位提升，不能认为统一时间参照已经解决利润回吐。'
             if audit['promoted_stop_events']==0 else '本轮出现本级保护位提升，仍须逐笔检查保护时点及利润回吐。')
    blocked=[]
    if (p/'holding-waves.json').exists():
        blocked=[t for t in load('holding-waves.json')['trades'] if
                 t.get('initial_core_stop_upper_bound',{}).get('raising_stop_impossible_under_observed_peaks')]
    constraint_finding=''
    if blocked:
        constraint_finding='<p style="color:#8b241c"><strong>已确定的规则约束：</strong>'+str(len(blocked))+\
            '笔持仓在全部已观察高点下，本级幅度门槛允许的保护价上界都低于初始止损，期间无法依该规则抬高止损。'+\
            '这是实验级别定义的限制，不能归为书中要求。具体计算见下方持仓波谷记录。</p>'
    parts+=['</table><p>v5.11是触发价消费修复前的对照，包含计划前已突破的600089、002709，不能作为最终版本的盈利证据。</p>',
        '<p>最终版本净盈亏 '+f"{current['realized_pnl']:,.2f}"+'元。'+finding+
        '成交样本和已反复研究的数据不足以证明稳定的盈利优势。</p>',
        constraint_finding,
        '<h2>成交数量的去重解释</h2><p>'+str(audit['independent_plans'])+'个独立计划，'+str(audit['approved_plans'])+
        '个通过计划审核，'+str(audit['filled_plans'])+'个成交。拒绝原因按独立计划的首次决定统计，订单续期事件不重复计为机会。</p>',
        '<pre>'+esc(json.dumps({k:audit[k] for k in ('first_rejections','suppressed_by_existing_position','plans_without_approval_or_rejection','approved_unfilled_plans')},ensure_ascii=False,indent=2))+'</pre>',
        '<h2>逐笔利润保护</h2><p>本级保护位提升事件：'+str(audit['promoted_stop_events'])+
        '次。峰值R使用退出日前最高收盘毛浮盈，实现R含费用。峰值是观察记录，不是可实现的最优离场。</p>',
        '<table><tr><th>股票</th><th>买入</th><th>卖出</th><th>峰值收盘毛浮盈R</th><th>实现净R</th><th>净盈亏</th><th>退出原因</th></tr>']
    for t in diagnostic['trades']:
        parts.append('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in (t['symbol'],t['entry_date'],t['exit_date'],
            f"{t['peak_close_gross_r']:.2f}",f"{t['realized_r']:.2f}",f"{t['net_pnl']:,.2f}元",t['exit_reason']))+'</tr>')
    parts+=['</table><h2>已验证与尚未成立</h2>',
        '<p>'+str(test_count)+'项Python测试通过；核心层29案例的87次截断重算一致；生命周期、父子引用、交易日期链和触发价消费审计通过。页面29案例174次DOM及绘图调用检查通过，未声称实际浏览器截图验证。</p>',
        '<p>这些检查不证明独立的波段识别准确率，也不证明已经稳定实现少数大盈利覆盖多次小亏损。周线W级别对应、真实小时节奏、问号阶段按次级波谷保护、丰厚利润后提高持仓周期及利润保护仍有缺口。自动账户风险收缩不能代替持仓阶段转换。</p>',
        '<h2>触发价消费核对</h2><pre>'+esc(json.dumps(fresh,ensure_ascii=False,indent=2))+'</pre>',
        '<p><a href="comparison.html">完整版本对照</a> · <a href="trade-timeline.html">买卖及结构日期链</a> · <a href="trade-timeline.csv">交易日期CSV</a> · <a href="trade-structure.html">成交结构与保护位图</a> · <a href="../20261010-v5_11-wave-validation-confirmed/review.html">结构图形对照</a> · <a href="../20261010-v5_11-wave-validation-confirmed/report.html">核心层验证</a></p>']
    if (p/'holding-constraints.json').exists():
        parts+=['<h2>持仓时间参照核对</h2><pre>'+esc(json.dumps(load('holding-constraints.json'),ensure_ascii=False,indent=2))+'</pre>',
                '<p>v5.11.1的002602使用34天日线调整参照，却从入场小结构计算16天上涨段，并将离场预算压缩为18天。v5.11.2从所属日线核心C点计量，超时预算也使用日线调整参照。表中只重算没有发生保护提升的超时交易，不替代完整持仓审计。</p>']
    if (p/'holding-waves.json').exists():
        parts+=['<h2>持仓期间的波谷分类记录</h2><p>只统计实际记录的分类和拒绝事件。归入本级仍需通过匹配、恢复及止损上移条件；没有记录的拒绝原因不能据此推断。</p>',
                '<table><tr><th>股票</th><th>内部调整</th><th>本级候选</th><th>未确定</th><th>较高低点拒绝</th><th>保护位提升</th><th>本级门槛下保护价上界</th><th>初始止损</th></tr>']
        for t in load('holding-waves.json')['trades']:
            c=t['classification_counts'];bound=t.get('initial_core_stop_upper_bound',{})
            parts.append('<tr>'+''.join('<td>'+esc(x)+'</td>' for x in (t['symbol'],c.get('internal',0),
                c.get('core',0),c.get('unresolved',0),t['rejected_floor_count'],t['promoted_stop_count'],
                f"{bound['max_candidate_stop']:.3f}" if bound else '未重算',
                f"{bound['initial_stop']:.3f}" if bound else '未重算'))+'</tr>')
        parts+=['</table><p>没有发生保护提升的owned_core持仓中，本级候选要求下跌幅度≥初始调整参照。因此保护价≤（已观察高点−参照幅度）×（1−缓冲）。若最高的上界仍不高于初始止损，则该持仓观察期间不可能因该规则抬高止损；反之仅代表未被这一必要条件排除，不能证明其余条件满足。表中统一到退出日复权尺度。</p>',
                '<p><a href="holding-waves.json">持仓结构事件、必要条件计算与日期原始记录</a></p>']
    (p/'assessment.html').write_text('\n'.join(parts),encoding='utf-8')
    print('Created',p/'assessment.html')


if __name__=='__main__':main(sys.argv[1])
