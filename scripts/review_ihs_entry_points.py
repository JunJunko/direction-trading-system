"""Persist observations after visually inspecting all 27 entry-path charts."""
import html,json,re
from statistics import mean,median
from audit_ihs_entry_points import OUT,load,dump,save,pct

NOTES={
1:'短暂回踩后走高，20日末仍上涨10.69%；实际卖出捕获了随后一段上涨。',
2:'20日内先冲高再回落；此时尚未卖出，实际退出发生在本图60日范围之外，不能将图末价格当作卖出价。',
3:'次日起所有日内低点都高于买入价，短期买点较有利；后续回落压缩了实际利润。',
4:'前20日上涨空间很小、走势偏弱，约一个多月后才启动；实际退出后又出现较大上涨，属于时机与退出节奏均需检查的样本。',
5:'先下探再反弹，持有期间收盘曾高于买价6.06%，最终小亏，存在浮盈回吐。',
6:'买入后迅速上涨，20日内最高37.32%、下探3.05%；实际盈利明显，卖出后仍有第二段上涨。',
7:'第一次603901入场后逐步走高；实际卖出后继续冲高，随后转弱。',
8:'买入后短暂盘整即卖出，净赚29元；卖出后上行，20日内最高28.94%，需要查原退出触发，不能归类为入场失败。',
9:'短期冲高后回落，实际仅小幅获利；20日末已低于买价，趋势延续性有限。',
10:'次日起日内低点均高于买价，随后快速上冲；实际获利退出，后期持续回落。',
11:'第二次603901接近局部高位，次日起20日最高仅1.53%，随后下跌；属于入场后迅速失效。',
12:'买入后迅速冲高并获利退出，后续还有反弹但最终回落，不宜仅按后续最高点评价卖出。',
13:'买入后先跌超过5%，未触及较宽初始止损，随后上涨；统一缩紧止损可能丢失这种交易。',
14:'早期回撤小，后续逐步上行；实际卖出后也存在更大上涨，属于较好的买点和待研究的退出节奏。',
15:'买入后先调整，再出现超过10%的盈利机会，最终跌破初始止损；持有收盘峰值11.12%仍未达到约12.63%的价格风险1R，盈利保护启动门槛值得单独检查。',
16:'20日内最高22.63%，收盘峰值19.51%，之后回落为亏损；更接近利润保护问题，而非没有上涨机会。',
17:'买入后连续走弱，3月23日止损，20日最低18.39%出现在该日，随后才大涨至51.17%；不能把止损后的上涨计作原持仓本来能获得的浮盈。',
18:'先经历接近12%的下探才反弹，最终小幅获利；方向正确不等于入场时机舒适。',
19:'短期先涨后跌，20日末已低于买价；实际提前卖出有利于保留部分利润。',
20:'603989在大涨之前先跌至买价下方5.93%，之后20日最高82.08%；实际获利28,116元但后期仍有显著回吐，固定5%止损会与保住该赢家的目标冲突。',
21:'次日起20日连最高价也低于买价，持续下跌；入场后迅速失效，原止损限制了后续更大损失。',
22:'先调整再上涨，实际卖出接近第一轮上冲后段；后续回落，已保留较大部分该轮收益。',
23:'买入后小幅上涨并获利退出，后续深回踩再反弹；降低保护灵敏度未必改善这一笔。',
24:'买入后上冲获利退出，后续又冲高、深回踩再反弹；需要同时看保留利润和多承担的波动。',
25:'早期涨幅有限便小亏退出，后续先继续下跌后反弹；20日最终上涨不代表原退出错误。',
26:'仅14日后续数据，最高上涨0.64%，下探9.72%；止损后反弹接近买价，样本未满20日。',
27:'仅10日后续数据，次日起最高价也略低于含滑点买价；仍持仓，不能作为已完成亏损交易。',
}

def main():
    rs=load(OUT/'entries.json');stats=load(OUT/'statistics.json')
    same=[r for r in rs if r['n60']==60]
    stats['same_21_entries']=[dict(horizon=n,n=len(same),positive=sum(r[f'd{n}_end_return']>0 for r in same),
                                  mean=mean(r[f'd{n}_end_return'] for r in same),median=median(r[f'd{n}_end_return'] for r in same)) for n in (5,10,20,40,60)]
    stats['complete20_excluding603989_mean']=mean(r['d20_end_return'] for r in rs if r['n20']==20 and r['symbol']!='603989.SH')
    reviewed=[]
    for r in rs:
        r['visual_observation']=NOTES[r['number']]
        reviewed.append(dict(number=r['number'],symbol=r['symbol'],chart=r['chart'],reviewed=True,observation=r['visual_observation']))
    dump(OUT/'entries.json',rs);save(OUT/'entries.csv',rs);dump(OUT/'statistics.json',stats);dump(OUT/'chart-review.json',reviewed)
    report=(OUT/'report.html').read_text(encoding='utf-8')
    analysis='''<h2>买点与退出应分开评价</h2><p>25个完整20日样本中，18笔曾涨至少10%，18笔第20日收盘高于买价；但16笔曾跌至买价以下5%，且10笔先触−5%再有其他发展。只有看高低点的先后顺序，才能区分“入场迅速失败”和“调整后才启动”。</p>
<p>8笔已平仓亏损中，603600、002541、001326三笔在实际持仓期间收盘曾分别上涨6.06%、11.12%、19.51%，有明确的浮盈回吐；000586的主要上涨发生在止损之后，不能列入这一类。002271则是退出过早的核查候选：20日内最高28.94%，实际仅净赚29元。</p>
<p>603989大涨前先下探5.93%，说明简单用“先跌5%”评价买点或统一止损，会伤及已知大赢家。该阈值在本报告只是诊断标尺，并未作为策略修改。</p>
<p>同一批有完整60日的21笔交易，20日末涨跌幅中位数为+10.69%，40日为−2.50%，60日为−3.42%；上涨笔数分别14、9、8。排除了不同窗口样本组成的影响后，仍可见中期上涨机会未必能延续。但不能据此直接定20日退出：还需完整账户回测，计入成本、仓位和错过大赢家的代价。</p>
<p>这是反复研究过的开发区间，仅27次实际入场；未与同日可交易股票、指数或匹配对照组比较，也未做独立样本外验证。能够支持“这些买点随后出现了哪些机会及风险”，尚不能单独证明策略有预测增量。</p>'''
    marker='<h2>统一持有观察窗口</h2>'
    report=report.replace(marker,analysis+marker)
    for r in rs:
        needle=f'<a href="{r["chart"]}"><img'
        report=report.replace(needle,f'<p><b>图形核对：</b>{html.escape(r["visual_observation"])}</p>'+needle)
    (OUT/'report.html').write_text(report,encoding='utf-8')
    assert len(rs)==len(reviewed)==len(NOTES)==27
    for target in re.findall(r'(?:href|src)="([^"]+)"',report):
        if not target.startswith('#'):assert (OUT/target).exists(),target
    v=load(OUT/'verification.json');v.update(all_27_charts_visually_reviewed=True,all_report_links_exist=True,same_cohort_checked=True)
    dump(OUT/'verification.json',v)
    print(json.dumps({'chart_reviews':27,'complete_window_arithmetic_checks':len(v['checks']),'same_cohort':stats['same_21_entries'],'links':'passed'},ensure_ascii=False))

if __name__=='__main__':main()
