"""Package the completed fixed-rule experiment and nonblind candle review."""
import hashlib,html,json,shutil
from pathlib import Path
from backtest_reentry_daily_protection import ROOT,OUT,load,rows,dump

NOTES={
'600900.SH':'原单6月2日买入、6月3日止损。新低6月8日形成，6月10日才完成右侧两根K线确认，6月11日重新买入；6月16日按原动态保护退出。图上重新站回颈线后只短暂上冲，随后继续下跌。新增一笔净亏694.11元；两笔合计亏1,370.02元。确认成立不等于趋势恢复。',
'600397.SH':'12月15日买入、16日止损后快速反弹。新规则没有捕获：12月23日先触及原目标价，重试资格因 target_already_reached 取消；此前没有满足“止损后全新五根K线低点确认”的再入场。图上的上涨不能归功于候选策略，也不能把事后上涨视为当时可执行信号。',
'002541.SZ':'日线低点在2月12日、3月11日确认后上移保护；保护仍低于买价。候选3月20日卖出，原版3月23日卖出，亏损4,914.39→2,596.25元，少亏2,318.14元。图中曾上涨后回落，提前退出缓解亏损，但没有保住正收益。',
'001326.SZ':'2月13日的低点经春节后的两个有效股票交易日，在2月25日确认。候选3月23日卖出，原版3月24日卖出，亏损5,140.10→1,141.55元，少亏3,998.54元。确认按交易K线计数，不是两天自然日。图中跳空使最终成交低于保护位，不能按保护价虚算成交。',
'603989.SH':'6月2日低点于6月4日确认，新的日线保护6月5日起有效；6月12日收盘跌破，6月15日开盘卖出。原周线保护允许继续持有至7月14日。实际利润28,115.62→16,499.35元，减少11,616.27元；图上候选退出后出现更强上涨。两版都买到这笔大赢家，候选明显截短了它。',
'605117.SH':'1月6日确认的日线保护在横盘后触发，候选2月3日提前卖出；原版2月24日卖出。原利润664.30元变为亏损1,531.75元，差额−2,196.04元。图中候选退出后恢复上涨，说明更早保护也会增加震荡中的退出。'}

def table(headers,data):
    return '<table><thead><tr>'+''.join('<th>'+html.escape(str(h))+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in row)+'</tr>' for row in data)+'</tbody></table>'

def main():
    comp=rows(OUT/'comparison.csv');audit=load(OUT/'audit-summary.json');verify=load(OUT/'verification.json')
    assert len(comp)==8 and all(v['checks_passed'] for v in verify.values())
    paired=rows(OUT/'paired-trades.csv');paths=rows(OUT/'trade-paths.csv')
    body=['<h1>双底重新确认入场 · 头肩底提前日线保护</h1><p>2026-11-10｜固定规则，8组全量账户回测</p>',
    '<p class="lead">本轮两项候选均未改善净收益，不升级默认策略。日线双底重试几乎被原风险门槛挡住；头肩底回撤下降，但会截短大赢家，双倍成本下转为亏损。</p>',
    '<h2>同一口径结果</h2><p>3214只股票快照，2,856,672根日线；预热从2023-01-03开始，评估2025-10-09至2026-09-30，初始资金100万元。保留全部6014个日线W与1713个头肩底原始信号，账户按原现金、风险、持仓数和下一开盘成交规则重跑。双底重试由各账户真实止损交易实时产生。没有用成交样本反推信号，也没有混入周线双底。</p>',
    table(['策略 / 成本','累计收益','最大回撤','买入/平仓/未平仓','亏损笔数','亏损单合计','曾涨≥5%后亏损'],[
       [r['case'],f"{float(r['total_return']):.3%}",f"{abs(float(r['max_drawdown'])):.3%}",f"{r['filled_buys']}/{r['closed_trades']}/{r['open_positions']}",audit[r['case']]['loss_count'],f"{audit[r['case']]['loss_pnl']:,.2f}",audit[r['case']]['gain5_then_loss']] for r in comp]),
    '<p>cost1为原佣金与滑点；cost2将佣金率与双边滑点翻倍，最低佣金和印花税不变。成本改变会改变可入场信号、仓位与资金路径，所以两种成本之间不能按“同一批交易加手续费”理解。曾涨≥5%用入场后、实际卖出日前的复权收盘峰值判断，避免卖出当日后续行情泄漏；亏损笔数只含已平仓。</p>',
    '<h2>这次只改了什么</h2><p><b>日线双底：</b>只有原单实际初始止损退出后，才允许同一形态的一次重试。在其后14根股票日线内，形成全新的严格左2右2低点（五根K线全部在退出后），新低随后未被破坏；信号收盘高于原颈线、当日开盘、前收盘。收盘跌破原W底或退出后曾触及原目标即失效。信号提交即消费重试资格，即使被风控拒绝也不再次尝试；重试单止损不再续期。下一开盘入场、新确认低点止损、原目标不变。原有净盈亏比&gt;3、预期空间&gt;5%、W入场至止损距离≤2%全部保留。没有另加下一开盘必须站上颈线的条件。</p>',
    '<p><b>头肩底：</b>保留原周线压力支撑管理，另加持仓后完整左2右2日线低点。低点高于上一确认日线低点（首次比较入场日最低价）时，用“低点−确认日前ATR14×0.5”上移保护；只升不降且低于当日收盘。确认日之后生效，收盘跌破后在下一可成交开盘退出，不设置2R启动门槛。初始止损、入场、目标、风险预算不变。</p>',
    '<p>两条规则分别测试，未把它们组合；窗口14、左右2、缓冲0.5ATR均在结果出现前冻结，本轮没有网格调参。</p>',
    '<h2>双底：重新确认与原入场约束不兼容</h2>',
    table(['标准成本重试结果','次数'],list(audit['W_candidate_cost1']['retry_rejections'].items())),
    '<p>66次重试信号中只有600900成交，净亏694.11元。全账户少赚671.85元，其余22.26元差异来自后续仓位变化。原230个成交形态全部保留，原收益前五名也全部保留且利润一致。因此没有因为重试遗漏原大赢家，但600397这种“止损后很快上涨”的漏单也没有被修复。等到确认与收复颈线时，多数价格已经离新止损太远，或离原目标太近。</p>',
    '<h2>头肩底：减亏有效，但未保住整体收益</h2><p>标准成本最大回撤4.079%→2.762%，累计收益5.134%→4.443%；亏损单总额仅改善533.47元，亏损笔数14→17，曾上涨5%后最终亏损仍是5笔。002541、001326少亏合计6,316.69元，但603989一笔就少赚11,616.27元。双倍成本收益0.774%→−1.432%，亏损笔数17→22，亏损单合计进一步增加。因此不能把“回撤降低”直接判为“误判减少、收益提高”。</p>',
    '<h2>账户差异归因</h2>']
    attrib=[]
    for family in ('W','IHS'):
        for cost in (1,2):
            r=[p for p in paired if p['family']==family and p['cost']==str(cost)]
            groups={'共同形态':[p for p in r if p['old_entry'] and p['new_entry']], '新增成交':[p for p in r if not p['old_entry']], '不再成交':[p for p in r if not p['new_entry']]}
            attrib.extend([[family,cost,k,len(v),f"{sum(float(p['delta']) for p in v):+,.2f}"] for k,v in groups.items()])
    body.append(table(['策略','成本','分类','数量','候选−基准净损益（元，含期末持仓）'],attrib))
    body.append('<p>IHS标准成本37个共同形态、3个新增、1个不再成交。提前退出改变空位与账户资金，新增603713亏5,079.92元，不再成交的000586原亏1,751.77元。002800和002357的买卖日期未变，利润增加来自数量变化，不能算退出改善。原收益前五名均仍成交，但603989被提前卖出。</p>')
    for family in ('W','IHS'):
        base=sorted([r for r in paths if r['case']==family+'_baseline_cost1' and r['closed']=='True'],key=lambda r:float(r['pnl']),reverse=True)[:5]
        ps={r['setup_id']:r for r in paired if r['family']==family and r['cost']=='1'}
        body.append('<h3>'+family+'原收益前五名跟踪</h3>'+table(['代码','基准退出','候选退出','基准利润','候选利润'],[[b['symbol'],ps[b['setup_id']]['old_exit'],ps[b['setup_id']]['new_exit'],f"{float(ps[b['setup_id']]['old_pnl']):,.2f}",f"{float(ps[b['setup_id']]['new_pnl']):,.2f}"] for b in base]))
    body.append('<h2>交易记录与K线复核</h2><p>以下6个差异案例已逐张查看，属于知晓结果后的案例核对，不能代替盲评或样本外验证。红涨绿跌；上下图分别为基准与候选，价格统一到原入场日复权因子。三角为实际成交，紫线为当日已生效保护；橙点是确认事件，保护线从下一股票日线才显示。图中卖出后的K线仅用于观察漏掉的行情。</p>')
    for c in load(OUT/'charts/index.json'):
        body.append(f'<section><h3>{c["family"]} · {c["symbol"]}</h3><p>{NOTES[c["symbol"]]}</p><a href="{c["chart"]}"><img src="{c["chart"]}" alt="{c["symbol"]} baseline and candidate candles"></a></section>')
    body.extend(['<h2>证据与边界</h2>',
      '<p>453项测试通过。标准成本基准的orders、trades、entry_audit、equity与上轮冻结基准逐项一致。8组所有实际入场均核验下一开盘滑点、净RR和空间；逐笔含复权数量及买卖费用的损益重新计算，并与期末账户权益对账。131次重试信号核验实际源止损、新低确认时点、原目标限制；31次日线保护核验严格低点、独立重算前14日ATR及下一交易日生效。动态收盘破位核验此前有效保护位，实际退出核验后续开盘成交。详见verification.json。</p>',
      '<p>仍是此前反复研究过的单一历史区间，没有独立保留样本；使用现有日线成交假设和合成复权记账，并非逐笔撮合或精确分红现金流。本轮支持的结论是这些固定实现的区间结果，不能推断实盘收益或给两类形态定性。未改变形态合格标准，因此没有证据称形态识别误判率下降。</p>',
      '<p>后续若继续研究：双底先拆开“确认等待导致离止损过远”和“原目标消耗过快”两个约束分别测试；头肩底先区分弱走势减亏与强趋势正常回撤，测试有条件启用日线保护。以上仅为未验证假设，本轮不追加调参。</p>',
      '<h2>可复查文件</h2><ul>'+''.join(f'<li><a href="{f}">{f}</a></li>' for f in ['comparison.csv','paired-trades.csv','trade-paths.csv','audit-summary.json','verification.json','protocol.json','manifest.json','source/reentry-daily-tests.log'])+'</ul>',
      '<p>每个case目录内保留config.json、decisions.csv、entry_audit.csv、orders.csv、trades.csv、equity.csv与summary.json。回放为保持原形态一一对应使用原策略ID；独立实验配置使用v8新ID，默认配置未升级。</p>'])
    css='body{max-width:1150px;margin:40px auto;padding:0 24px;font:16px/1.8 system-ui,"Microsoft YaHei",sans-serif;color:#243047;background:#f7f9fc}h1,h2,h3{line-height:1.4;color:#182437}h2{margin-top:38px}.lead{padding:20px;border-left:5px solid #bf6841;background:#fff0e5}table{width:100%;border-collapse:collapse;font-size:13px;background:white}td,th{padding:9px;border:1px solid #dbe2ec;text-align:left}th{background:#e9eff7}img{width:100%;height:auto}section{background:white;padding:18px;margin:20px 0}a{color:#245bb2}'
    (OUT/'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="UTF-8"><title>重新确认与日线保护全量对照</title><style>'+css+'</style><body>'+''.join(body)+'</body></html>',encoding='utf-8')
    dump(OUT/'charts/visual-review.json',dict(review_type='nonblind, six images visually inspected',notes=NOTES))
    for family,name,newid in [('W','double_bottom_v8_reconfirmed','double_bottom_v8_reconfirmed'),('IHS','ihs_v8_daily_protection','inverse_head_shoulders_v8_daily_protection')]:
        cfg=load(OUT/f'{family}_candidate_cost1/config.json');cfg['strategies'][0]['id']=newid
        dump(ROOT/'configs/experiments'/(name+'.json'),cfg)
    source=OUT/'source'
    for name in ('audit_reentry_daily_protection.py','chart_reentry_daily_protection.py','report_reentry_daily_protection.py'):
        shutil.copy2(ROOT/'scripts'/name,source/name)
    shutil.copy2(ROOT/'runs/reentry-daily-tests.log',source/'reentry-daily-tests.log')
    shutil.copy2(ROOT/'tests/test_reentry_daily_protection.py',source/'test_reentry_daily_protection.py')
    originals=[ROOT/'src/trading_system/engine.py',ROOT/'src/trading_system/strategies/reconfirmed_w.py',ROOT/'src/trading_system/strategies/daily_protected_ihs.py',ROOT/'src/trading_system/strategies/__init__.py']
    for p in originals:assert p.read_bytes()==(source/p.relative_to(ROOT)).read_bytes()
    manifest=dict(protocol=load(OUT/'protocol.json'),source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in originals},baseline_exact_reproduction=True,tests=453,completed_cases=8,promoted=False,independent_holdout=False)
    dump(OUT/'manifest.json',manifest)
    print('Report ready',OUT/'report.html')

if __name__=='__main__':main()
