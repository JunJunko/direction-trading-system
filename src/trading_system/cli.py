import argparse
import hashlib
import html
import json
import shutil
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from .data import TushareSource,load_csv,save_csv,load_intraday_csv
from .demo import demo_data
from .engine import Backtest
from .strategies import build_strategies
from .universe import MainboardUniverse


def main():
    parser=argparse.ArgumentParser(description='Direction framework research backtest')
    parser.add_argument('mode',choices=['demo','tushare','csv'])
    parser.add_argument('--config',default='configs/double_bottom_v3.json')
    parser.add_argument('--symbols',nargs='+',default=['000001.SZ','600000.SH','600036.SH'])
    parser.add_argument('--start',default='20200101')
    parser.add_argument('--end',default='20260930')
    parser.add_argument('--csv')
    parser.add_argument('--calendar',help='JSON with open_dates and week_ends for CSV input')
    parser.add_argument('--lower-csv',help='Completed hourly bars, timestamps YYYYMMDDHHMMSS')
    parser.add_argument('--evaluation-start',help='Start with a flat account after causally warming earlier data, YYYYMMDD')
    parser.add_argument('--evaluation-end',help='Last evaluation date, YYYYMMDD')
    parser.add_argument('--output',default='runs')
    parser.add_argument('--universe',help='Dated mainboard stock metadata and ST coverage JSON')
    args=parser.parse_args()
    config=json.loads(Path(args.config).read_text(encoding='utf-8'))
    if config['execution']['minimum_commission'] != 5:
        raise ValueError('v1 risk model requires minimum_commission=5')
    if args.mode=='demo':
        bars,calendar,week_ends=demo_data()
    elif args.mode=='tushare':
        bars,calendar,week_ends=TushareSource().fetch(args.symbols,args.start,args.end)
    else:
        if not args.csv or not args.calendar:
            parser.error('csv mode requires --csv and --calendar')
        bars=load_csv(args.csv)
        cal=json.loads(Path(args.calendar).read_text(encoding='utf-8'))
        calendar,week_ends=cal['open_dates'],set(cal['week_ends'])
    if calendar!=sorted(set(calendar)) or not calendar:
        raise ValueError('Calendar must be sorted, unique and non-empty')
    if any(b.date not in calendar for b in bars):
        raise ValueError('Market bars fall outside trading calendar')
    digest=hashlib.sha256(json.dumps([asdict(b) for b in bars],sort_keys=True).encode()).hexdigest()
    code_hash=hashlib.sha256()
    for path in sorted(Path(__file__).parent.rglob('*.py')):
        code_hash.update(str(path.relative_to(Path(__file__).parent)).encode())
        code_hash.update(path.read_bytes())
    now=datetime.now(ZoneInfo('Asia/Shanghai'))
    output=Path(args.output)/(now.strftime('%Y%m%d-%H%M%S-%f')+'-'+args.mode)
    output.mkdir(parents=True)
    shutil.copytree(Path(__file__).parent,output/'source'/'src'/'trading_system',
                    ignore=shutil.ignore_patterns('__pycache__'))
    launcher = Path(__file__).resolve().parents[2]/'run.py'
    if launcher.exists():
        shutil.copy2(launcher,output/'source'/'run.py')
    lower_bars=load_intraday_csv(args.lower_csv) if args.lower_csv else []
    evaluation_dates=[d for d in calendar if (not args.evaluation_start or d>=args.evaluation_start)
                      and (not args.evaluation_end or d<=args.evaluation_end)]
    if not evaluation_dates:
        raise ValueError('Evaluation window has no trading dates')
    universe_data=json.loads(Path(args.universe).read_text(encoding='utf-8')) if args.universe else None
    universe=MainboardUniverse(universe_data['stocks'],universe_data['st_by_date']) if universe_data else None
    if universe and any(d not in universe.st_by_date for d in evaluation_dates):
        raise ValueError('Historical ST coverage must include every evaluation session')
    engine=Backtest(config,build_strategies(config['strategies'])).run(
        bars,calendar,week_ends,lower_bars,args.evaluation_start,args.evaluation_end,universe)
    summary=engine.summary()
    summary['event_counts']=dict(Counter(e['event'] for e in engine.events))
    manifest=dict(created_at=now.isoformat(),source=args.mode,data_sha256=digest,
                  research_scope=config.get('research_scope'),
                  code_sha256=code_hash.hexdigest(),symbols=sorted({b.symbol for b in bars}),
                  lower_bar_count=len(lower_bars),
                  entry_clock=engine.entry_clock,
                  lower_data_sha256=hashlib.sha256(json.dumps([asdict(b) for b in lower_bars],sort_keys=True).encode()).hexdigest(),
                  start=calendar[0],end=calendar[-1],bar_count=len(bars),
                  evaluation_start_requested=args.evaluation_start,evaluation_end_requested=args.evaluation_end,
                  evaluation_first_session=evaluation_dates[0],evaluation_last_session=evaluation_dates[-1],
                  evaluation_session_count=len(evaluation_dates),warmup_event_count=len(engine.warmup_events),
                  initial_position_policy='flat; warmup entry intents discarded',
                  philosophy_version='2.0' if 'account_policy' in config else '1.0',
                  account_policy='human_phase_annual_contraction' if 'account_policy' in config else 'fixed',
                  corporate_actions='synthetic_total_return_factor_share_adjustment',
                  limitations=['completed hourly OHLC conservative fills; exact intrabar order and tick fill time unknown'
                               if engine.entry_clock=='hourly' else 'daily OHLC conservative fills, not intraday replay',
                               'fixed sample is not a point-in-time market universe',
                               'human market phases required; retrospective labels do not prove causality'
                               if 'account_policy' in config else 'no market-index gate, three-element policy or Boston allocation yet',
                               'swing/area/volume definitions are research conventions'
                               if 'account_policy' in config else 'target-height and retest thresholds are research hypotheses'])
    for name,value in [('manifest',manifest),('config',config),('summary',summary),
                       ('calendar',dict(open_dates=calendar,week_ends=sorted(week_ends)))]:
        (output/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    if universe_data:
        manifest['universe']='historical mainboard listing dates; dated ST exclusion on signal and execution'
        manifest['limitations'].remove('fixed sample is not a point-in-time market universe')
        (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        (output/'universe.json').write_text(json.dumps(universe_data,ensure_ascii=False),encoding='utf-8')
    save_csv(output/'bars.csv',[asdict(b) for b in bars])
    if lower_bars:
        save_csv(output/'hourly.csv',[asdict(b) for b in lower_bars])
    for name,rows in [('decisions',engine.events),('warmup_decisions',engine.warmup_events),('orders',engine.orders),
                      ('trades',engine.trades),('equity',engine.curve),('entry_audit',engine.entry_audits)]:
        save_csv(output/(name+'.csv'),rows)
    rendered=html.escape(json.dumps(dict(manifest=manifest,summary=summary),ensure_ascii=False,indent=2))
    (output/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>回测报告</title>'
        '<style>body{max-width:1000px;margin:40px auto;font-family:system-ui}pre{white-space:pre-wrap}</style>'
        '<h1>交易系统流程验证报告</h1><p>DEMO 为构造数据；真实样本结果不代表策略已验证。</p><pre>'+rendered+'</pre>',encoding='utf-8')
    print(json.dumps(dict(output=str(output.resolve()),summary=summary),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
