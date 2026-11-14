"""Audit a completed frozen v5.15 run and build full/cohort comparisons."""
import argparse
import copy
import csv
import html
import json
import math
import shutil
import statistics
import sys
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Bar
from trading_system.engine import Backtest
from trading_system.strategies import build_strategies
from trading_system.universe import MainboardUniverse
from trading_system.data import save_csv


def read(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def load(p):return json.loads(p.read_text(encoding='utf-8'))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')


def audit_plan(p,history):
    e=p['evidence'];known={b.date:b for b in history if b.date<=p['date']}
    anchor=known[p['date']].factor
    def price(b,k):return getattr(b,k)*b.factor/anchor
    ordered=[known[d] for d in sorted(known)]
    ix={b.date:i for i,b in enumerate(ordered)};index=ix[e['support_band_known_at']]
    ranges=[max(price(ordered[i],'high')-price(ordered[i],'low'),
                abs(price(ordered[i],'high')-price(ordered[i-1],'close')),
                abs(price(ordered[i],'low')-price(ordered[i-1],'close')))
            for i in range(index-13,index+1)]
    atr=sum(ranges)/14;source=known[e['support_source_date']]
    original=price(source,'low');upper=min(price(source,'open'),price(source,'close'))
    floor=max(original,upper-.15*atr)
    for a,b in ((atr,e['support_reference_atr']),(original,e['support_lower']),
                (upper,e['support_upper']),(floor,p['stop'])):
        assert math.isclose(a,b,rel_tol=1e-11,abs_tol=1e-11),(p['setup_id'],a,b)
    current=known[p['date']];stand=known[e['support_stand_date']]
    assert e['support_source_date']<e['support_band_known_at']<=e['support_stand_date']<e['support_retest_date']==p['date']
    assert price(stand,'low')>upper and floor<price(current,'low')<=upper
    assert price(current,'close')>max(upper,price(stand,'close'),price(current,'open'))
    assert (upper-floor)/upper<=.005+1e-12
    assert (p['trigger']-p['stop'])/p['trigger']<=.01+1e-12
    assert p['trigger']==e['rebound_signal_close']
    return dict(symbol=p['symbol'],date=p['date'],setup_id=p['setup_id'],
        support_lower=original,support_upper=upper,defense_lower=floor,defense_upper=upper,
        band_width=(upper-floor)/upper,signal_price=p['trigger'],target=p['target'],known_at=e['support_band_known_at'])


def audit_fills(audits,ex):
    rr=distance=filled=0
    for r in audits:
        if r.get('support_entry_distance'):
            d=(float(r['fill'])-float(r['stop']))/float(r['fill'])
            assert math.isclose(d,float(r['support_entry_distance']),abs_tol=1e-12)
            if r['risk_reason']=='approved' or r['execution_reason']=='filled':assert d<=.01+1e-12
            distance+=1
        if r['execution_reason']=='filled':
            assert r['date']>r['signal_date'] and r['entry_order']=='next_open'
            assert math.isclose(float(r['fill']),float(r['open'])*(1+ex['slippage']),rel_tol=1e-12)
            assert float(r['net_rr'])>3
            filled+=1
        if not r.get('net_rr'):continue
        q=float(r['candidate_quantity']);entry=float(r['fill'])
        stop=float(r['stop'])*(1-ex['slippage']);target=float(r['target'])*(1-ex['slippage'])
        tax=ex['sell_tax_after_20230828'] if r['date']>='20230828' else ex['sell_tax_before_20230828']
        fee=lambda value,sell:max(ex['minimum_commission'],value*ex['commission_rate'])+(value*tax if sell else 0)
        profit=q*(target-entry)-fee(q*entry,False)-fee(q*target,True)
        loss=q*(entry-stop)+fee(q*entry,False)+fee(q*stop,True)
        assert math.isclose(profit/loss,float(r['net_rr']),abs_tol=1e-11,rel_tol=1e-11)
        rr+=1
    return dict(fee_inclusive_rr_audits=rr,price_distance_audits=distance,next_open_fills=filled)


def post_stop(trades,audits,grouped,calendar,last):
    fills={r['setup_id']:r for r in audits if r['execution_reason']=='filled'}
    dates={d:i for i,d in enumerate(calendar)};rows=[]
    for t in trades:
        if not t['reason'].endswith('support_band_break'):continue
        a=fills[t['setup_id']];raw={b.date:b for b in grouped[t['symbol']]}
        factor=raw[t['entry_date']].factor
        normalized=lambda b,key:getattr(b,key)*b.factor/factor
        index=dates[t['exit_date']];following=calendar[index+1:index+6]
        complete=len(following)==5 and all(d<=last and d in raw and raw[d].volume>0 for d in following)
        r=dict(symbol=t['symbol'],setup_id=t['setup_id'],exit_date=t['exit_date'],reason=t['reason'],
            pnl=float(t['pnl']),complete_5_sessions=complete,recovered_entry=None,reached_target=None,original_floor_intact=None)
        if complete:
            window=[raw[t['exit_date']]]+[raw[d] for d in following]
            intact=min(normalized(b,'low') for b in window)>float(a['support_lower'])
            high=max(normalized(raw[d],'high') for d in following)
            r.update(original_floor_intact=intact,recovered_entry=intact and high>=float(a['fill']),
                reached_target=intact and high>=float(a['target']))
        rows.append(r)
    complete=[r for r in rows if r['complete_5_sessions']]
    return rows,dict(band_exit_count=len(rows),complete_5_session_windows=len(complete),incomplete_windows=len(rows)-len(complete),
        intact_floor_recovered_entry=sum(r['recovered_entry'] for r in complete),
        intact_floor_reached_target=sum(r['reached_target'] for r in complete),
        recovered_entry_rate=sum(r['recovered_entry'] for r in complete)/len(complete) if complete else None)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output');args=parser.parse_args()
    out=Path(args.output);cfg=load(out/'config.json');plans=load(out/'plans.json');summary=load(out/'summary.json')
    assert load(out/'status.json')['status']=='complete'
    protocol=load(out/'sweep-protocol.json');assert protocol['post_stop_horizon_sessions']==5
    cal=load(out/'calendar.json');ud=load(out/'universe.json')
    cohort=ROOT/'runs/20261023-support-rebound-cohort-verified';cohort_symbols=set(load(cohort/'symbols.json'))
    needed={p['symbol'] for p in plans};grouped=defaultdict(list)
    with (out/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in needed:grouped[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in
                ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    for bars in grouped.values():bars.sort(key=lambda b:b.date)
    plan_rows=[audit_plan(p,grouped[p['symbol']]) for p in plans]
    save_csv(out/'band-plans.csv',plan_rows)
    audits=read(out/'entry_audit.csv');trades=read(out/'trades.csv');curve=read(out/'equity.csv')
    checks=audit_fills(audits,cfg['execution'])
    checks.update(all_plan_bands_independently_verified=len(plans),all_population=load(out/'account-verification.json'))
    sweeps,sweep_metrics=post_stop(trades,audits,grouped,cal['open_dates'],'20260930')
    save_csv(out/'post-stop-5-sessions.csv',sweeps)
    # Same 62-symbol opportunity universe as v5.14; replay only its new signal stocks.
    selected=[p for p in plans if p['symbol'] in cohort_symbols];selected_symbols={p['symbol'] for p in selected}
    bars=sorted((b for sym in selected_symbols for b in grouped[sym]),key=lambda b:(b.date,b.symbol))
    universe=MainboardUniverse(ud['stocks'],ud['st_by_date'])
    matched=Backtest(copy.deepcopy(cfg),build_strategies(cfg['strategies'])).run(bars,cal['open_dates'],set(cal['week_ends']),
        evaluation_start='20251009',evaluation_end='20260930',universe=universe)
    actual={e['setup_id']:(e['date'],e['trigger'],e['stop'],e['target']) for e in matched.events if e['event']=='entry_intent'}
    assert actual=={p['setup_id']:(p['date'],p['trigger'],p['stop'],p['target']) for p in selected}
    folder=out/'matched-62';folder.mkdir(exist_ok=True)
    for name,records in [('orders',matched.orders),('trades',matched.trades),('equity',matched.curve),('entry_audit',matched.entry_audits)]:save_csv(folder/(name+'.csv'),records)
    dump(folder/'summary.json',matched.summary())
    checks['matched_cohort_signal_equivalence']=True
    counts=load(out/'signal-counts.json')
    fills=[r for r in audits if r['execution_reason']=='filled']
    metrics=dict(summary,net_pnl=summary['final_equity']-summary['initial_cash'],
        first_plans=len(plans),plan_stocks=len(needed),risk_reasons=dict(Counter(r['risk_reason'] for r in audits)),
        execution_reasons=dict(Counter(r['execution_reason'] for r in audits)),exit_reasons=dict(Counter(r['reason'] for r in trades)),
        median_band_width=statistics.median(r['band_width'] for r in plan_rows) if plan_rows else None,
        median_filled_price_risk=statistics.median(float(r['support_entry_distance']) for r in fills) if fills else None,
        median_filled_net_rr=statistics.median(float(r['net_rr']) for r in fills) if fills else None,
        actual_wins=sum(float(t['pnl'])>0 for t in trades),actual_losses=sum(float(t['pnl'])<0 for t in trades),
        sweeps=sweep_metrics)
    assessment=dict(full_population=dict(v5_12=load(ROOT/'runs/20261022-mainboard-daily-direction/summary.json'),
        v5_13=load(ROOT/'runs/20261022-mainboard-support-zone/summary.json'),v5_15=metrics),
        matched_62=dict(v5_14=load(cohort/'candidate/summary.json'),v5_15=matched.summary()),
        verification=checks,post_stop=sweeps,signal_wait_reasons=counts['reasons'])
    dump(out/'assessment.json',assessment)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif']=['Microsoft YaHei','DejaVu Sans'];plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(2,1,figsize=(11,6.8),sharex=True,gridspec_kw={'height_ratios':[2,1]})
    for data,label,color in [(read(ROOT/'runs/20261022-mainboard-daily-direction/equity.csv'),'日线突破 v5.12','#607d8b'),
                            (read(ROOT/'runs/20261022-mainboard-support-zone/equity.csv'),'支撑过滤 v5.13','#aab6ba'),
                            (curve,'窄防守带 v5.15','#176b87')]:
        x=[datetime.strptime(r['date'],'%Y%m%d') for r in data]
        axes[0].plot(x,[float(r['equity'])/cfg['initial_cash'] for r in data],label=label,color=color,lw=1.5)
        axes[1].plot(x,[100*float(r['drawdown']) for r in data],color=color,lw=1.3)
    axes[0].legend(frameon=False);axes[0].set_ylabel('账户净值');axes[1].set_ylabel('回撤（%）')
    axes[0].set_title('3,214只股票共享账户：固定参数窄防守带实验',loc='left',fontsize=12)
    for ax in axes:ax.grid(alpha=.2);ax.spines[['top','right']].set_visible(False)
    fig.autofmt_xdate();fig.tight_layout();fig.savefig(out/'equity-comparison.png',dpi=160);plt.close(fig)
    esc=lambda v:html.escape(str(v))
    def fmt(v,percent=False):
        if v is None:return '无样本'
        if percent:return f'{v:.2%}'
        return f'{v:,.2f}' if isinstance(v,float) else str(v)
    names={r['ts_code']:r.get('name','') for r in ud['stocks']}
    wait_labels=dict(support_defense_band_not_narrow='防守带宽度不合格（零宽或超过0.5%）',
        waiting_after_support_confirmation='仍在首次支撑确认当日，等待后续K线',
        no_upper_edge_retest='没有回踩支撑区上沿',upper_edge_not_previously_held='前一根K线未完全站稳上沿',
        upper_edge_recovery_not_confirmed='回踩后未满足收回及收阳条件',support_already_touched='原支撑下沿已触及',
        defense_band_breached_during_confirmation='确认期间已触及防守带下沿')
    lead=(f"买入 {summary['filled_buys']} 笔，平仓 {summary['closed_trades']} 笔，净盈亏 {fmt(metrics['net_pnl'])} 元，收益 {fmt(summary['total_return'],True)}，最大回撤 {fmt(abs(summary['max_drawdown']),True)}。"
          if summary['filled_buys'] else '本轮零成交，账户保持现金，收益及回撤均为零；这不能证明止损方式有效。')
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>窄防守带全量回测</title>',
        '<style>body{font:16px/1.65 system-ui,"Microsoft YaHei";max-width:1200px;margin:36px auto;padding:0 24px;color:#23323e}h1{font-size:28px}h2{font-size:21px;margin-top:32px}table{border-collapse:collapse;width:100%;margin:16px 0}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #dce3e7}th{background:#f3f6f8}img{width:100%}a{color:#176b87}.note{padding:14px 18px;background:#edf4f7;border-radius:6px}.scroll{overflow:auto}</style>',
        '<h1>v5.15 支撑上沿回踩与窄防守带：全量回测</h1>',
        '<p>3,214只股票、2,856,672根日线，2023-01-03起预热，2025-10-09至2026-09-30考核241个交易日。100万元共享账户，按信号日与执行日的历史上市、退市和ST状态过滤。</p>',
        '<p class="note">'+lead+'</p>',
        '<p>规则固定为：支撑上沿已站稳，回踩上沿并收回后，次日开盘执行；防守带下沿=max(原支撑底，上沿−0.15×支撑确认时14根平均真实波幅)，宽度≤0.5%；成交价到退出线≤1%，含费用净盈亏比严格>3。触及防守带下沿触发全退，当日不可卖或跌停时保留退出状态。本轮没有根据收益调参。</p>',
        '<h2>同一全市场范围对照</h2><p>v5.15相对v5.13同时改变入场、回踩确认、止损定义和距离限制，是整体规则对照。</p>',
        '<table><tr><th>指标</th><th>v5.12 日线突破</th><th>v5.13 支撑过滤</th><th>v5.15 窄防守带</th></tr>']
    fields=[('final_equity','期末权益',False),('total_return','收益率',True),('max_drawdown','最大回撤',True),
            ('filled_buys','买入数',False),('closed_trades','平仓数',False),('open_positions','期末持仓',False),('win_rate','实际平仓胜率',True),('profit_factor','利润因子',False)]
    for field,label,percent in fields:
        parts.append('<tr><th>'+label+'</th>'+''.join('<td>'+fmt(assessment['full_population'][k].get(field),percent)+'</td>' for k in ('v5_12','v5_13','v5_15'))+'</tr>')
    parts+=['</table><img src="equity-comparison.png" alt="全市场共享账户净值及回撤">',
        '<h2>相同62股范围：与v5.14止跌入场比较</h2><p>此处独立共享账户只允许上轮固定62股机会。v5.14为已冻结核验结果，v5.15以全量扫描中属于该范围的信号重新重放账户；两者信号集合重新核对。不能将这张表与全市场收益直接比较。</p>',
        '<table><tr><th>指标</th><th>v5.14 止跌入场</th><th>v5.15 窄防守带</th></tr>']
    for field,label,percent in fields:
        parts.append('<tr><th>'+label+'</th>'+''.join('<td>'+fmt(assessment['matched_62'][k].get(field),percent)+'</td>' for k in ('v5_14','v5_15'))+'</tr>')
    parts+=['</table><h2>信号、审核与止损距离</h2>',f"<p>首次计划 {len(plans)} 个，涉及 {len(needed)} 只股票。计划防守带宽度中位数 {fmt(metrics['median_band_width'],True)}；实际成交价到初始退出线中位数 {fmt(metrics['median_filled_price_risk'],True)}，成交时净盈亏比中位数 {fmt(metrics['median_filled_net_rr'])}。</p>",
        '<p>以下均为观察事件次数，同一结构可能在多个日期重复等待；不能当成独立计划数量或直接计算筛选比例。</p>',
        '<table><tr><th>环节</th><th>原因</th><th>次数</th></tr>']
    for kind in ('risk_reasons','execution_reasons','exit_reasons'):
        for reason,n in metrics[kind].items():parts.append('<tr><td>'+kind+'</td><td>'+esc(reason)+'</td><td>'+str(n)+'</td></tr>')
    for r in counts['reasons']:
        if r['event']=='support_rebound_wait':parts.append('<tr><td>结构等待</td><td>'+esc(wait_labels.get(r['reason'],r['reason']))+'</td><td>'+str(r['count'])+'</td></tr>')
    for r in [r for r in counts['reasons'] if r['event'] in ('core_structure_wait','rhythm_wait')][:10]:
        parts.append('<tr><td>'+esc(r['event'])+'</td><td>'+esc(r['reason'])+'</td><td>'+str(r['count'])+'</td></tr>')
    parts.append('</table>')
    if not plans:
        parts.append('<p class="note">本轮没有形成入场计划，因而尚未进入1%距离、3:1净盈亏比和资金审核。零成交首先反映计划生成条件的限制；不能归因于账户预算不足或盈亏比审核拒绝，也没有止损交易可用于评估扫损。</p>')
    parts+=['<h2>窄带退出后5个交易日</h2>',
        '<p>事前固定定义：退出日到之后5个交易日，原支撑底全程未破，且之后5日最高价重新达到入场价；另统计达到原目标价。必须有完整5日正成交量行情，否则单列不完整样本。这是后续价格路径描述，不是重新买回或继续持有的可兑现收益。</p>',
        f"<p>窄带退出 {sweep_metrics['band_exit_count']} 笔；完整观察 {sweep_metrics['complete_5_session_windows']} 笔，不完整 {sweep_metrics['incomplete_windows']} 笔。原支撑未破且回到入场价 {sweep_metrics['intact_floor_recovered_entry']} 笔（{fmt(sweep_metrics['recovered_entry_rate'],True)}）；达到原目标价 {sweep_metrics['intact_floor_reached_target']} 笔。</p>",
        '<h2>逐笔平仓</h2><div class="scroll"><table><tr><th>股票</th><th>买入</th><th>卖出</th><th>净盈亏</th><th>实际R</th><th>退出原因</th></tr>']
    for t in trades:
        parts.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [t['symbol']+' '+names.get(t['symbol'],''),t['entry_date'],t['exit_date'],fmt(float(t['pnl'])),fmt(float(t['realized_r'])),t['reason']])+'</tr>')
    if not trades:parts.append('<tr><td colspan="6">无已平仓交易</td></tr>')
    parts+=['</table></div><h2>全部首次防守带</h2><div class="scroll"><table><tr><th>股票</th><th>计划日期</th><th>原支撑区</th><th>防守带</th><th>带宽</th><th>信号参考价</th><th>目标价</th></tr>']
    for r in plan_rows:
        parts.append('<tr>'+''.join('<td>'+esc(v)+'</td>' for v in [r['symbol']+' '+names.get(r['symbol'],''),r['date'],f"{r['support_lower']:.3f}～{r['support_upper']:.3f}",f"{r['defense_lower']:.3f}～{r['defense_upper']:.3f}",fmt(r['band_width'],True),fmt(r['signal_price']),fmt(r['target'])])+'</tr>')
    parts+=['</table></div><h2>验证与适用范围</h2>',
        f"<p>239项回归测试与6项报告检查通过。实际可核验的首次防守带、ATR和确认时点共 {checks['all_plan_bands_independently_verified']} 个计划；含费用盈亏比 {checks['fee_inclusive_rr_audits']} 条、距离审核 {checks['price_distance_audits']} 条、次日开盘成交 {checks['next_open_fills']} 笔。零计划时这些检查没有真实样本，执行机制由构造测试验证。扫描计划与共享账户重算一致，旧全量v5.13账户精确复现。</p>",
        '<p class="note">此区间已多次用于研究，本轮为固定参数的样本内实验，没有独立保留样本。日线小结构代理不能代表真实小时入场，日线OHLC不能验证秒级成交。1%是初始价格距离，费用、滑点、跳空、当日不可卖和跌停可能使实际亏损更大。公司行动仍采用合成总收益因子调整。实际平仓胜率与旧68个计划的目标先到率不同，不能混用。</p>',
        '<p><a href="assessment.json">完整统计</a> · <a href="band-plans.csv">全部防守带</a> · <a href="entry_audit.csv">入场审核</a> · <a href="trades.csv">逐笔平仓</a> · <a href="post-stop-5-sessions.csv">退出后5日</a> · <a href="sweep-protocol.json">事前后续路径口径</a> · <a href="manifest.json">指纹与范围</a></p></html>']
    (out/'report.html').write_text('\n'.join(parts),encoding='utf-8')
    shutil.copy2(__file__,out/'source/report_support_band.py')
    print(json.dumps(dict(metrics=metrics,matched_62=assessment['matched_62'],checks=checks),ensure_ascii=True))


if __name__=='__main__':main()
