"""Compare completed experiments with identical frozen data and account rules."""
import csv,html,json,statistics,sys
from collections import Counter
from pathlib import Path


def read_rows(path):
    with path.open(encoding='utf-8-sig') as f:return list(csv.DictReader(f))


def analyze(path):
    summary=json.loads((path/'summary.json').read_text(encoding='utf-8'))
    manifest=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    trades=read_rows(path/'trades.csv')
    gains=[float(t['pnl']) for t in trades if float(t['pnl'])>0]
    losses=[float(t['pnl']) for t in trades if float(t['pnl'])<0]
    metric=dict(version=manifest['rule_version'],total_return=summary['total_return'],
        drawdown=summary['max_drawdown'],buys=summary['filled_buys'],closed=len(trades),
        open=summary['open_positions'],wins=len(gains),losses=len(losses),
        win_rate=summary['win_rate'],profit_factor=summary['profit_factor'],
        realized_pnl=sum(float(t['pnl']) for t in trades),
        average_win=statistics.mean(gains) if gains else None,
        average_loss=statistics.mean(losses) if losses else None,
        payoff=statistics.mean(gains)/-statistics.mean(losses) if gains and losses else None,
        best_r=max((float(t['realized_r']) for t in trades),default=None),
        worst_r=min((float(t['realized_r']) for t in trades),default=None),
        average_r=statistics.mean(float(t['realized_r']) for t in trades) if trades else None,
        exit_reasons=dict(Counter(t['reason'] for t in trades)),
        direction_confirmations=summary['event_counts'].get('upper_direction_confirmed',0),
        entry_plans=summary['event_counts'].get('entry_intent',0))
    return dict(path=str(path.resolve()),manifest=manifest,metrics=metric,trades=trades)


def main(paths):
    runs=[analyze(Path(p)) for p in paths]
    baseline=runs[0]['manifest']
    def account_rules(path):
        config=json.loads((Path(path)/'config.json').read_text(encoding='utf-8'))
        for strategy in config['strategies']:
            strategy.pop('id',None);strategy['params'].pop('retest_mode',None)
            strategy['params'].pop('candidate_mode',None)
            strategy['params'].pop('core_mode',None)
            strategy['params'].pop('holding_scale_mode',None)
        return config
    rules=account_rules(paths[0])
    for run in runs[1:]:
        for key in ('bars_sha256','stocks','first_session','last_session','sessions'):
            if run['manifest'][key]!=baseline[key]:raise ValueError('Incomparable data: '+key)
        if account_rules(run['path'])!=rules:raise ValueError('Other strategy or account rules changed')
    p=Path(paths[-1]);(p/'comparison.json').write_text(json.dumps(runs,ensure_ascii=False,indent=2),encoding='utf-8')
    esc=lambda x:html.escape(str(x))
    labels=[('total_return','总收益'),('drawdown','最大回撤'),('buys','买入笔数'),('closed','平仓笔数'),
        ('open','期末持仓'),('wins','盈利笔数'),('losses','亏损笔数'),('win_rate','胜率'),
        ('profit_factor','利润因子'),('realized_pnl','已实现净盈亏'),('average_win','平均盈利'),
        ('average_loss','平均亏损'),('payoff','平均盈亏比'),('best_r','最佳单笔R'),
        ('worst_r','最差单笔R'),('average_r','平均单笔R'),('direction_confirmations','方向确认事件'),('entry_plans','入场计划')]
    content=['<!doctype html><meta charset="utf-8"><title>双底回踩规则全量对照</title>',
        '<style>body{font:16px system-ui;max-width:1400px;margin:30px auto}table{border-collapse:collapse;width:100%}th,td{padding:9px;border-bottom:1px solid #ddd;text-align:left}pre{white-space:pre-wrap}</style>',
        '<h1>双底回踩规则全量对照</h1>',
        '<p>同一冻结行情、主板历史上市及每日非ST股票池、共用100万元账户、相同风险与费用。2023年起预热，考核开始空仓。实际考核 '+esc(baseline['first_session'])+'—'+esc(baseline['last_session'])+'。数据已用于研究，属于样本内比较；daily_nested 不是实际小时线。</p>',
        '<table><tr><th>指标</th>'+''.join('<th>'+esc(r['metrics']['version'])+'</th>' for r in runs)+'</tr>']
    for key,title in labels:
        vals=[]
        for run in runs:
            value=run['metrics'][key]
            vals.append('无样本' if value is None else f'{value:.2%}' if key in ('total_return','drawdown','win_rate') else f'{value:,.2f}' if isinstance(value,float) else str(value))
        content.append('<tr><th>'+title+'</th>'+''.join('<td>'+esc(v)+'</td>' for v in vals)+'</tr>')
    content.append('</table>')
    last=runs[-1]['metrics']
    content.append('<h2>本轮结果的含义</h2><p>最后版本已实现净盈亏 '+
        f"{last['realized_pnl']:,.2f}"+' 元，期末持仓 '+str(last['open'])+
        ' 个。成交样本仍少，收益转正不能证明系统已稳定实现少数大盈利覆盖多次小亏损；默认实盘配置未替换。</p>')
    diagnostic_path=p/'profit-diagnostics.json'
    if diagnostic_path.exists():
        diagnostic=json.loads(diagnostic_path.read_text(encoding='utf-8'))
        content.append('<h2>最后版本的利润回吐诊断</h2><p>峰值为退出日前持仓期间的最高收盘毛浮盈，按初始风险折算；实现R含费用。峰值不代表当时一定能够实现的收益，不含盘中最高价。</p><table><tr><th>股票</th><th>峰值收盘日</th><th>峰值收盘毛浮盈R</th><th>实现净R</th><th>退出原因</th></tr>')
        for trade in diagnostic['trades']:
            content.append('<tr>'+''.join('<td>'+esc(value)+'</td>' for value in
                [trade['symbol'],trade['peak_close_date'],f"{trade['peak_close_gross_r']:.2f}",
                 f"{trade['realized_r']:.2f}",trade['exit_reason']])+'</tr>')
        content.append('</table>')
    def identity(trade):return trade['symbol'],trade['entry_date']
    for before,after in zip(runs,runs[1:]):
        old={identity(t):t for t in before['trades']};new={identity(t):t for t in after['trades']}
        removed=[old[k] for k in old.keys()-new.keys()]
        added=[new[k] for k in new.keys()-old.keys()]
        changed=[dict(before=old[k],after=new[k]) for k in old.keys()&new.keys()
                 if any(old[k][field]!=new[k][field] for field in ('exit_date','quantity','pnl','reason'))]
        content.append('<h2>'+esc(before['metrics']['version'])+' → '+esc(after['metrics']['version'])+
            ' 成交变化</h2><pre>'+esc(json.dumps(dict(removed=removed,added=added,changed=changed),ensure_ascii=False,indent=2))+'</pre>')
    for run in runs:
        content.append('<h2>'+esc(run['metrics']['version'])+'：逐笔成交</h2><table><tr><th>股票</th><th>买入</th><th>卖出</th><th>净盈亏</th><th>R</th><th>退出原因</th></tr>')
        for trade in run['trades']:
            content.append('<tr>'+''.join('<td>'+esc(trade[k])+'</td>' for k in ('symbol','entry_date','exit_date','pnl','realized_r','reason'))+'</tr>')
        content.append('</table><p>退出原因统计：'+esc(json.dumps(run['metrics']['exit_reasons'],ensure_ascii=False))+'</p>')
    (p/'comparison.html').write_text('\n'.join(content),encoding='utf-8')
    print(json.dumps([r['metrics'] for r in runs],ensure_ascii=True))


if __name__=='__main__':main(sys.argv[1:])
