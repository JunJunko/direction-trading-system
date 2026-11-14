import sys,json,csv,html
from pathlib import Path
from collections import defaultdict
from dataclasses import asdict
from concurrent.futures import ProcessPoolExecutor
from scan_20261026 import ROOT,OUT,CACHE,CFG,Bar,build_strategies,dump
from trading_system.domain import Intent
from trading_system.engine import Backtest
def replay(item):
 s,bs=item;strategies=build_strategies(CFG['strategies']);last=[]
 for n,b in enumerate(bs):
  for strategy in strategies:
   intents,_=strategy.on_close(bs[:n+1],set())
   if b.date=='20261023':last.extend(asdict(i) for i in intents)
 return s,last
def main():
 plans=json.loads((OUT/'plans.json').read_text(encoding='utf-8'));symbols={p['symbol'] for p in plans};bs=defaultdict(list)
 with (ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v5-breakout-trend/bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   if r['symbol'] in symbols:bs[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
 for path in sorted(CACHE.glob('daily_trade_date-*.json')):
  d=path.stem[-8:];daily=json.loads(path.read_text(encoding='utf-8'))
  fs={r['ts_code']:r['adj_factor'] for r in json.loads((CACHE/f'adj_factor_trade_date-{d}.json').read_text(encoding='utf-8'))}
  ls={r['ts_code']:r for r in json.loads((CACHE/f'stk_limit_trade_date-{d}.json').read_text(encoding='utf-8'))}
  for r in daily:
   s=r['ts_code']
   if s in symbols:bs[s].append(Bar(s,d,*[float(r[k]) for k in ('open','high','low','close','vol')],float(fs[s]),float(ls[s]['up_limit']),float(ls[s]['down_limit'])))
 for bars in bs.values():bars.sort(key=lambda b:b.date)
 with ProcessPoolExecutor(max_workers=8) as pool:
  for symbol,actual in pool.map(replay,bs.items()):
   expected=[{k:v for k,v in p.items() if k not in ('name','reference_assessment')} for p in plans if p['symbol']==symbol]
   assert actual==expected,symbol
   print('full replay verified',symbol,flush=True)
 engine=Backtest(CFG,[])
 for p in plans:
  i=Intent(**{k:v for k,v in p.items() if k not in ('name','reference_assessment')})
  p['reference_assessment']=engine.assess_entry(i,i.trigger*1.001,1e6,1e6,{},'20261026')
  allowed=[]
  for cents in range(int(i.stop*100)+1,int(i.target*100)):
   a=engine.assess_entry(i,cents/100*1.001,1e6,1e6,{},'20261026')
   if a['risk_reason']=='approved':allowed.append(cents/100)
  p['conditional_open_range']=[min(allowed),max(allowed)] if allowed else None
 dump(OUT/'plans.json',plans);dump(OUT/'verification.json',dict(full_history_replay_all_10_signals_exact=True,next_session_risk_date='20261026',assumptions='1M flat account; 0.1% slippage; commission 0.03%; sell tax 0.05%; minimum commission 5; unchanged 20261023 adjustment factors',no_actual_orders=True))
 labels={'approved':'通过','entry_too_far_from_W_retest':'止损距离超过2%','net_rr_not_above_threshold':'净收益风险比不高于3','ihs_breakout_lost_at_entry':'开盘颈线条件未满足','ihs_breakout_entry_too_far':'距颈线过远'}
 table=''
 for p in plans:
  a=p['reference_assessment'];rg=p['conditional_open_range'];price_range=f'{rg[0]:.2f}–{rg[1]:.2f}' if rg else '无'
  table+=f'<tr><td>{p["name"]} {p["symbol"]}</td><td>{"双底回踩" if p["reason"]=="direct_w" else "头肩底突破"}</td><td>{p["trigger"]:.2f}</td><td>{p["stop"]:.2f}</td><td>{p["target"]:.2f}</td><td>{a.get("net_rr",0):.2f}</td><td>{labels.get(a["risk_reason"],a["risk_reason"])}</td><td>{price_range}</td></tr>'
 waiting=json.loads((OUT/'waiting.json').read_text(encoding='utf-8'))
 wt=''.join(f'<tr><td>{p["name"]} {p["symbol"]}</td><td>{p["date"]}</td><td>{p["evidence"]["w_neckline"]:.2f}</td></tr>' for p in waiting)
 page=f'''<!doctype html><meta charset="utf-8"><title>2026-10-26 盘前双底与头肩底扫描</title><style>body{{font:16px system-ui;margin:40px auto;max-width:1200px;color:#182536}}table{{border-collapse:collapse;width:100%;margin:24px 0}}th,td{{padding:10px;border-bottom:1px solid #ddd;text-align:left}}th{{background:#edf3f8}}p{{line-height:1.7}}</style><h1>2026-10-26 盘前扫描</h1><p>数据截至2026-10-23收盘，来源Tushare。沪深主板非ST 3,053只，3,052只有当日日线；601326.SH缺少当日日线，不给出当前判断。采用双底v5.19、头肩底v5的入场规则及v7配置。10只信号全部通过完整历史逐日重放复核。</p><h2>结论：瀚蓝环境通过收盘参考价风控</h2><p>600323.SH：双底日期9月28日、10月16日；10月19日突破，10月20日结构可确认，10月23日回踩30.25后收于30.73。颈线30.65，初始止损30.25，量度参考目标32.99。参考成交30.76073，扣费净收益风险比3.76。目标只用于评估空间，v7不以触及目标自动卖出。</p><h2>已完成入场信号</h2><p>通过表示假设100万元空仓账户、按前收盘加0.1%滑点估算；并非实际成交。条件开盘区间按0.01元网格计算，含费用、止损距离和10月26日颈线条件，仅为价格风控结果，仍须核实当天ST、停牌、涨停及复权变化。开盘下穿止损不买。价格区间不是盘中追单范围。</p><table><tr><th>股票</th><th>形态</th><th>前收盘</th><th>止损</th><th>目标参考</th><th>净RR</th><th>参考价判断</th><th>条件开盘区间</th></tr>{table}</table><p>净RR显示0表示在更早的止损距离检查已被拒绝，尚未进入净RR计算。未通过参考价风控的股票，仅在开盘价格改变后才可能通过，不能认定为已可买。</p><h2>42个待回踩确认的双底</h2><p>这些是观察池，不是已完成的买入信号。颈线价格使用各自登记日的复权基准。</p><table><tr><th>股票</th><th>登记日</th><th>登记颈线</th></tr>{wt}</table>'''
 (OUT/'report.html').write_text(page,encoding='utf-8')
 for p in plans:print(json.dumps(dict(symbol=p['symbol'],name=p['name'],range=p['conditional_open_range'],risk=p['reference_assessment']['risk_reason'],net_rr=p['reference_assessment'].get('net_rr')),ensure_ascii=True),flush=True)
if __name__=='__main__':main()
