"""Build a compact Chinese report from completed replay artifacts."""
import sys,json,csv,html,hashlib,statistics
from pathlib import Path
from collections import Counter

def main(path):
    p=Path(path)
    def read(name):
        with (p/(name+'.csv')).open(encoding='utf-8-sig') as f:
            return list(csv.DictReader(f))
    summary=json.loads((p/'summary.json').read_text(encoding='utf-8'))
    manifest=json.loads((p/'manifest.json').read_text(encoding='utf-8'))
    universe=json.loads((p/'universe.json').read_text(encoding='utf-8'))
    events,trades,curve,orders=map(read,['decisions','trades','equity','orders'])
    pnl=[float(r['pnl']) for r in trades]; wins=[v for v in pnl if v>0]; losses=[v for v in pnl if v<0]
    entry=[r for r in events if r['event']=='entry_intent']
    audit=read('entry_audit')
    counts=Counter(r['event'] for r in events)
    rejections=Counter(r.get('reason') for r in orders if r['status']=='rejected')
    rejections.update(r.get('reason') for r in events if r['event']=='entry_rejected')
    summary['rejection_counts']=dict(rejections)
    (p/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    daily=[]
    for date,st in universe['st_by_date'].items():
        listed=[r for r in universe['stocks'] if r['list_date']<=date and (not r.get('delist_date') or date<r['delist_date'])]
        st=set(st)
        daily.append(dict(date=date,listed_mainboard=len(listed),eligible_non_st=sum(r['ts_code'] not in st for r in listed)))
    with (p/'universe_counts.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['date','listed_mainboard','eligible_non_st']);writer.writeheader();writer.writerows(daily)
    code_hash=hashlib.sha256()
    for source in sorted((p/'source/src').rglob('*.py')):
        code_hash.update(str(source.relative_to(p/'source/src')).encode());code_hash.update(source.read_bytes())
    manifest.update(code_sha256=code_hash.hexdigest(),universe_sha256=hashlib.sha256((p/'universe.json').read_bytes()).hexdigest(),
        config_sha256=hashlib.sha256((p/'config.json').read_bytes()).hexdigest(),
        eligible_non_st_daily_min=min(r['eligible_non_st'] for r in daily),
        eligible_non_st_daily_max=max(r['eligible_non_st'] for r in daily),
        subsequently_delisted_candidates=sum(r['list_status']=='D' for r in universe['stocks']))
    last_dates={}
    with (p/'bars.csv').open(encoding='utf-8-sig') as f:
        for r in csv.DictReader(f): last_dates[r['symbol']]=r['date']
    stale=[dict(symbol=r['symbol'],last_bar=last_dates[r['symbol']]) for r in summary['positions'] if last_dates[r['symbol']]<manifest['last_session']]
    metrics=dict(realized_pnl=sum(pnl),average_win=statistics.mean(wins) if wins else None,
        average_loss=statistics.mean(losses) if losses else None,
        payoff_ratio=statistics.mean(wins)/-statistics.mean(losses) if wins and losses else None,
        average_realized_r=statistics.mean(float(t['realized_r']) for t in trades) if trades else None,
        worst_realized_r=min((float(t['realized_r']) for t in trades),default=None),
        best_realized_r=max((float(t['realized_r']) for t in trades),default=None),
        largest_closed_loss=min(pnl,default=0),largest_closed_win=max(pnl,default=0),
        intent_count=counts['entry_intent'],intent_symbols=len({r['symbol'] for r in entry}),
        buy_symbols=len({r['symbol'] for r in orders if r['side']=='buy' and r['status']=='filled'}),
        total_fees=sum(float(r.get('fee') or 0) for r in orders if r['status']=='filled'),
        max_gross_weight=max(float(r['gross_weight']) for r in curve),stale_final_marks=stale,
        entry_audit_count=len(audit),event_counts=dict(counts))
    for name,value in [('manifest',manifest),('evaluation',metrics)]:
        (p/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    def pct(x): return f'{x:.2%}' if x is not None else '无样本'
    def num(x): return f'{x:,.2f}' if x is not None else '无样本'
    items=[('考核交易日',f"{manifest['first_session']}—{manifest['last_session']}（{manifest['sessions']}日）"),
        ('股票池',f"{manifest['stocks']}只；逐日非ST {manifest['eligible_non_st_daily_min']}—{manifest['eligible_non_st_daily_max']}只"),
        ('初始资金',num(summary['initial_cash'])),('期末权益',num(summary['final_equity'])),
        ('总收益',pct(summary['total_return'])),('最大回撤',pct(summary['max_drawdown'])),
        ('买入 / 已平仓 / 期末持仓',f"{summary['filled_buys']} / {summary['closed_trades']} / {summary['open_positions']}"),
        ('平仓胜率',pct(summary['win_rate'])),('利润因子',num(summary['profit_factor'])),
        ('平均盈利 / 平均亏损',f"{num(metrics['average_win'])} / {num(metrics['average_loss'])}"),
        ('实际平均盈亏比',num(metrics['payoff_ratio'])),('平仓平均R',num(metrics['average_realized_r'])),
        ('最大单笔亏损 / 盈利',f"{num(metrics['largest_closed_loss'])} / {num(metrics['largest_closed_win'])}"),
        ('最差 / 最佳单笔R',f"{num(metrics['worst_realized_r'])} / {num(metrics['best_realized_r'])}")]
    unrealized=summary['final_equity']-summary['initial_cash']-metrics['realized_pnl']
    items.extend([('已实现盈亏 / 期末浮盈亏',f"{num(metrics['realized_pnl'])} / {num(unrealized)}")])
    names={r['ts_code']:r['name'] for r in universe['stocks']}
    trade_table='<tr><th>股票</th><th>买入 / 卖出</th><th>净盈亏</th><th>实际R</th></tr>'
    for t in trades:
        trade_table+='<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in
            [names[t['symbol']]+' '+t['symbol'],t['entry_date']+' / '+t['exit_date'],num(float(t['pnl'])),num(float(t['realized_r']))])+'</tr>'
    table=''.join('<tr><th>'+html.escape(k)+'</th><td>'+html.escape(v)+'</td></tr>' for k,v in items)
    values=[float(r['equity']) for r in curve];lo,hi=min(values),max(values);span=hi-lo or 1
    points=' '.join(f'{40+i*920/max(1,len(values)-1):.1f},{250-(v-lo)*210/span:.1f}' for i,v in enumerate(values))
    report=f'''<!doctype html><meta charset="utf-8"><title>主板非 ST 双底回测</title>
<style>body{{font-family:system-ui;max-width:1000px;margin:40px auto;padding:0 24px;color:#263238}}table{{border-collapse:collapse;width:100%}}th,td{{padding:12px;border-bottom:1px solid #ddd;text-align:left}}pre{{white-space:pre-wrap}}svg{{width:100%;background:#f7fafc}}</style>
<h1>主板非 ST {html.escape(manifest['rule_version'])} 全量回测</h1><p>所有股票共用一个100万元账户。2023年起预热，考核开始空仓；参数详见 config.json。</p><table>{table}</table>
<h2>账户净值（{num(lo)}—{num(hi)}元）</h2><svg viewBox="0 0 1000 280"><polyline fill="none" stroke="#176b87" stroke-width="2" points="{points}"/></svg>
<h2>已平仓交易</h2><table>{trade_table}</table><p>期末持仓：{html.escape('、'.join(names[r['symbol']]+' '+r['symbol'] for r in summary['positions'])) or '无'}。已平仓样本 {len(trades)} 笔，期末浮盈亏 {num(unrealized)} 元；不能据此证明长期稳定的小亏大赚。</p>
<h2>执行口径</h2><p>沪深主板A股，上市/退市日期与每日历史ST名单共同筛选；信号日、执行日都复核资格。包含后来退市的候选；持仓变ST不强制平仓，继续执行原止损。佣金、最低5元佣金、卖出印花税及单边0.1%滑点已计入。停牌、涨跌停、T+1与入场日止损歧义按引擎规则处理。</p>
<p>目标价用于入场盈亏比筛选；持仓保护与退出按归档策略代码执行。本轮使用日线内部小结构代替真实小时线，只能评估该研究版本。</p>
<h2>信号与拒单统计</h2><pre>{html.escape(json.dumps(dict(events=metrics['event_counts'],rejections=summary['rejection_counts']),ensure_ascii=False,indent=2))}</pre>
<h2>结果的适用范围</h2><p>日线OHLC保守成交，非逐笔重放；复权采用合成总收益因子调整股数，而非真实分红现金与配股流程。一年样本只能描述这一期间的表现。期末持仓计入浮盈亏，平仓胜率与盈亏比只含已平仓交易。</p>
<p>期末缺少最后一日行情的持仓：{html.escape(json.dumps(stale,ensure_ascii=False))}。若存在，应复核停牌或退市估值。</p>
<p>数据说明：<a href="https://tushare.pro/document/2?doc_id=25">股票列表</a>、<a href="https://tushare.pro/document/2?doc_id=397">历史ST名单</a>、<a href="https://tushare.pro/document/2?doc_id=27">日线</a>。</p>'''
    (p/'performance.html').write_text(report,encoding='utf-8')
    print(json.dumps(dict(summary=summary,evaluation=metrics,manifest=manifest),ensure_ascii=True))
if __name__=='__main__': main(sys.argv[1])
