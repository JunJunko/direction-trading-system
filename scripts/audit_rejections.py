"""Audit historical flat-account runs without changing the original artifacts."""
import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.analysis import adjusted,pivot_lows,weekly
from trading_system.data import load_csv,save_csv
from trading_system.domain import Intent
from trading_system.risk import RiskManager


def read_csv(path):
    if not path.exists() or not path.stat().st_size:
        return []
    with path.open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('--output',default='audits')
    args=parser.parse_args()
    run=Path(args.run)
    config=json.loads((run/'config.json').read_text())
    summary=json.loads((run/'summary.json').read_text())
    events=read_csv(run/'decisions.csv')
    bars=load_csv(run/'bars.csv')
    by_key={(b.symbol,b.date):b for b in bars}
    calendar=json.loads((run/'calendar.json').read_text())
    ends=set(calendar['week_ends'])
    audits=read_csv(run/'entry_audit.csv')
    if not audits and summary['filled_buys']:
        raise ValueError('Legacy non-flat runs require recorded historical account state; refusing fabricated sizing')
    if not audits:
        risk=RiskManager(config['risk'])
        for e in events:
            if e['event']!='entry_intent':
                continue
            execution=next(x for x in events if x['setup_id']==e['setup_id']
                           and x['date']>e['date'] and x.get('trigger'))
            b=by_key[e['symbol'],execution['date']]
            i=Intent(e['strategy'],e['symbol'],e['date'],float(e['trigger']),float(e['stop']),
                     float(e['target']),e['setup_id'],'audit')
            slip=config['execution']['slippage']
            fill=max(b.open,i.trigger)*(1+slip)
            ex=config['execution']
            tax=ex['sell_tax_after_20230828'] if b.date>='20230828' else ex['sell_tax_before_20230828']
            assessed=risk.assess(i,fill,config['initial_cash'],config['initial_cash'],{}, {},
                                 ex['commission_rate'],tax,slippage=slip)
            audits.append(dict(assessed,date=b.date,symbol=b.symbol,strategy=e['strategy'],
                               signal_date=e['date'],setup_id=i.setup_id,trigger=i.trigger,
                               stop=i.stop,target=i.target,open=b.open,high=b.high,low=b.low,
                               up_limit=b.up_limit,execution_reason=execution['event'],
                               fill_within_bar=b.low<=fill<=b.high,
                               fill_below_up_limit=fill<b.up_limit,
                               audit_method='flat-account reconstruction from frozen bars and config'))
    for row in audits:
        setup=next(x for x in events if x['setup_id']==row['setup_id'] and x['event']=='double_bottom_breakout')
        retest=next(x for x in events if x['setup_id']==row['setup_id'] and x['event']=='retest_observed')
        history=[b for b in bars if b.symbol==row['symbol'] and b.date<=setup['date']]
        spec=next(s for s in config['strategies'] if s['id']==row['strategy'])
        p=spec.get('params',{})
        upper=weekly(adjusted(history),ends) if p.get('direction_cycle','weekly')=='weekly' else adjusted(history)
        pivots=pivot_lows(upper,p.get('left',2),p.get('right',2))
        between=[upper[i].date for i in pivots if setup['first_bottom']<upper[i].date<setup['second_bottom']]
        row.update(first_bottom=setup['first_bottom'],second_bottom=setup['second_bottom'],
                   breakout_date=setup['date'],retest_date=retest['date'],
                   intermediate_pivot_count=len(between),intermediate_pivots=';'.join(between),
                   raw_3r_price=float(row['fill'])+3*(float(row['fill'])-float(row['stop'])))
    output=Path(args.output)/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-'+run.name)
    output.mkdir(parents=True)
    save_csv(output/'entry_audit.csv',audits)
    lines=['# 入场拒绝逐笔审计','',f'来源：`{run.resolve()}`','',
           '旧版未成交记录按原始行情和配置重建平仓账户风险评估；不将未成交订单称为已发生的交易。',
           '', '| 次日日期 | 股票 | 拟成交价 | 止损 | 目标 | 毛RR | 净RR | 日高 | 涨停价 | 中间波谷数 | 原拒绝原因 |',
           '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for r in audits:
        number=lambda key:f'{float(r[key]):.4f}' if r.get(key) not in ('',None) else '—'
        lines.append('| '+' | '.join([r['date'],r['symbol'],number('fill'),number('stop'),number('target'),
                     number('gross_rr'),number('net_rr'),number('high'),number('up_limit'),
                     str(r['intermediate_pivot_count']),r['execution_reason']])+' |')
    lines.extend(['','完整数量、费用、风险预算、结构日期与成交标记见同目录 entry_audit.csv。'])
    (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(output.resolve()),entries=len(audits)),ensure_ascii=False))


if __name__=='__main__':
    main()
