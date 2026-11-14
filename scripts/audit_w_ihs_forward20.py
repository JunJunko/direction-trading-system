"""Posterior entry-price paths, capped at 20 exchange sessions; never change entry/exit rules."""
import csv,hashlib,html,json,math,shutil
from collections import Counter,defaultdict
from pathlib import Path
from statistics import mean,median
ROOT=Path(__file__).resolve().parents[1]
PRIOR=ROOT/'audits/20261025-w-ihs-v7-R-distribution'
RUN=ROOT/'runs/20261025-w-ihs-v7-shared-account'
OUT=ROOT/'audits/20261025-w-ihs-v7-forward20'
HORIZONS=(1,3,5,10,20)
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def save(p,rs):
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rs for k in r)));w.writeheader();w.writerows(rs)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def near(a,b):assert math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-8),(a,b)

def summarize(rs):
 full=[r for r in rs if r['full_window']];n=len(full)
 rate=lambda count:count/n if n else None
 def count(key):return sum(bool(r[key]) for r in full)
 return dict(events=len(rs),complete=n,censored=len(rs)-n,
   median_max_gross_return=median(r['max_gross_return'] for r in full) if n else None,
   median_MFE_net_R=median(r['MFE_net_R'] for r in full) if n else None,
   median_end_net_R=median(r['end_net_R'] for r in full) if n else None,
   mean_end_net_R=mean(r['end_net_R'] for r in full) if n else None,
   median_MAE_net_R=median(r['MAE_net_R'] for r in full) if n else None,
   observed_net_positive=sum(r['MFE_net_R']>0 for r in full),
   MFE_1R=sum(r['MFE_net_R']>=1 for r in full),MFE_1R_rate=rate(sum(r['MFE_net_R']>=1 for r in full)),
   MFE_2R=sum(r['MFE_net_R']>=2 for r in full),MFE_2R_rate=rate(sum(r['MFE_net_R']>=2 for r in full)),
   MFE_3R=sum(r['MFE_net_R']>=3 for r in full),MFE_3R_rate=rate(sum(r['MFE_net_R']>=3 for r in full)),
   sellable_MFE_1R=sum(r['sellable_MFE_net_R'] is not None and r['sellable_MFE_net_R']>=1 for r in full),
   max_gross_5pct=sum(r['max_gross_return']>=.05 for r in full),max_gross_10pct=sum(r['max_gross_return']>=.1 for r in full),
   first_day_close_net_negative=sum(r['day1_close_net_R']<0 for r in full),
   all_observed_closes_net_negative=count('all_closes_net_negative'),
   end_net_positive=sum(r['end_net_R']>0 for r in full),end_net_positive_rate=rate(sum(r['end_net_R']>0 for r in full)),
   initial_stop_touched=count('initial_stop_touched'),
   stop_then_1R=sum(r['stop_vs_1R']=='先触止损，后达1R' for r in full),
   one_R_then_stop=sum(r['stop_vs_1R']=='先达1R，后触止损' for r in full),
   same_day_stop_and_1R=sum(r['stop_vs_1R']=='同日均触，先后未知' for r in full),
   first_day_only_1R=sum(r['MFE_net_R']>=1 and (r['sellable_MFE_net_R'] is None or r['sellable_MFE_net_R']<1) for r in full),
   median_stop_distance=median(r['stop_distance'] for r in full) if n else None,
   median_initial_R_money=median(r['initial_R_money'] for r in full) if n else None)

def main():
 OUT.mkdir(exist_ok=True);(OUT/'source').mkdir(exist_ok=True);shutil.copy2(__file__,OUT/'source'/Path(__file__).name)
 cfg=load(RUN/'candidate_combined/config.json');cost=cfg['execution'];manifest=load(RUN/'manifest.json')
 assert sha(RUN/'bars.csv')==manifest['bars_sha256']
 sources=[('全部达标准机会',rows(PRIOR/'qualified-opportunities-R.csv')),('组合实际成交',rows(PRIOR/'combined-trades-R.csv'))]
 assert len(sources[0][1])==852 and len(sources[1][1])==146
 protocol=dict(purpose='posterior price-opportunity audit, not executable strategy profits',
   source_qualification=str(PRIOR/'protocol.json'),source_account=str(RUN),bars_sha256=manifest['bars_sha256'],
   windows=list(HORIZONS),session_count='D1 is actual entry session; D20 is the twentieth exchange session including D1',
   time_limit='data stops at 20260930; incomplete horizons are censored and excluded from complete-window rates',
   original_exit_ignored_for_observation=True,initial_stop_ignored_for_observation_but_touch_order_reported=True,
   denominator='entry-time original cost-inclusive R; no reset after support movement',
   future_use='future prices used only for posterior measurement; never alter entry eligibility or simulate a peak exit',
   same_day_high_low_order='unknown when both levels touched in the same daily bar',
   T1='entry-day peaks retained as observed, also report peaks after entry day separately',
   limitations=['known development data','overlapping repeated events are not independent','daily highs are not guaranteed sale prices','suspensions and synthetic factor share convention'])
 dump(OUT/'protocol.json',protocol)
 needed={r['symbol'] for scope,rs in sources for r in rs};hist=defaultdict(dict)
 with (RUN/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for b in csv.DictReader(f):
   if b['symbol'] in needed and b['date']<='20260930':hist[b['symbol']][b['date']]={k:(float(v) if k not in ('symbol','date') else v) for k,v in b.items()}
 cal=[d for d in load(RUN/'calendar.json')['open_dates'] if d<='20260930'];index={d:i for i,d in enumerate(cal)}
 records=[];daily=[];allh=[]
 for scope,rs in sources:
  for r in rs:
   start=r['entry_date'];symbol=r['symbol'];bs=hist[symbol];b0=bs[start];factor=b0['factor']
   fill,q,fee,risk,stop=(float(r[k]) for k in ('entry_price','quantity','entry_fee','initial_R_money','initial_stop'))
   def econ(b,k):return b[k]*b['factor']/factor
   def net(price):
    val=price*q*(1-cost['slippage'])
    return val-fill*q-fee-max(5,val*cost['commission_rate'])-val*cost['sell_tax_after_20230828']
   days=cal[index[start]:index[start]+20];path=[];lastclose=fill
   for j,d in enumerate(days,1):
    b=bs.get(d);quoted=b is not None and b['volume']>0
    if quoted:lastclose=econ(b,'close')
    day=dict(scope=scope,shape=r['shape'],symbol=symbol,setup_id=r['setup_id'],date=d,day_number=j,
      observed_quote=quoted,high=econ(b,'high') if quoted else None,low=econ(b,'low') if quoted else None,
      close=lastclose,close_carried=not quoted,close_net_R=net(lastclose)/risk,
      high_net_R=net(econ(b,'high'))/risk if quoted else None,low_net_R=net(econ(b,'low'))/risk if quoted else None,
      initial_stop_touched=quoted and econ(b,'low')<=stop,high_gross_return=econ(b,'high')/fill-1 if quoted else None)
    path.append(day);daily.append(day)
   assert path[0]['observed_quote']
   for horizon in HORIZONS:
    p=path[:horizon];observed=[d for d in p if d['observed_quote']];hi=max(observed,key=lambda d:d['high']);lo=min(observed,key=lambda d:d['low']);cl=max(p,key=lambda d:d['close_net_R'])
    sells=[d for d in observed if d['day_number']>1]
    first_stop=next((d for d in observed if d['initial_stop_touched']),None)
    first1=next((d for d in observed if d['high_net_R']>=1),None)
    if first_stop and first1:
     order='同日均触，先后未知' if first_stop['day_number']==first1['day_number'] else '先触止损，后达1R' if first_stop['day_number']<first1['day_number'] else '先达1R，后触止损'
    elif first_stop:order='触止损，未达1R'
    elif first1:order='达1R，未触止损'
    else:order='两者均未触及'
    row=dict(scope=scope,shape=r['shape'],symbol=symbol,setup_id=r['setup_id'],signal_date=r['signal_date'],entry_date=start,
      horizon=horizon,observed_exchange_sessions=len(p),full_window=len(p)==horizon,quoted_sessions=len(observed),
      end_date=p[-1]['date'],last_quote_date=next(d['date'] for d in reversed(p) if d['observed_quote']),end_close_carried=p[-1]['close_carried'],
      entry_price=fill,initial_stop=stop,stop_distance=(fill-stop)/fill,initial_R_money=risk,quantity=q,entry_net_RR=float(r['entry_net_RR']),
      max_price=hi['high'],max_price_date=hi['date'],max_price_day=hi['day_number'],max_gross_return=hi['high']/fill-1,
      MFE_net_R=hi['high_net_R'],peak_close_net_R=cl['close_net_R'],peak_close_day=cl['day_number'],
      min_price=lo['low'],min_price_day=lo['day_number'],MAE_gross_return=lo['low']/fill-1,MAE_net_R=lo['low_net_R'],
      end_price=p[-1]['close'],end_gross_return=p[-1]['close']/fill-1,end_net_R=p[-1]['close_net_R'],
      day1_close_net_R=p[0]['close_net_R'],day1_MFE_net_R=p[0]['high_net_R'],
      sellable_MFE_net_R=max(d['high_net_R'] for d in sells) if sells else None,
      all_closes_net_negative=all(d['close_net_R']<0 for d in p),
      initial_stop_touched=first_stop is not None,first_stop_date=first_stop['date'] if first_stop else '',first_stop_day=first_stop['day_number'] if first_stop else None,
      first_1R_date=first1['date'] if first1 else '',first_1R_day=first1['day_number'] if first1 else None,stop_vs_1R=order,
      in_combined_actual=scope=='组合实际成交' or r.get('in_combined_actual')=='True',
      actual_final_R=float(r['net_R']) if scope=='组合实际成交' else (float(r['actual_combined_net_R']) if r.get('actual_combined_net_R') else None))
    near(row['MFE_net_R'],net(row['max_price'])/risk);assert row['max_gross_return']>=-1e-10
    allh.append(row)
    if horizon==20:records.append(row)
 assert len(records)==998 and len(allh)==4990
 summaries=[]
 for scope in ('全部达标准机会','组合实际成交'):
  for horizon in HORIZONS:
   for shape in ('双底','头肩底','合计'):
    rs=[r for r in allh if r['scope']==scope and r['horizon']==horizon and (shape=='合计' or r['shape']==shape)]
    summaries.append(dict(scope=scope,horizon=horizon,shape=shape,**summarize(rs)))
 dump(OUT/'summary.json',summaries);save(OUT/'summary.csv',summaries);save(OUT/'forward20-details.csv',records)
 save(OUT/'qualified-forward20.csv',[r for r in records if r['scope']=='全部达标准机会'])
 save(OUT/'actual-forward20.csv',[r for r in records if r['scope']=='组合实际成交'])
 save(OUT/'all-horizons.csv',allh);save(OUT/'daily-paths.csv',daily)
 dump(OUT/'verification.json',dict(qualified_events=852,actual_combined_events=146,records=998,
  all_windows_bounded_to_20_exchange_sessions=True,entry_day_is_day1=True,no_data_after_20260930=True,
  incomplete_windows_excluded_from_horizon_rates=True,net_cost_R_values_recomputed=True,
  no_optimization_or_trading_rule_change=True,same_day_touch_order_not_invented=True))
 render(summaries,records)
 for s in summaries:
  if s['horizon']==20:print(json.dumps(s,ensure_ascii=True),flush=True)
 print('COMPLETE',flush=True)

def render(summaries,records):
 num=lambda v:'—' if v is None else f'{v:.2f}'
 pct=lambda v:'—' if v is None else f'{v:.2%}'
 def table(headers,data):return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+html.escape(str(v))+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in r)+'</tr>' for r in data)+'</tbody></table></div>'
 body='<h1>后验观察：双底与头肩底买入后20个交易日能涨多高？</h1><p>使用既有审核通过的852个独立准入机会，并单列组合实际成交146笔。D1为买入当天，最多观察至D20；不受原卖出日期或初始止损限制，但不假设真的可以忽略止损持有。</p><p><b>下表均只统计窗口完整的记录。</b>样本截至2026-09-30，不足20日的记录保留明细，单独标注，不补未来数据。最高涨幅是事后价格空间，不是可执行胜率或可保证收益。</p>'
 for scope in ('全部达标准机会','组合实际成交'):
  body+='<h2>'+scope+'：20日后验</h2>'+table(['形态','记录/完整/不足20日','最高涨幅中位数','最高净浮盈R中位数','曾达1R','曾达2R','曾达3R','D20净盈利比例','所有观察收盘均净亏','买入首日收盘净亏'],[(s['shape'],f"{s['events']}/{s['complete']}/{s['censored']}",pct(s['median_max_gross_return']),num(s['median_MFE_net_R']),f"{s['MFE_1R']} ({pct(s['MFE_1R_rate'])})",f"{s['MFE_2R']} ({pct(s['MFE_2R_rate'])})",f"{s['MFE_3R']} ({pct(s['MFE_3R_rate'])})",pct(s['end_net_positive_rate']),s['all_observed_closes_net_negative'],s['first_day_close_net_negative']) for s in summaries if s['scope']==scope and s['horizon']==20])
 body+='<h2>全体达标准机会：上涨空间与止损先后</h2>'+table(['形态','窗口完整','20日内触初始止损','先止损后达1R（不同日）','同日止损和1R（顺序未知）','1R只出现在买入日','最大不利波动净R中位数','D20净R中位数','初始止损距离中位数'],[(s['shape'],s['complete'],s['initial_stop_touched'],s['stop_then_1R'],s['same_day_stop_and_1R'],s['first_day_only_1R'],num(s['median_MAE_net_R']),num(s['median_end_net_R']),pct(s['median_stop_distance'])) for s in summaries if s['scope']=='全部达标准机会' and s['horizon']==20])
 body+='<h2>固定观察窗口对照</h2>'+table(['形态','窗口（含买入日）','完整样本','最高涨幅中位数','曾达1R比例','曾达2R比例','曾达3R比例','窗口末净盈利比例','窗口末平均净R'],[(s['shape'],s['horizon'],s['complete'],pct(s['median_max_gross_return']),pct(s['MFE_1R_rate']),pct(s['MFE_2R_rate']),pct(s['MFE_3R_rate']),pct(s['end_net_positive_rate']),num(s['mean_end_net_R'])) for s in summaries if s['scope']=='全部达标准机会' and s['shape']!='合计'])
 body+='<h2>每笔后验记录</h2><p>可按股票、日期、形态搜索。完整窗口与不足20日的记录分开过滤。</p><label>范围 <select id="scope"><option>全部达标准机会</option><option>组合实际成交</option></select></label> <label>形态 <select id="shape"><option>全部</option><option>双底</option><option>头肩底</option></select></label> <label>窗口 <select id="complete"><option value="yes">完整20日</option><option value="all">全部（含不足20日）</option><option value="no">不足20日</option></select></label> <input id="query" placeholder="股票、日期或止损先后"><p id="shown"></p>'
 headers=['范围','形态','股票','买入日','观察交易日','有效报价日','入场价','初始止损','1R金额','入场净RR','窗口最高价','最高涨幅','最高净浮盈R','峰值日期/第几日','可卖阶段最高净R','D20或末日净R','最大不利净R','首日收盘净R','首次止损日','首次1R日','止损/1R先后','属于组合成交','原策略最终R']
 body+='<div class="scroll"><table id="details"><thead><tr>'+''.join('<th>'+html.escape(v)+'</th>' for v in headers)+'</tr></thead><tbody>'
 for r in sorted(records,key=lambda r:(r['entry_date'],r['symbol'],r['scope'])):
  vals=[r['scope'],r['shape'],r['symbol'],r['entry_date'],r['observed_exchange_sessions'],r['quoted_sessions'],num(r['entry_price']),num(r['initial_stop']),f"{r['initial_R_money']:,.2f}",num(r['entry_net_RR']),num(r['max_price']),pct(r['max_gross_return']),num(r['MFE_net_R']),f"{r['max_price_date']} / D{r['max_price_day']}",num(r['sellable_MFE_net_R']),num(r['end_net_R']),num(r['MAE_net_R']),num(r['day1_close_net_R']),r['first_stop_date'],r['first_1R_date'],r['stop_vs_1R'],'是' if r['in_combined_actual'] else '否',num(r['actual_final_R'])]
  body+='<tr data-scope="'+r['scope']+'" data-shape="'+r['shape']+'" data-complete="'+('yes' if r['full_window'] else 'no')+'">'+''.join('<td>'+html.escape(str(v))+'</td>' for v in vals)+'</tr>'
 body+='</tbody></table></div><p>净R使用入场时原始含成本风险金额，按当时数量及复权经济价格计算。最高净R已扣估计卖出滑点、佣金和税；未执行峰值卖出。可卖阶段排除买入当日，但仍不代表能够绕过原止损或按盘中最高价成交。同根日线同时触及止损和1R时，不推断先后。</p><p>停牌/缺报价日不虚构高低价，末价可沿用最近报价并标注；交易日窗口按市场日历计数。重复股票与重叠机会并非独立样本；全部机会不可相加视为一个账户收益。此后验测量没有调整选股或交易规则。</p>'
 body+='<p><a href="qualified-forward20.csv">852笔准入机会后验明细</a> · <a href="actual-forward20.csv">146笔组合成交后验明细</a> · <a href="all-horizons.csv">1/3/5/10/20日逐笔数据</a> · <a href="daily-paths.csv">逐日价格及净R</a> · <a href="summary.csv">汇总统计</a> · <a href="protocol.json">统计口径</a></p>'
 js="""<script>const scope=document.getElementById('scope'),shape=document.getElementById('shape'),complete=document.getElementById('complete'),query=document.getElementById('query'),rs=[...document.querySelectorAll('#details tbody tr')];function filter(){let n=0;const q=query.value.trim().toLowerCase();for(const r of rs){let show=r.dataset.scope===scope.value&&(shape.value==='全部'||r.dataset.shape===shape.value)&&(complete.value==='all'||r.dataset.complete===complete.value)&&(!q||r.textContent.toLowerCase().includes(q));r.hidden=!show;if(show)n++}document.getElementById('shown').textContent='显示 '+n+' 笔'}scope.onchange=shape.onchange=complete.onchange=query.oninput=filter;filter();</script>"""
 (OUT/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>双底与头肩底20日后验空间</title><style>body{font:15px/1.7 system-ui;max-width:1600px;margin:30px auto;padding:0 20px;color:#18324a}.scroll{overflow:auto;max-height:650px}table{border-collapse:collapse;width:100%}th,td{padding:7px;border:1px solid #dce4ec;white-space:nowrap}th{background:#eef3f8;position:sticky;top:0}label{margin-right:10px}input,select{padding:7px}[hidden]{display:none!important}</style>'+body+js,encoding='utf-8')
if __name__=='__main__':main()
