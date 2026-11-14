import csv,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.analysis import adjusted,weekly
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
p=Path(sys.argv[1]);audit=json.loads((p/'trade-lineage-audit.json').read_text());items={r['symbol']:r for r in audit['trades']};bars={s:[] for s in items}
for r in csv.DictReader((p/'bars.csv').open(encoding='utf-8-sig')):
 if r['symbol'] in bars:
  bars[r['symbol']].append(Bar(r['symbol'],r['date'],*[float(r[k]) for k in ['open','high','low','close','volume','factor','up_limit','down_limit']]))
cal=json.loads((p/'calendar.json').read_text());fig,axs=plt.subplots((len(items)+1)//2,2,figsize=(17,5*((len(items)+1)//2)),squeeze=False)
for ax,(sym,r) in zip(axs.flat,items.items()):
 history=[b for b in bars[sym] if b.date<=r['breakout']];w=weekly(adjusted(history),set(cal['week_ends']));idx={b.date:i for i,b in enumerate(w)};a,c,n=idx[r['bottom1']],idx[r['bottom2']],idx[r['neck_peak']];start=max(0,a-10)
 for i in range(start,len(w)):
  b=w[i];color='#d44444' if b.close>=b.open else '#21916b';ax.vlines(i,b.low,b.high,color=color,lw=.8);ax.add_patch(Rectangle((i-.3,min(b.open,b.close)),.6,max(abs(b.close-b.open),.01),color=color))
 ax.plot([a,n,c,len(w)-1],[w[a].low,w[n].high,w[c].low,w[-1].close],'--',color='#4463aa',lw=1)
 ax.axhline(r['neckline'],ls=':',color='#888');ax.set_title(sym+' | bottoms '+r['bottom1']+' / '+r['bottom2']+' | breakout '+r['breakout'],fontsize=10)
 ticks=list(range(start,len(w),max(1,(len(w)-start)//7)));ax.set_xticks(ticks,[w[i].date[:6] for i in ticks],rotation=35);ax.grid(alpha=.15)
for ax in list(axs.flat)[len(items):]:ax.set_visible(False)
fig.suptitle('Actual weekly candles and algorithm-selected enclosing W — adjusted at each breakout date',fontsize=14);fig.tight_layout(rect=(0,0,1,.97));fig.savefig(p/'all-trades-weekly-structure-audit.png',dpi=120);print(str(len(items))+' symbols chart saved')
