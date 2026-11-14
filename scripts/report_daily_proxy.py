"""Render diagnostic evidence without using returns to label structures."""
import argparse,csv,html,json,sys
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main(out):
    load=lambda p:json.loads(p.read_text(encoding='utf-8'))
    result=load(out/'result.json');metrics=load(out/'baseline/plan-metrics.json')
    paired=load(out/'paired-plans.json');plan=load(out/'evaluation-plan.json')
    plt.rcParams['font.family']=['Microsoft YaHei','DejaVu Sans']
    plt.rcParams['axes.unicode_minus']=False
    plt.rcParams['font.size']=11
    fig,ax=plt.subplots(figsize=(10,6))
    for passed,color,label in [(False,'#b05252','毛盈亏比≤3'),(True,'#29856e','毛盈亏比>3')]:
        subset=[p for p in metrics if (p['gross_rr']>3)==passed]
        ax.scatter([p['stop_distance_pct']*100 for p in subset],
            [(p['target']-p['trigger'])/p['trigger']*100 for p in subset],c=color,label=label,s=52)
    ax.plot([0,20],[0,60],'--',c='#62748a',label='目标空间＝3×止损距离')
    for p in metrics:
        if p['symbol'] in ('600458.SH','002708.SZ','002602.SZ'):
            ax.annotate(p['symbol'],(p['stop_distance_pct']*100,(p['target']-p['trigger'])/p['trigger']*100),
                xytext=(6,3),textcoords='offset points')
    ax.set(xlabel='初始止损距离／触发价（%）',ylabel='剩余目标空间／触发价（%）',
           title='冻结基线35个计划：价位组合能否提供3倍空间')
    ax.grid(alpha=.2);ax.legend();fig.tight_layout();fig.savefig(out/'space-risk.png',dpi=150);plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,6))
    ax.scatter([p['small_to_core_correction_duration'] for p in metrics],
               [p['small_to_core_correction_range'] for p in metrics],c='#346ca0',s=52)
    ax.set(xlabel='小调整时间／核心调整时间',ylabel='小调整幅度／核心调整幅度',
           title='日线代理：时间较短，幅度未同比缩小')
    ax.grid(alpha=.2);fig.tight_layout();fig.savefig(out/'scale.png',dpi=150);plt.close(fig)
    fig,ax=plt.subplots(figsize=(11,5))
    for i,p in enumerate(paired):
        ax.plot([i-.14,i+.14],[p['baseline_gross'],p['recovery_gross']],c='#939ba3')
    ax.scatter([i-.14 for i in range(len(paired))],[p['baseline_gross'] for p in paired],label='原小B触发',s=45)
    ax.scatter([i+.14 for i in range(len(paired))],[p['recovery_gross'] for p in paired],label='恢复K高点触发',s=45)
    ax.axhline(3,linestyle='--',c='#aa6655');ax.set_xticks(range(len(paired)),[p['symbol'] for p in paired],rotation=25)
    ax.set(ylabel='毛盈亏比',title='固定恢复入场对照：8个共同结构，7个同日、1个更晚')
    ax.grid(axis='y',alpha=.2);ax.legend();fig.tight_layout();fig.savefig(out/'paired.png',dpi=150);plt.close(fig)
    folder=Path(plan['experiment']);frozen=folder/'frozen-baseline'
    baselines=load(out/'baseline/plans.json');symbols={'600458.SH','002708.SZ','002602.SZ'}
    grouped={s:[] for s in symbols}
    with (frozen/'bars.csv').open(encoding='utf-8-sig',newline='') as stream:
        for r in csv.DictReader(stream):
            if r['symbol'] in grouped:grouped[r['symbol']].append(r)
    cases=[]
    for p in baselines:
        if p['symbol'] not in symbols:continue
        e=p['evidence'];rows=sorted([b for b in grouped[p['symbol']] if e['core_a']<=b['date']<=p['date']],key=lambda b:b['date'])
        fig,ax=plt.subplots(figsize=(12,5))
        factor=e['factor'];index={b['date']:i for i,b in enumerate(rows)}
        def value(b,k):return float(b[k])*float(b['factor'])/factor
        for i,b in enumerate(rows):
            o,h,l,c=[value(b,k) for k in ('open','high','low','close')];color='#c64e50' if c>=o else '#2e8d7a'
            ax.vlines(i,l,h,color=color);ax.add_patch(plt.Rectangle((i-.3,min(o,c)),.6,max(abs(c-o),.003),color=color))
        for keys,color,label in [(('core_a','core_b','core_c'),'#346ca0','核心N'),(('small_a','small_b','small_c'),'#8856aa','小N代理')]:
            points=[(index[e[k]],value(rows[index[e[k]]],'high' if k.endswith('b') else 'low')) for k in keys]
            ax.plot(*zip(*points),color=color,label=label)
            for key,(x,y) in zip(keys,points):ax.annotate(key,(x,y),xytext=(3,6),textcoords='offset points',fontsize=9)
        for key,label,color in [('trigger','原触发','#925f18'),('stop','初始止损','#b05252'),('target','目标','#29856e')]:
            ax.axhline(p[key],linestyle='--',c=color,label=f'{label} {p[key]:.3f}')
        alternative=next((r for r in paired if r['setup_id']==p['setup_id']),None)
        if alternative:ax.axhline(alternative['recovery_trigger'],linestyle=':',c='#4c7992',label=f'诊断触发 {alternative["recovery_trigger"]:.3f}')
        ci=index[e['small_confirmed']];ax.axvline(ci,c='#777',linestyle=':')
        ax.set_title(f'{p["symbol"]} 截至 {p["date"]} 已知K线；小C确认日即原计划日')
        step=max(1,len(rows)//7);ticks=list(range(0,len(rows),step))
        ax.set_xticks(ticks,[rows[i]['date'] for i in ticks],rotation=20);ax.grid(alpha=.15);ax.legend(fontsize=9,ncol=3)
        fig.tight_layout();name='case-'+p['symbol']+'.png';fig.savefig(out/name,dpi=150);plt.close(fig);cases.append(name)
    base=result['results']['baseline'];alt=result['results']['D01']
    table=''.join(f'<tr><td>{html.escape(p["symbol"])}</td><td>{p["baseline_date"]}</td><td>{p["recovery_date"]}</td><td>{p["baseline_gross"]:.3f}</td><td>{p["recovery_gross"]:.3f}</td></tr>' for p in paired)
    hourly=''
    real=out/'hourly-case-verification/result.json'
    if real.exists():
        h=load(real);hourly=f'<h2>真实小时对照</h2><p>固定3例：{h["lower_bars"]}根真实小时K，{h["complete_sessions"]}个与原日线OHLC一致的完整交易日；缺失{h["missing_sessions"]}日。日线子账户成交{h["daily_subcohort_summary"]["filled_buys"]}笔，小时入场成交{h["summary"]["filled_buys"]}笔，小时净损益{h["net_pnl"]:.2f}元。仍在日终产生计划、次日用日线执行，并非盘中执行回测。修正了冻结引擎热身期间未及时传入小时行情的缺陷，仅用于本次研究；生产及冻结文件未改。</p>'
    else:
        hourly='<h2>真实小时对照尚未完成</h2><p>已获得600458.SH的30条原始60分钟／竞价记录（6个交易日短窗口）。完整历史请求未成功：当前账户先返回每分钟1次限制，随后返回每小时1次限制，错误码40203。所有失败记录保留；不能据短窗口宣称小时模式更好。<a href="hourly-long-span-probe.json">实际账户限制证据</a>；<a href="https://tushare.pro/document/2?doc_id=370">数据源官方接口说明</a>列出的普通频次不等于当前账户权限。</p>'
    hourly+='<h2>程序时钟的限制</h2><p>引擎按交易日推进，先将当天完成的小时K加入历史，再调用一次策略 on_close；策略又以最后一根日K的日期去重。同一天不能随每根小时K更新计划。小时数据能改变识别的局部结构，但现有流程仍在日终才知道它，订单最早次日执行。真实小时模式的“更早确认”优势并未由当前事件时钟完整表达。</p><p>另发现冻结引擎热身期间先调用策略、之后才加入当日小时K，也未向策略传入小时历史。回归测试证实此信息传递缺陷；研究工具准备了修正，但完整小时对照因数据限制未运行成功，生产及冻结引擎均未修改。</p>'
    page=f'''<!doctype html><meta charset="utf-8"><title>日线小结构代理验证</title>
<style>body{{font:16px system-ui;line-height:1.8;max-width:1250px;margin:30px auto;padding:0 20px;color:#1b2735}}img{{width:100%;max-width:1100px}}td,th{{border:1px solid #ccd;padding:8px}}table{{border-collapse:collapse}}.note{{background:#f2f5f8;padding:18px}}</style>
<h1>日线小结构代理：确认、止损与剩余空间</h1>
<p class="note">已否定“现有35个计划在小C确认后额外拖延”的猜测。止损尺度与目标空间不匹配的现象存在，但还不能认定小时模式一定改善。固定恢复入场对照没有提供改善依据。基线完整复现，原始输入前后哈希一致，生产策略未升级。</p>
<p>样本：原35个计划＋预先已有的E01/E03恢复结构所覆盖的71只股票；没有按事后收益挑股票。每次回放使用当时前缀、既有周线方向和日线核心归属。</p>
<h2>确认是否偏晚</h2><p>35/35小C等待1根日K确认；35/35在确认当天生成计划；35/35核心在其C确认日接受。逐日选中核心下相同小ABC在计划前可用的数量为0。对同一ABC，触发B和止损C固定，确认等待本身不降低预设盈亏比。日线确认与小时确认的时差需要真实小时数据单独衡量。</p>
<h2>止损是否过宽</h2><p>小调整时间／核心时间中位数25.0%，幅度／核心幅度中位数48.2%；初始止损距离中位数6.62%。信号时已使用约52.0%的核心投射涨幅（中位数）。35个计划中只有6个毛比&gt;3；计划当时更晚、更高且仍有效的已确认日线谷为0，不能事后把止损提到未来的谷。较宽不自动意味着错误，真实小时结构能否给出合理的更窄风险须实测。</p>
<img src="space-risk.png"><img src="scale.png">
<h2>固定恢复入场对照 D01</h2><p>保留匹配N和C，要求完成的阳线收盘恢复前K高点、低点不下降，再计划次日突破该恢复K的高点；该触发必须低于原小B。并保留原新鲜性、压力、费用、仓位和持仓规则。这改变入场定义并增加恢复条件，是一次机制诊断，不是所有“更早入场”方法的否定。</p>
<table><tr><th>方案</th><th>计划</th><th>独立空仓净比通过</th><th>实际成交</th><th>净损益</th></tr><tr><td>冻结基线</td><td>35</td><td>6</td><td>2</td><td>-8477.32</td></tr><tr><td>D01</td><td>8</td><td>1</td><td>1</td><td>-4936.84</td></tr></table>
<p>8个共同结构中7个计划同日、1个更晚，没有更早的计划日；触发价格都降低且止损未改变。仅002708形成净比合格的计划并成交，最终仍亏1R。少亏的账户总额不能当作更优：交易数量及持仓组成不同，且没有新样本。独立空仓净比使用固定100万元、相同风险上限；与真实共享账户可通过数量不同。</p>
<img src="paired.png"><table><tr><th>股票</th><th>原计划日</th><th>恢复计划日</th><th>原毛比</th><th>恢复毛比</th></tr>{table}</table>
{hourly}<h2>截至原计划日的结构实例</h2>{''.join('<img src="'+name+'">' for name in cases)}
<h2>书中依据与下一步界线</h2><p>《持续盈利》第二部分“节奏点交易的实战原则”（约560行起）要求次级折返之后等待进攻信号，并区分形态外节奏与途中中继，按各自核心周期衡量空间；系统提要（1289—1299行）明确周—日—小时架构、节奏失败为初始止损及报酬风险比&gt;3。不能为了增加成交，把止损随意收紧，或改用周线更远目标给日线途中入场凑空间。</p>
<p>继续验证小时节奏时须分别检验：结构/确认更早是否真实可观察、风险更小是否来自该节奏的实际失效边界，以及日终识别是否错过盘中可提交订单的时点。日线数据无法唯一还原这些信息。</p>
<p><a href="baseline/plan-metrics.json">35条逐计划诊断</a> · <a href="paired-plans.json">8条配对对照</a> · <a href="D01/trades.csv">D01交易明细</a> · <a href="result.json">完整结果</a> · <a href="evaluation-plan.json">结果前固定的实验定义</a></p>'''
    (out/'report.html').write_text(page,encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path)
    main(parser.parse_args().output)
