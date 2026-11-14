import sys,csv,json,shutil,html
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.strategies.direction_double_bottom import DirectionDoubleBottom

p=Path(sys.argv[1]);out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
lineage=json.loads((p/'trade-lineage-audit.json').read_text())['trades'];symbols={r['symbol'] for r in lineage};hist={s:[] for s in symbols}
cal=json.loads((p/'calendar.json').read_text());ends=set(cal['week_ends']);events={}
strategies={m:DirectionDoubleBottom('retest_'+m,dict(lower_cycle='daily_nested',structure_mode='hierarchy',exit_mode='active_correction',entry_lifecycle='fresh',retest_mode=m)) for m in ('legacy','structured')}
for s in strategies.values():s.set_calendar(cal['open_dates'])
with (p/'bars.csv').open(encoding='utf-8-sig') as f:
 for r in csv.DictReader(f):
  if r['symbol'] in hist:
   hist[r['symbol']].append(Bar(r['symbol'],r['date'],*[float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')]))
for mode,s in strategies.items():
 found=[]
 for symbol,bars in hist.items():
  for i in range(len(bars)):
   _,ev=s.on_close(bars[:i+1],ends)
   found.extend(e for e in ev if e['event'] in ('upper_direction_confirmed','weekly_reversal_candidate','weekly_retest_observed','weekly_reversal_invalidated'))
 events[mode]=found
rows=[]
for r in lineage:
 matches=[e for e in events['structured'] if e['symbol']==r['symbol'] and e['event']=='upper_direction_confirmed' and e.get('breakout_date')==r['breakout']]
 new=matches[0] if matches else {}
 rows.append(dict(symbol=r['symbol'],old_entry=r['entry'],breakout=r['breakout'],old_confirmed=r['direction_confirmed'],new_confirmed=new.get('date'),kind=new.get('retest_kind'),peak=new.get('peak_date'),trough=new.get('trough_date'),start=new.get('retest_start_date'),width=new.get('correction_range')))
checks=dict(confirm_after_peak=all(e['peak_date']<e['date'] for e in events['structured'] if e['event']=='upper_direction_confirmed'),confirm_after_trough=all(e['trough_date']<e['date'] for e in events['structured'] if e['event']=='upper_direction_confirmed'))
result=dict(scope='Nine previously traded stocks; causal direction replay only, no account return estimate',checks=checks,rows=rows,counts={m:sum(e['event']=='upper_direction_confirmed' for e in es) for m,es in events.items()})
(out/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');(out/'events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
keys=list(rows[0]);table='<table><tr>'+''.join('<th>'+k+'</th>' for k in keys)+'</tr>'+''.join('<tr>'+''.join('<td>'+html.escape(str(r[k]))+'</td>' for k in keys)+'</tr>' for r in rows)+'</table>'
(out/'report.html').write_text('<!doctype html><meta charset="utf-8"><style>body{font-family:system-ui;margin:30px;line-height:1.7}table{border-collapse:collapse}th,td{border:1px solid #bbb;padding:8px}</style><h1>v5.7 回踩结构修改核验</h1><p>只验证原10笔成交涉及的9只股票的因果方向事件，不是新的全量组合收益回测。空的新确认日表示原突破候选未被新规则确认。</p><p>规则：以突破后最高峰为活动锚点，排除峰值K线内部低点；恢复前至少3根调整K线，至少两次收盘下降，幅度小于此前上涨段。斜向调整须收盘突破前K线高点；横向整理须相邻K线区间重叠、收盘保持颈线上方并恢复超过调整收盘区间中点。以上为工程定义，书中没有规定两次下降和三根K线。新高重置活动区间；恢复K线不计入调整长度。</p>'+table+'<p>局限：仍未实现同级摆动归并；横向区间重叠不等于严格的均衡形态，需独立样本验证。缺少真实小时数据，不更新默认配置。</p>',encoding='utf-8')
shutil.copytree(Path(__file__).resolve().parents[1]/'src',out/'source/src',ignore=shutil.ignore_patterns('__pycache__'),dirs_exist_ok=True)
print(json.dumps(result,ensure_ascii=False))
if not all(checks.values()):raise SystemExit('causal verification failed')
