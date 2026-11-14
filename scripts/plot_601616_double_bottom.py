import csv,json,sys
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'runs/20261027-601616-double-bottom';OUT.mkdir(exist_ok=True)
sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Bar
from trading_system.strategies import build_strategies
from trading_system.analysis import adjusted
r=ROOT/'runs/20261027-expected-upside5/upside5'
plans=json.loads((r/'plans.json').read_text(encoding='utf-8'));p=next(x for x in plans if x['symbol']=='601616.SH' and x['date']=='20251009')
with (ROOT/'runs/20261026-c2-full-comparable/bars.csv').open(encoding='utf-8-sig') as f:
 raw=[Bar(x['symbol'],x['date'],**{k:float(x[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}) for x in csv.DictReader(f) if x['symbol']=='601616.SH' and x['date']<='20251010']
raw.sort(key=lambda b:b.date);bars=adjusted(raw);lookup={b.date:b for b in bars}
left=lookup[p['w_left_date']];right=lookup[p['w_right_date']];peak=max((b for b in bars if left.date<b.date<right.date),key=lambda b:b.high)
assert abs(peak.high-p['w_neckline'])<1e-9
cfg=json.loads((r/'config.json').read_text(encoding='utf-8'));strategy=build_strategies(cfg['strategies'][:1])[0];found=[]
for i,b in enumerate(raw):
 if '20250401'<=b.date<='20251009':
  intents,events=strategy.on_close(raw[:i+1],set())
  found.extend(x for x in intents if x.date=='20251009')
match=next(x for x in found if x.setup_id==p['setup_id'])
assert abs(match.stop-p['stop'])<1e-9 and abs(match.target-p['target'])<1e-9
plt.rcParams['font.sans-serif']=['Microsoft YaHei','SimHei','DejaVu Sans'];plt.rcParams['axes.unicode_minus']=False
fig,axes=plt.subplots(2,1,figsize=(16,12),gridspec_kw={'height_ratios':[1.2,1]},layout='constrained')
colors={'neck':'#1679a0','stop':'#dc6a24','target':'#7d4eaa','buy':'#222222'}
def candles(ax,bs):
 for i,b in enumerate(bs):
  color='#cc3d42' if b.close>=b.open else '#16846c'
  ax.vlines(i,b.low,b.high,color=color,lw=.8)
  ax.add_patch(Rectangle((i-.3,min(b.open,b.close)),.6,max(abs(b.close-b.open),.002),facecolor=color,edgecolor=color,lw=.6))
 ticks=list(range(0,len(bs),max(1,len(bs)//9)))
 if len(bs)-1 not in ticks:
  if len(bs)-1-ticks[-1]<max(1,len(bs)//18):ticks.pop()
  ticks.append(len(bs)-1)
 ax.set_xticks(ticks,[bs[i].date[4:6]+'-'+bs[i].date[6:] for i in ticks]);ax.grid(alpha=.16);ax.set_xlim(-2,len(bs)+2);ax.set_ylabel('价格（元，统一到2025-10-10复权单位）')
 return {b.date:i for i,b in enumerate(bs)}
def label(ax,x,y,text,offset):
 ax.annotate(text,(x,y),xytext=offset,textcoords='offset points',fontsize=10,arrowprops=dict(arrowstyle='->',color='#334155'),bbox=dict(boxstyle='round,pad=.35',fc='white',ec='#cbd5e1',alpha=.95))
bs=[b for b in bars if b.date>='20250401'];ax=axes[0];ix=candles(ax,bs)
ax.axhline(p['w_neckline'],color=colors['neck'],ls='--',lw=1.4,label=f"颈线 {p['w_neckline']:.4f}")
ax.axhline(p['w_floor'],color='#8b929d',ls=':',label=f"结构底线 {p['w_floor']:.4f}（不是实际止损）")
ax.axhline(p['target'],color=colors['target'],ls='--',label=f"结构目标 {p['target']:.4f}")
ax.plot([ix[left.date],ix[peak.date],ix[right.date],ix[p['w_breakout_date']]],[left.low,peak.high,right.low,lookup[p['w_breakout_date']].close],color='#2457c5',alpha=.7,lw=1.5,marker='o',ls=':',label='算法选定的结构连接（非价格预测）')
label(ax,ix[left.date],left.low,f"左底 04-30\n{left.low:.4f}",(-45,-45));label(ax,ix[right.date],right.low,f"右底 09-23\n{right.low:.4f}",(-105,-40));label(ax,ix[peak.date],peak.high,f"两底间最高点 {peak.date[4:6]}-{peak.date[6:]}\n形成颈线",(-95,28))
ax.set_title('601616.SH｜算法识别的是跨100个交易日的宽双底，并非10月附近的小W',loc='left',fontsize=16,weight='bold');ax.legend(loc='upper left',ncol=2,fontsize=9);ax.set_ylim(min(b.low for b in bs)-.18,max(p['target']+.12,max(b.high for b in bs)+.12))
bs=[b for b in bars if b.date>='20250915'];ax=axes[1];ix=candles(ax,bs)
for value,key,title in [(p['w_neckline'],'neck','颈线 4.0787'),(p['stop'],'stop','实际止损 4.0500'),(4.08408,'buy','模拟买入 4.08408')]:ax.axhline(value,color=colors[key],ls='--',label=title)
label(ax,ix['20250925'],lookup['20250925'].close,'09-25 突破并确认结构',(-140,50));label(ax,ix['20250930'],lookup['20250930'].low,'09-30 回踩低点 4.05\n成为实际止损',(-130,-60));label(ax,ix['20251009'],lookup['20251009'].close,'10-09 收盘4.09\n回踩恢复，产生信号',(-160,95));label(ax,ix['20251010'],4.08408,'10-10 开盘4.08\n加0.1%滑点买入4.08408',(22,-20))
ax.axvspan(ix['20251010']-.5,ix['20251010']+.5,color='#f6c34a',alpha=.18)
ax.set_title('买点放大｜信号在10月9日收盘形成，10月10日开盘执行',loc='left',fontsize=15,weight='bold');ax.legend(loc='upper left',fontsize=9);ax.set_ylim(min(b.low for b in bs)-.18,max(b.high for b in bs)+.25)
fig.suptitle('历史记录核对：有算法买入信号，但结构认定与交易质量需要分开判断',fontsize=18,weight='bold')
fig.supxlabel('黄底K线为买入当日：高4.34、低4.04、收4.25；开盘决策不使用当日后续高低收盘。红涨绿跌。未展示10月10日之后行情。',fontsize=10,color='#475569')
fig.savefig(OUT/'annotated-chart.png',dpi=160);plt.close(fig)
result=dict(plan=p,left_adjusted_low=left.low,right_adjusted_low=right.low,neckline_peak_date=peak.date,neckline=peak.high,replayed_signal_exact=True,buy_day=dict(open=4.08,high=4.34,low=4.04,close=4.25),note='10月10日高低收盘仅供事后核查；信号回放严格截止10月9日')
(OUT/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
