"""Draw the exact selected daily W and surrounding price action for review."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib import font_manager
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/20261026-premarket-w-ihs-no-distance-cap/600323-structure'
def main():
 font_manager.fontManager.addfont('C:/Windows/Fonts/msyh.ttc')
 plt.rcParams.update({'font.family':'Microsoft YaHei','axes.unicode_minus':False,'font.size':11})
 data=json.loads((OUT/'adjusted-bars.json').read_text(encoding='utf-8'))
 plan=next(p for p in json.loads((OUT.parent/'plans.json').read_text(encoding='utf-8')) if p['symbol']=='600323.SH')
 e=plan['evidence'];bars=[b for b in data if b['date']>='20260828'];idx={b['date']:n for n,b in enumerate(bars)}
 left=idx[e['w_left_date']];right=idx[e['w_right_date']]
 peak=max(range(left+1,right),key=lambda n:bars[n]['high'])
 assert bars[peak]['date']=='20261013' and abs(bars[peak]['high']-e['w_neckline'])<1e-9
 assert abs(min(bars[left]['low'],bars[right]['low'])-e['w_floor'])<1e-9
 assert abs(plan['target']-(2*e['w_neckline']-e['w_floor']))<1e-9
 fig,(ax,detail)=plt.subplots(2,1,figsize=(16,11),gridspec_kw={'height_ratios':[1.25,1]},facecolor='#f8fafc')
 fig.subplots_adjust(left=.065,right=.84,top=.89,bottom=.13,hspace=.32)
 for a,start,end in [(ax,0,len(bars)-1),(detail,idx['20261012'],len(bars)-1)]:
  a.set_facecolor('white')
  for n in range(start,end+1):
   b=bars[n];color='#ce4246' if b['close']>=b['open'] else '#169375'
   a.vlines(n,b['low'],b['high'],color=color,lw=1.2,zorder=3)
   a.add_patch(Rectangle((n-.28,min(b['open'],b['close'])),.56,max(abs(b['close']-b['open']),.012),facecolor=color,edgecolor=color,zorder=3))
  a.set_xlim(start-.9,end+2);a.grid(axis='y',color='#e2e8f0',lw=.7);a.set_ylabel('价格（元）')
  for spine in ['top','right']:a.spines[spine].set_visible(False)
  ticks=list(range(start,end+1,5 if a is ax else 1));a.set_xticks(ticks,[bars[n]['date'][4:6]+'/'+bars[n]['date'][6:] for n in ticks],rotation=0)
  a.axhline(e['w_neckline'],color='#2563eb',lw=1.5,ls='--',zorder=2)
  a.axhline(plan['stop'],color='#dc2626',lw=1.2,ls=':',zorder=2)
  a.text(1.01,e['w_neckline'],'颈线 30.65',transform=a.get_yaxis_transform(),va='center',color='#2563eb',fontweight='bold')
  a.text(1.01,plan['stop'],'局部止损 30.25',transform=a.get_yaxis_transform(),va='center',color='#dc2626')
 ax.set_ylim(min(b['low'] for b in bars)-.45,34.05)
 ax.axhline(plan['target'],color='#8b5cf6',lw=1.4,ls='--')
 ax.text(1.01,plan['target'],'量度目标 32.99',transform=ax.get_yaxis_transform(),va='center',color='#7c3aed')
 ax.axhline(e['w_floor'],color='#64748b',lw=1,ls=':')
 ax.text(1.01,e['w_floor'],'形态底线 28.31',transform=ax.get_yaxis_transform(),va='center',color='#64748b')
 path=[left,peak,right,idx['20261019']]
 ax.plot(path,[bars[left]['low'],bars[peak]['high'],bars[right]['low'],bars[idx['20261019']]['close']],color='#ed8a18',lw=2.1,marker='o',ms=5,zorder=4)
 def note(a,date,price,label,xytext,color='#334155'):
  a.annotate(label,xy=(idx[date],price),xytext=xytext,textcoords='offset points',fontsize=10,ha='center',color=color,arrowprops={'arrowstyle':'->','color':color,'lw':.9},bbox={'boxstyle':'round,pad=.35','facecolor':'white','edgecolor':'#d5dee9','alpha':.96},zorder=8)
 note(ax,'20260928',bars[left]['low'],'① 算法左底 09/28\n28.3117',(-38,-47))
 note(ax,'20261013',30.65,'② 颈线高点 10/13\n30.65',(-80,55),'#2563eb')
 note(ax,'20261016',29.51,'③ 算法右底 10/16\n29.51',(15,-52))
 earlier=idx['20260922'];note(ax,'20260922',bars[earlier]['low'],'需检查：更早低点 09/22\n28.1334，低于算法左底',(-62,58),'#8a5b15')
 note(ax,'20261019',30.74,'④ 首次收盘突破 10/19\n收 30.74 > 30.65',(45,67),'#2563eb')
 ax.set_title('A  全貌｜橙线连接算法选中的形态锚点，保留周边全部日K',loc='left',fontsize=12,pad=12)
 detail.set_ylim(29.15,31.85)
 note(detail,'20261016',29.51,'右底 10/16\n29.51',(-55,-22))
 note(detail,'20261019',30.74,'突破 10/19\n收 30.74',(-30,55),'#2563eb')
 note(detail,'20261020',30.82,'结构确认 10/20\n右底右侧第2根K',(40,87),'#334155')
 note(detail,'20261023',30.25,'⑤ 回踩低点／初始止损\n10/23 低 30.25',(-76,-38),'#dc2626')
 note(detail,'20261023',30.73,'⑥ 回踩确认 10/23\n开30.65 → 收30.73',(7,42),'#169375')
 detail.set_title('B  突破与回踩细节｜10/21、10/22收盘曾回到颈线下，10/23重新收上',loc='left',fontsize=12,pad=12)
 fig.suptitle('600323 瀚蓝环境｜本次扫描选中的日线双底结构',x=.065,ha='left',fontsize=20,fontweight='bold',color='#152a43',y=.97)
 fig.text(.065,.923,'截至 2026-10-23 收盘 · 按 10/23 复权因子统一价格 · 红涨绿跌 · 横轴按实际有行情的交易日排列',fontsize=11,color='#5b6b80')
 fig.text(.065,.065,'量度目标 = 30.65 + (30.65 − 28.3117) = 32.9883；用于评估空间。局部止损30.25与形态底线28.31含义不同。',fontsize=11,color='#334155')
 fig.text(.065,.035,'复核提示：9/22有更低低点；缓存无9/25日K。上图忠实展示算法选择，需人工检查形态完整性及左底归属。数据：Tushare。',fontsize=10,color='#7c5c2c')
 fig.savefig(OUT/'600323-structure.png',dpi=155,facecolor=fig.get_facecolor())
 fig.savefig(OUT/'600323-structure.svg',facecolor=fig.get_facecolor())
 anchors=dict(symbol='600323.SH',as_of='20261023',left=dict(date=e['w_left_date'],low=bars[left]['low']),neck=dict(date=bars[peak]['date'],high=e['w_neckline']),right=dict(date=e['w_right_date'],low=bars[right]['low']),breakout=e['w_breakout_date'],known=e['w_known_at'],retest=dict(date='20261023',low=30.25,close=30.73),earlier_lower_low=dict(date='20260922',low=bars[earlier]['low']),missing_bar='20260925',target=plan['target'])
 (OUT/'anchors.json').write_text(json.dumps(anchors,ensure_ascii=False,indent=2),encoding='utf-8')
 print(str(OUT/'600323-structure.png'))
if __name__=='__main__':main()
