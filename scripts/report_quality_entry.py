"""Full account evidence for four entry-only filters; retain all failed variants."""
import hashlib,html,shutil
from backtest_quality_entry import ROOT,OUT,CASES,load,rows,dump

NOTES={
'002201.SZ':'双底，原开盘仅高于前复权收盘约0.118%，过滤后不再买入。原单净亏约1,872元。K线中入场后回落，原策略按规则止损；过滤避免了这次亏损，但如此小的高开也被排除，不能据此称高开本身必然失败。',
'001229.SZ':'双底盈利单被直接误删：原单利润7,565.92元。图中12月29日买入当日大涨，原版次日退出兑现盈利。候选仅因约0.077%的高开而跳过，因此过滤绝不是只删亏损单。',
'000422.SZ':'原双底大赢家利润9,337.59元，开盘条件本可通过；候选在1月13日信号阶段被 max_positions 拒绝，故1月14日没有买单。这是其他成交改变持仓名额的间接损失，不能算该股票高开不合格。',
'002006.SZ':'头肩底开盘高于前复权收盘约1.089%，原单亏4,916.78元，候选直接排除。图中随后下跌，属于过滤命中的亏损案例。候选没有改变这笔单的止损或事后等待规则。',
'002518.SZ':'头肩底盈利单也被直接排除，原单利润约3,876元；图中虽有回撤，后续仍走强。与删掉的亏损单一起展示，避免只挑成功的过滤案例。',
'603989.SH':'头肩底最大赢家保留：两版入场、退出日期一致，利润均28,115.62元。K线中的震荡后主升段仍完整经过原退出管理；本轮过滤没有像提前日线保护那样截短该赢家。'}

def table(headers,data):
    return '<table><thead><tr>'+''.join('<th>'+html.escape(str(v))+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in data)+'</tbody></table>'

def main():
    comparisons=rows(OUT/'comparison.csv');by={r['case']:r for r in comparisons};pairs=rows(OUT/'paired-trades.csv');attrib=rows(OUT/'attribution.csv');verification=load(OUT/'verification.json')
    assert len(comparisons)==12 and all(r['passed'] for r in verification.values())
    b=['<h1>从入场前过滤低质量交易</h1><p>2026-11-10｜四个固定条件，各自单变量测试｜8个新账户＋4个冻结基准</p>',
       '<p class="lead">目前最有价值的线索是：不追高开，允许平开或低开。标准及双倍成本下，双底与头肩底均改善。双底仍亏损，头肩底保留原前五大赢家。这个条件也会误删盈利单，尚不升级默认策略。</p>',
       '<h2>范围与规则</h2><p>同一3214只股票快照、6014个日线双底信号、1713个头肩底信号；评估2025-10-09至2026-09-30，预热自2023-01-03，资金100万元。冻结原v7入场候选与退出，只在下一开盘的执行风控层增加一个拒绝条件。没有使用上轮重新入场或提前日线保护，也没有组合四个过滤器。</p>',
       table(['条件','通过标准','已知时点'],[['W_span120','两底间距≤120根股票日线','信号出现时'],['W/IHS_no_gap_up','当日原始开盘≤前一股票日线复权到当日的收盘；允许平开','当日开盘'],['IHS_neck_half_atr','含滑点买价距执行日冻结颈线<0.5×前14日ATR','当日开盘，ATR仅用此前日线']]),
       '<p>“不追高开”按真实开盘判定，不把滑点算成高开。原有净RR&gt;3、上涨空间&gt;5%、W止损距离≤2%、账户风险和退出全部保留。四个条件来自此前交易分组的探索，阈值在本轮结果前冻结，没有网格搜索。已研究区间中的前后半年也不能冒充训练/验证集。</p>',
       '<h2>完整账户结果</h2>']
    b.append(table(['账户','累计收益','最大回撤','成交买入/平仓','胜率'],[[r['case'],f"{float(r['total_return']):.3%}",f"{abs(float(r['max_drawdown'])):.3%}",r['filled_buys']+'/'+r['closed_trades'],f"{float(r['win_rate']):.1%}"] for r in comparisons]))
    b.append('<p>cost1为标准成本；cost2把佣金率与双边滑点翻倍，最低佣金及印花税不变。W_span120两种成本下小幅减亏，但不如不追高开；IHS_neck_half_atr标准成本改善，双倍成本收益0.774%→−1.502%，不具备本轮成本稳健性。</p>')
    b.append('<h2>不追高开到底少做了什么</h2>')
    chosen=[r for r in attrib if '_no_gap_up_' in r['case']]
    b.append(table(['账户','亏损笔数 原→新','原成交不再出现','其中原亏损/原盈利','新增成交','共同交易差额','移除交易贡献','新增交易贡献'],[[r['case'],r['baseline_losses']+'→'+r['losses'],r['removed'],r['removed_losses']+'/'+r['removed_wins'],r['added'],f"{float(r['shared_delta']):+,.2f}",f"{float(r['removed_delta']):+,.2f}",f"{float(r['added_delta']):+,.2f}"] for r in chosen]))
    b.append('<p>金额为元，包含期末未平仓市值。标准成本W账户多出36,466.63元，IHS多出11,163.90元。不能把原成交表中的亏损行直接删除后相加：W少了86笔原成交，但新增60笔；IHS少了17笔，新增6笔。各账户重新计算资金、名额、风险预算和仓位，表中共同交易差额也包含数量变化。</p>')
    b.append('<p>W不再成交的86笔中，33笔的开盘条件本可通过，是账户路径变化使其未成交；IHS同类有4笔。因此这些移除不能全部归因于“高开质量差”。baseline-screen.csv记录对原交易静态过滤的结果，paired-trades.csv记录真实重跑变化，两种口径分开保留。</p>')
    for family in ('W','IHS'):
        own=[p for p in pairs if p['case']==family+'_no_gap_up_cost1'];top=sorted(own,key=lambda p:float(p['old_pnl']),reverse=True)[:5]
        b.append('<h3>'+family+'原前五大赢家</h3>'+table(['代码','原利润','新利润','状态'],[[p['symbol'],f"{float(p['old_pnl']):,.2f}",f"{float(p['new_pnl']):,.2f}",p['category']] for p in top]))
    b.append('<p>W误删001229（高开直接拒绝）以及000422（1月13日max_positions拒绝），两笔原利润约7,566元和9,338元。IHS原前五大赢家全部保留；但其后面的002357原利润5,135元因9月2日insufficient_budget_or_cash未成交，002518原利润3,876元因高开被直接剔除。</p>')
    b.append('<h2>改善是否仅来自一个半年</h2>')
    halves=[]
    for family in ('W','IHS'):
        for cost in (1,2):
            for rule in ('baseline','no_gap_up'):
                case=f'{family}_{rule}_cost{cost}';eq=rows(OUT/case/'equity.csv');mid=[r for r in eq if r['date']<'20260401'][-1]
                halves.append([case,f"{float(mid['equity'])/1e6-1:.3%}",f"{float(eq[-1]['equity'])/float(mid['equity'])-1:.3%}"])
    b.append(table(['账户','开始至2026-03-31','2026-04-01至结束'],halves))
    b.append('<p>这里按连续账户在3月31日的权益分段，跨段持仓保留；不是各半年重置账户。标准成本两种策略的两个半年均有改善，但仍属于同一已使用样本的稳定性观察。</p>')
    b.append('<h2>K线与逐笔核验</h2><p>以下6张图均在看到结果后挑选并逐张核对：包括删掉的亏损、误删的赢家、名额挤占和保留的大赢家。上图放大入场附近，虚线标前收盘，过滤只读取当时开盘；下图展示原交易持有及退出。后续K线仅用于评价，不参与过滤。</p>')
    for c in load(OUT/'charts/index.json'):
        b.append(f'<section><h3>{c["family"]} {c["symbol"]}</h3><p>{NOTES[c["symbol"]]}</p><a href="{c["chart"]}"><img src="{c["chart"]}" alt="{c["symbol"]} entry quality review"></a></section>')
    b.extend(['<h2>验证与结论边界</h2><p>457项测试通过。12组账户共1,436笔买入记录逐笔复算开盘滑点、费用、复权数量和最终损益，与账户权益对账一致；2,206条执行评估独立重算过滤值，并核验历史信息早于入场日。测试验证当日高低收盘变化不影响过滤、除权价格口径、平开与阈值边界。4个基准直接复用上一轮已验证冻结结果，8个新账户从全部原信号重跑。</p>',
      '<p>“高开”里很多只是一个报价档位的微小差异，例如001336约0.038%、002201约0.118%，尚未证明在其他行情、不同数据处理或执行条件下仍有效。日线撮合、合成复权和已有样本反复研究的限制仍保留。本轮显示的是过滤后的历史账户改善，不能证明某种图形天然低质量，也不能推断实盘收益。失败的颈线过滤结果完整保留。</p>',
      '<p>下一步优先验证不追高开在未使用时间段的效果，并单独检查它是否通过压低买入价格改善盈亏，而非单纯减少笔数。暂不叠加更多过滤器，不依据这次结果升级默认策略。</p>',
      '<h2>文件</h2><ul>'+''.join(f'<li><a href="{name}">{name}</a></li>' for name in ['comparison.csv','attribution.csv','paired-trades.csv','baseline-screen.csv','trade-paths.csv','verification.json','protocol.json','manifest.json','source/quality-entry-tests.log'])+'</ul>',
      '<p>各case目录保存配置、信号事件、拒绝原因、订单、逐笔交易和权益。研究脚本backtest_quality_entry.py调用QualityEntryBacktest执行门槛；配置中的research_experiment_id区分版本，保留原setup_id用于逐笔匹配。普通回测入口不会自动启用研究门槛。</p>'])
    css='body{max-width:1180px;margin:40px auto;padding:0 24px;font:16px/1.8 system-ui,"Microsoft YaHei",sans-serif;color:#23314b;background:#f6f8fb}h1,h2,h3{line-height:1.4}h2{margin-top:36px}.lead{background:#e6f3ed;padding:20px;border-left:5px solid #3c8866}table{border-collapse:collapse;width:100%;font-size:13px;background:white}td,th{padding:9px;border:1px solid #dce3ee;text-align:left}th{background:#eaf0f8}section{padding:18px;background:white;margin:20px 0}img{width:100%;height:auto}a{color:#2458a5}'
    (OUT/'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>交易质量过滤对照</title><style>'+css+'</style><body>'+''.join(b)+'</body></html>',encoding='utf-8')
    source=OUT/'source'
    for name in ['backtest_quality_entry.py','audit_quality_entry.py','chart_quality_entry.py','report_quality_entry.py']:
        shutil.copy2(ROOT/'scripts'/name,source/name)
    for name in ['quality-entry-tests.log','quality-entry-audit.log']:shutil.copy2(ROOT/'runs'/name,source/name)
    shutil.copy2(ROOT/'tests/test_quality_entry_research.py',source/'test_quality_entry_research.py')
    dump(OUT/'charts/visual-review.json',dict(type='nonblind six reviewed images',notes=NOTES))
    code=ROOT/'src/trading_system/quality_entry_research.py';assert code.read_bytes()==(source/'src/trading_system/quality_entry_research.py').read_bytes()
    dump(OUT/'manifest.json',dict(data_sha256=load(OUT/'protocol.json')['source_protocol']['bars_sha256'],code_sha256=hashlib.sha256(code.read_bytes()).hexdigest(),tests=457,baseline_cases=4,new_cases=8,promoted=False,holdout=False,script='scripts/backtest_quality_entry.py'))
    print('REPORT READY',OUT/'report.html')

if __name__=='__main__':main()
