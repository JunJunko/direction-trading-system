"""Reproducible attribution and final report for the frozen v11 experiment."""
import csv
import hashlib
import html
import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'runs/20261109-qualified-candidates-verified'

def load(p):
    return json.loads(p.read_text(encoding='utf-8'))

def rows(p):
    with p.open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))

def dump(p, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def table(headers, data):
    return '<div class="scroll"><table><thead><tr>' + ''.join('<th>'+html.escape(str(x))+'</th>' for x in headers) + '</tr></thead><tbody>' + ''.join('<tr>'+''.join('<td>'+html.escape(str(x))+'</td>' for x in row)+'</tr>' for row in data) + '</tbody></table></div>'

NEW_NOTES = {
    '08b49e5260': '000301：多年U形恢复，左右肩集中在两端少数K线，传递规则本身没有解决尺度失配。',
    '1384feecde': '002937周线W：两个回落低点可见，但背景为持续上涨，更像上涨途中的调整；不应仅凭W标签称为底部反转。',
    '141217011c': '000059：多年宽底，左肩反弹短、右肩回落急，肩部与主跌升段不在同一时间尺度。',
    '2759621c25': '600389：大幅下跌后多年恢复，左肩至左峰几乎挤在一起，仍是大底部配短肩。',
    '3e507e99b2': '002192：宽阔下跌恢复段，左肩几根K线、右肩也短，尺度失配明确。',
    '4496116b90': '603187：多年底部恢复，左肩反弹较短；右侧有回落，但整体不呈均衡的三段底部。',
    '53a6cdb976': '600315：左右肩均可辨认，主底部明显更宽，5%阈值仍能放行这类长期大底部。',
    '83809891b5': '003011：长期底部后的恢复，左肩较短，右肩仅末端小回撤。',
    '9188488c5c': '002591：先行下跌、左肩反弹、较深头部和右侧回撤均可辨；右肩较浅但持续多根K线，突破幅度较小。持仓期回落后修复，期末仍未平仓。',
    '99198318b8': '603989：长期宽底，左肩短、右侧回撤短，单独失效传递仍会交易这种尺度不匹配形态。',
    'a5de7ad2d8': '603661：约一年尺度的底部，左右外肩有持续反弹/回落，10%规则合格；头部包含跳空，形态合格不等于突破可靠。随后支撑退出小亏。',
    'a79729983a': '002930：多年恢复背景，两侧外肩挤在边缘，尺度仍明显偏小。',
    'dbdeb9e1b4': '603519周线W：两个低点和中间反弹可辨，左侧处于区间震荡，第二底下影较长；成交后仍可失败。',
    'de803137b5': '600388：多年大底部，左肩仅很短反弹，右肩较短，失效传递没有独立修正几何语义。',
    'df6d721740': '600426：长周期底部，左右肩均短于主跌升段，属于质量筛选需要处理的案例。',
    'eaf13fa7ca': '600076：多年深底部，肩部局限在两端；右侧波动明显但左肩很短。',
    'f62b1b0c8d': '600057：外肩比极短肩案例更清楚，但主底部仍很宽；5%容忍度保留了此类结构。',
    'feb38d1bc5': '001300：左侧快速下跌与右侧长期恢复高度不对称，左肩短；仅排序或传递不足以改善。',
}

def main():
    protocol = load(RUN/'protocol.json')
    summary = rows(RUN/'comparison.csv')
    trades = rows(RUN/'chart-audit/trade-audit.csv')
    cases = {x['case']: x for x in summary}
    assert len(cases) == 42 and load(RUN/'status.json')['status'] == 'complete'
    old = ROOT/'runs/20261109-candidate-policy-full/chart-audit'
    notes = load(old/'visual-review.json')['observations']
    for key in notes:
        assert (old/'structures'/f'{key}.png').read_bytes() == (RUN/'chart-audit/structures'/f'{key}.png').read_bytes()
    assert not notes.keys() & NEW_NOTES.keys()
    notes.update(NEW_NOTES)
    assert set(notes) == {x.stem for x in (RUN/'chart-audit/structures').glob('*.png')}
    dump(RUN/'chart-audit/visual-review.json', dict(
        method='AI辅助非盲图审，不是人工标注误判率。45张旧结构图逐字节相同，复用上一轮观察；18张新增结构通过接触表逐张查看，另放大603661、002591结构以及主方案3笔IHS持仓图。收益已知，不能称为盲审。',
        reused_byte_identical=45, newly_reviewed=18, observations=notes,
        holding_reviews={
            'quality_10_guard-a5de7ad2d8': '11月3日买入，11月12日起动态支撑约34元；11月19日退出，净亏227.11元。未触初始止损，属于动态支撑退出。',
            'quality_10_guard-7b5b300ff8': '8月19日买入，支撑逐次抬高，9月2日跌破动态支撑退出，净利7874.69元。',
            'quality_10_guard-9188488c5c': '8月31日买入后震荡回落，但未触初始保护线；9月30日期末未平仓，按市值计入220.06元，不能记为已实现盈利。'}))
    diagnostics = {}
    for policy in protocol['configs']:
        account = RUN/(policy+'_combined_cost1')
        own = [x for x in trades if x['policy'] == policy]
        pnl = sum(float(x['pnl']) for x in own)
        expected = float(cases[policy+'_combined_cost1']['final_equity']) - float(cases[policy+'_combined_cost1']['initial_cash'])
        assert abs(pnl-expected) < 1e-6, (policy, pnl, expected)
        audits = [x for x in rows(account/'entry_audit.csv') if 'head_shoulders' in x['strategy']]
        reasons = Counter(x['risk_reason'] or x['execution_reason'] for x in audits)
        family = {f: {state: sum(float(x['pnl']) for x in own if x['family'] == f and x['closed'] == flag)
                      for state, flag in [('realized','True'),('open_marked','False')]} for f in ['IHS','W']}
        diagnostics[policy] = dict(total_pnl=pnl, family_pnl=family, entry_audit_rows=len(audits),
            unique_audited_candidates=len({x['setup_id'] for x in audits}), entry_reasons=dict(reasons))
    attribution = {}
    for before, after in [('balance_single','quality_10_guard'),('balance_fallback','propagation_only')]:
        a = {(x['symbol'],x['signal']): x for x in trades if x['policy'] == before}
        b = {(x['symbol'],x['signal']): x for x in trades if x['policy'] == after}
        assert len(a) == sum(x['policy'] == before for x in trades)
        assert len(b) == sum(x['policy'] == after for x in trades)
        common, removed, added = a.keys()&b.keys(), a.keys()-b.keys(), b.keys()-a.keys()
        item = dict(before=before, after=after, matched_on='symbol + signal date, including anchor changes',
            shared_count=len(common), shared_pnl_change=sum(float(b[k]['pnl'])-float(a[k]['pnl']) for k in common),
            removed_count=len(removed), removed_old_pnl=sum(float(a[k]['pnl']) for k in removed),
            added_count=len(added), added_new_pnl=sum(float(b[k]['pnl']) for k in added),
            removed_trades=[a[k] for k in sorted(removed)], added_trades=[b[k] for k in sorted(added)])
        item['net_change'] = item['shared_pnl_change']-item['removed_old_pnl']+item['added_new_pnl']
        assert abs(item['net_change']-(diagnostics[after]['total_pnl']-diagnostics[before]['total_pnl'])) < 1e-6
        attribution[after] = item
    qualifications = {}
    for tag in ['05','10','20']:
        q = [x for x in rows(RUN/f'quality_{tag}-qualification.csv') if x['event']=='candidate_qualification']
        assert len(q) == 2064
        qualifications[tag] = dict(total=len(q), passed=sum(x['shape_qualified']=='True' for x in q),
            reason_combinations=dict(Counter(x['shape_rejection_reasons'] for x in q)))
        for combined in ['IHS','combined']:
            for cost in [1,2]:
                a=RUN/f'quality_{tag}_{combined}_cost{cost}'
                b=RUN/f'quality_{tag}_guard_{combined}_cost{cost}'
                # Strategy IDs differ, so compare actual order execution fields and equity.
                fields=['date','symbol','side','status','price','quantity','fee','reason']
                assert [[x.get(k) for k in fields] for x in rows(a/'orders.csv')] == [[x.get(k) for k in fields] for x in rows(b/'orders.csv')]
                assert rows(a/'equity.csv') == rows(b/'equity.csv')
    guard_audits=rows(RUN/'propagation_only_combined_cost1/entry_audit.csv')
    evidence = {symbol:[x for x in guard_audits if x['symbol']==symbol] for symbol in ['003031.SZ','603098.SH','000762.SZ']}
    dump(RUN/'diagnostics.json', dict(policies=diagnostics, qualification=qualifications, attribution=attribution,
        same_execution_with_without_guard=True, case_evidence=evidence))

    labels={'baseline':'原基线','balance_single':'上一轮较优：平衡首选','balance_fallback':'平衡排序＋候补',
            'propagation_only':'仅同底失效传递','quality_05':'质量5%','quality_10':'质量10%', 'quality_20':'质量20%',
            'quality_05_guard':'质量5%＋传递','quality_10_guard':'主方案：质量10%＋传递',
            'quality_20_guard':'质量20%＋传递','W_only':'仅周线W'}
    keytable=[]
    for policy in protocol['configs']:
        a=cases[policy+'_combined_cost1']; b=cases[policy+'_combined_cost2']
        keytable.append([labels[policy],f"{float(a['total_return']):.2%}",f"{abs(float(a['max_drawdown'])):.2%}",
            a['IHS_buys']+'/'+a['W_buys'],f"{float(b['total_return']):.2%}",f"{abs(float(b['max_drawdown'])):.2%}"])
    content=['''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>候选质量与同底失效传递：全量对照</title><style>
body{font:16px/1.75 system-ui,"Microsoft YaHei",sans-serif;max-width:1180px;margin:32px auto;padding:0 24px;color:#203044;background:#fafbfc}
h1{font-size:30px}h2{font-size:23px;margin-top:38px}a{color:#1765a3}table{border-collapse:collapse;width:100%;font-size:14px;background:white}
th,td{padding:9px 12px;border-bottom:1px solid #dce3eb;text-align:right}th:first-child,td:first-child{text-align:left}th{background:#eaf0f6}.scroll{overflow:auto}
.callout{padding:18px 22px;background:#eaf0f6;border-left:5px solid #426b96}img{width:100%;height:auto;background:white}figure{margin:24px 0}figcaption{font-size:14px;color:#465a70}
details{margin:18px 0}summary{cursor:pointer;font-weight:600}.small{font-size:14px;color:#526274}</style>
<h1>候选形态合格标准与同一底部失效传递</h1><p class="small">报告日期：2026-11-10｜冻结实验：20261109-qualified-candidates-verified｜研究结果，未替换默认策略</p>
<div class="callout"><b>两类机械问题得到限制，但没有同时改善收益。</b>主方案收益4.87%、最大回撤1.37%，低于上一轮较优方案的9.85%；只加失效传递收益6.13%、回撤3.93%。
主方案只成交3笔头肩底，无法据此证实真实误判率下降。组合利润大部分来自周线W，双倍费用/滑点下也没有超过仅周线W。</div>
<h2>统一口径与结果</h2><p>3214只股票、2,856,672根日K；预热从2023-01-03开始，评估2025-10-09至2026-09-30。100万元共享账户。
全部2064个原始头肩底候选（1713个股票信号日）和1146个周线W信号参与，未只取旧成交样本。质量规则只删选原几何候选；运行时失效状态、成交、风控、出场均在各账户独立重演。
10种候选策略×IHS单独/组合×两档成本，加2组W单独，共42组。所有12个旧对照账户逐项复现。</p>
<p>风控保持单笔0.5%、组合2%、单票10%、总仓50%、最多5票，预期空间严格大于5%、净报酬风险比严格大于3。双倍成本只加倍佣金费率与买卖滑点，最低佣金及税率不变。收益含期末浮盈，未强平。</p>''']
    content.append(table(['组合方案','正常成本收益','最大回撤','IHS/W买入数','双倍成本收益','双倍成本回撤'],keytable))
    content.append('''<p>5%、10%、20%是回测前声明的尺度敏感性，不是根据结果反复搜索。20%方案仅比10%多约227元收益，且只剩2笔IHS，不能据此选为更优阈值。质量筛选后，三个阈值的有/无传递版本在两档成本和两类账户中成交与净值完全一致；传递虽额外拒绝候选，但本样本没有增量收益。</p>
<h2>本轮实际修改</h2><ol><li>先判断合格，再排序：L→P1和P2→R两段外肩各至少3个实际交易日；各自长度至少达到相邻P1→H、H→P2主段的10%。保留5%/20%对照，不简单按大底部总跨度一刀切。</li>
<li>合格候选按四段时间平衡排序。所有看过的原候选均消费，避免被拒后重发同一结构；换肩或换颈线不能更换底部身份。</li>
<li>同底部按“股票＋已确认头部日期”归组。真实开盘丢失突破、开盘破保护、成交后触初始保护线，封锁同头部后续候选。新确认头部才开始新组。净RR不足、空间不足、追高、无效止损等只否决同信号日同底部候补；后续新信号日允许重新评估。</li>
<li>现金、风险预算、满仓、停牌或已有持仓不写成形态失效。收盘才知道的低点不得倒推否决当日开盘；首选成交后的闲置备选也不得反过来污染该底部。</li></ol>
<p>“同一底部”目前是精确头部日期，不代表已解决相邻低点属于同一宏观底部的问题；这一更宽的归并规则尚未实验。本轮也没有修改W识别语义、入场距离、目标和动态出场。</p>
<h2>收益为何下降，瓶颈在哪里</h2>''')
    content.append(table(['外肩/主段下限','原候选','合格候选','过滤比例'], [[k+'%',2064,v['passed'],f"{1-v['passed']/2064:.1%}"] for k,v in qualifications.items()]))
    primary=diagnostics['quality_10_guard']
    content.append(f'''<p>10%主方案过滤75.0%的候选。对剩余515个候选，逐项入场审计中的主要拒绝是净RR不足303次、突破距离过大121次；同日失效传递29次。记录次数按候选审计计，不能当作独立交易或误判率。最终仅3笔IHS成交。说明形态合格之后，当前突破入场价、右肩保护距离与目标空间的组合仍很难满足净RR门槛。</p>''')
    content.append(table(['IHS候选审计结果','记录次数'],sorted(primary['entry_reasons'].items(),key=lambda x:-x[1])))
    content.append(table(['组合利润归属','已实现/元','未平仓按市值/元'],[[f, f"{d['realized']:,.2f}",f"{d['open_marked']:,.2f}"] for f,d in primary['family_pnl'].items()]))
    content.append('''<p>主方案IHS总贡献7,867.63元，W贡献40,844.93元；其中W的002242期末浮盈29,376.07元，尚未兑现。IHS单独账户正常成本收益约0.79%，双倍成本约−0.02%。组合回撤下降同时伴随交易和风险暴露减少，不能把它全解释成预测更准。</p>
<p>按“股票＋信号日”匹配，避免将换锚点算成全新交易，得到以下完整净值差额分解（含期末市值；持仓和仓位路径变化也会影响共同交易）：</p>''')
    content.append(table(['比较','共同交易数/盈亏变化','移除交易数/原盈亏','新增交易数/新盈亏','净变化'],[[labels[v['before']]+' → '+labels[v['after']], f"{v['shared_count']} / {v['shared_pnl_change']:,.2f}",f"{v['removed_count']} / {v['removed_old_pnl']:,.2f}",f"{v['added_count']} / {v['added_new_pnl']:,.2f}",f"{v['net_change']:,.2f}"] for v in attribution.values()]))
    content.append('''<p>仅传递方案漏掉003031（2026-01-27信号，旧候补方案赚25,203.98元），审计原因为风险预算不足，并非同底封锁：当日已用风险27,216.35元，剩余风险预算−6,588.94元，现金仍约93.09万元。持仓为600388、600076、605117、600426；旧候补方案当日仅持600063、605117。传递先改变其他交易，再改变后续可用风险预算，不能只累加“挡掉的亏损”来评价它。</p>
<h2>交易记录与K线核验</h2><p>11个正常成本组合累计201笔买入记录、169笔退出、213次保护线更新已做价格、时间和水平核验；对应63个不同成交结构。跨方案重复交易不是独立样本。45张旧图与上一轮逐字节相同，复用已有观察；18张新增图完成非盲图审，另放大主方案3笔IHS的持仓路径。图审观察不是人工标签或真实误判率。</p>
<p>上一轮较优方案32笔IHS中，16笔至少一侧外肩≤2个交易日、22笔跨度超过250个交易日；主方案3笔两项均为0。这个变化证明筛选按设计工作，却不能独立证明策略预测能力提高。</p>''')
    examples=[
        ('f87ca29915','603098：首选净RR失败后，不再换锚点绕过','旧候补2026-03-25换锚点成交，亏4,873.53元。仅传递方案保留首选RR拒绝，并将其余3个同日同头候补记为cohort veto；质量主方案更早就因肩部尺度不合格排除。'),
        ('0fc7f38ce1','000762：旧底部保护已破，后续换肩仍继承失效','2025-11-24触初始保护，2026-05-06同头部的4个候选全部继承失效。旧候补该次交易亏620.70元；更早的11月亏损仍存在，传递无法事后消除。'),
        ('85c4f4c3b1','003031：过滤掉的问题形态也可能是大赢家','外肩相对多年主底部很短，质量规则将其排除；上一轮较优和候补方案该次净赚25,203.98元。盈利不等于形态标签正确，但删除它确有收益代价。'),
        ('a5de7ad2d8','603661：合格后仍会小亏',notes['a5de7ad2d8']),
        ('7b5b300ff8','002800：保留的盈利案例','左右肩可辨，但仍偏短。按突破买入，动态支撑逐次抬高，最终净赚7,874.69元；这是主方案绝大部分IHS利润。'),
        ('9188488c5c','002591：形态更规整，收益尚未兑现',notes['9188488c5c'])]
    for key,title,description in examples:
        content.append(f'<h3>{html.escape(title)}</h3><p>{html.escape(description)}</p><figure><img loading="lazy" src="chart-audit/structures/{key}.png" alt="{key}结构图"><figcaption>信号日为止的结构，不含后来K线。</figcaption></figure>')
        if key in ['a5de7ad2d8','7b5b300ff8','9188488c5c']:
            content.append(f'<figure><img loading="lazy" src="chart-audit/holdings/quality_10_guard-{key}.png" alt="持仓、保护线与出场核验"></figure>')
    content.append('''<h2>结论与下一步实验</h2><p>本轮不把新方案升级为默认配置。正常成本下，上一轮时间平衡首选＋W仍是本次对照中收益最高的组合；但它的短肩语义问题和双倍成本亏损仍未解决。</p>
<p>下一轮优先检验“合格形态的入场时机”：固定本轮质量标准，单独比较突破入场与回踩后重新确认，检查净RR不足和追高拒绝是否减少，以及是否只是漏掉强势行情。其次再对失效后的重新武装条件做单因素实验，例如新的确认低点和重新站回结构，而不是任意换锚点。不能一边放宽形态、一边改变目标和止损后再将改善归因给某一个规则。</p>
<p>本次沿用已看过的历史区间，属于开发样本，尚无独立保留样本证明。下一轮应先冻结标准、按时间分开发/验证/最终保留段，在最终段只评估一次；另对未成交合格候选做不知道后续涨跌的人工图审，才能讨论真实误判率。日K无法还原完整盘中路径，沿用项目既有复权和执行限制。</p>
<h2>复现与核验文件</h2><p>449项测试通过；全部42个账户风控与信号核验通过；12组普通原生扫描抽查与候选池重放一致。9,021条失效来源及1,167条传递拒绝完成来源、头部身份、观察时钟与成交因果检查（为跨账户累计记录）。</p>
<ul><li><a href="chart-audit/charts.html">全部交易与K线图</a> · <a href="chart-audit/visual-review.json">63张图的非盲观察</a> · <a href="chart-audit/trade-audit.csv">逐笔交易审计</a></li>
<li><a href="comparison.csv">42组完整结果</a> · <a href="diagnostics.json">筛选、拒绝和收益差额归因</a> · <a href="protocol.json">冻结协议、配置和指纹</a></li>
<li><a href="verification.json">全量核验</a> · <a href="pool-verification.json">原始候选池核验</a> · <a href="native-verification.json">普通扫描一致性</a> · <a href="failure-verification.json">失效来源核验</a> · <a href="failure-lineage.json">传递明细</a></li>
<li><a href="chart-audit/verification.json">K线价格/时间核验</a> · <a href="chart-reuse-verification.json">修正前后图表复用核验</a> · <a href="tests.log">449项测试日志</a> · <a href="quality_10_guard-config.json">主方案研究配置</a> · <a href="final-verification.json">交付指纹与最终检查</a></li></ul>''')
    content.append('<details><summary>展开全部42组结果</summary>'+table(['账户','收益','回撤','买入数','期末持仓'],[[x['case'],f"{float(x['total_return']):.4%}",f"{abs(float(x['max_drawdown'])):.4%}",x['filled_buys'],x['open_positions']] for x in summary])+'</details></html>')
    (RUN/'report.html').write_text('\n'.join(content),encoding='utf-8')
    # Preserve the analysis/verification scripts alongside the frozen implementation.
    for name in ['report_qualified_candidates.py','audit_qualified_candidates.py','audit_candidate_policy.py',
                 'check_qualified_lineage.py','verify_qualified_candidates.py','reuse_qualified_audit.py',
                 'backtest_qualified_candidates.py','backtest_candidate_policy.py']:
        dst=RUN/'source/scripts'/name;dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(ROOT/'scripts'/name,dst)
    print('REPORT COMPLETE: 42 accounts; 63 structure observations; PnL reconciled for all 11 combined arms.')

if __name__ == '__main__':
    main()
