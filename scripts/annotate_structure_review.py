import csv,json,sys,re,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from trading_system.domain import Bar
from trading_system.analysis import adjusted,weekly
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

p=Path(sys.argv[1]);read=lambda f:json.loads(f.read_text(encoding='utf-8'));m=read(p/'manifest.json');cases=read(p/'cases-private.json');pred=read(p/'predictions-private.json');cal=read(p/'calendar.json');hist={c['symbol']:[] for c in cases}
with (Path(m['snapshot'])/'bars.csv').open(encoding='utf-8-sig') as f:
 for r in csv.DictReader(f):
  if r['symbol'] in hist:hist[r['symbol']].append(Bar(r['symbol'],r['date'],*[float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')]))
(p/'annotated').mkdir(exist_ok=True);audit=[];hover={}
for c in cases:
 bars=adjusted([b for b in hist[c['symbol']] if b.date<=c['as_of']]);w=weekly(bars,set(cal['week_ends']));fig,axes=plt.subplots(2,1,figsize=(15,9),gridspec_kw={'height_ratios':[2,1]})
 for ax,view,title in ((axes[0],w,'Weekly, all available history'),(axes[1],bars[-80:],'Daily, latest 80 observed sessions')):
  for i,b in enumerate(view):
   color='#b94141' if b.close>=b.open else '#21846b';ax.vlines(i,b.low,b.high,color=color,linewidth=.7);ax.add_patch(Rectangle((i-.3,min(b.open,b.close)),.6,max(abs(b.close-b.open),.003),facecolor=color))
  ticks=list(range(0,len(view),max(1,len(view)//10)));ax.set_xticks(ticks,[view[j].date for j in ticks],rotation=35,fontsize=8);ax.set_title(title,fontsize=11);ax.grid(alpha=.25)
 model=pred[c['id']]['structured'];source=model.get('source');ix={b.date:i for i,b in enumerate(w)};ax=axes[0];record=dict(id=c['id'],active=model['double_bottom'],model='v5.7 structured')
 if source:
  a=ix[source['first_date']];d=ix[source['second_date']];n=max(range(a+1,d),key=lambda i:w[i].high);b=ix[source['breakout_date']];o=ix[source['origin_date']];neck=w[n].high
  color='#204bc1' if model['double_bottom'] else '#888'
  ax.plot([o,a,n,d,b],[w[o].high,w[a].low,neck,w[d].low,w[b].close],color=color,linewidth=1.6,linestyle='--',label='Algorithm W candidate' if model['double_bottom'] else 'Historical candidate (not active)')
  ax.axhline(neck,color='#cc7417',linewidth=1.5,label='Neckline '+f'{neck:.3f}')
  for index,value,title in [(a,w[a].low,'Bottom 1'),(d,w[d].low,'Bottom 2'),(n,neck,'Neck peak'),(b,w[b].close,'Breakout')]:
   ax.scatter(index,value,s=26,color=color,zorder=4);ax.annotate(title+' '+w[index].date,(index,value),xytext=(4,12 if index in [n,b] else -22),textcoords='offset points',fontsize=8,color=color)
  ax.legend(loc='upper left',fontsize=9);record.update(bottom1=w[a].date,bottom2=w[d].date,neck_peak=w[n].date,neckline=neck,breakout=w[b].date)
 else:
  ax.text(.02,.94,'No W candidate found by this algorithm',transform=ax.transAxes,color='#777',fontsize=11)
 confirmation=model.get('confirmation')
 if confirmation and confirmation.get('retest_start_date') in ix:
  start=ix[confirmation['retest_start_date']];end=ix[confirmation['direction_bar']]
  ax.axvspan(start-.5,end-.5,color='orange',alpha=.15)
  ax.axvline(end,color='green',linestyle='--',label='Historical confirmation '+confirmation['direction_bar'])
  ax.annotate('Recovery '+confirmation['direction_bar'],(end,w[end].close),xytext=(6,25),textcoords='offset points',fontsize=8,color='green')
  if end>start:
   ax.hlines(max(x.close for x in w[start:end]),start-.5,end+.5,color='orange',linestyle='--',label='Prior adjustment closing high')
  ax.legend(loc='upper left',fontsize=8)
 status='Confirmed direction' if model['retest'] else 'Pending candidate' if model['double_bottom'] else 'Inactive / absent'
 ax.text(.99,.03,status,transform=ax.transAxes,ha='right',fontsize=10,bbox=dict(facecolor='white',alpha=.8))
 fig.suptitle(c['id']+' | '+c['as_of']+' | ALGORITHM ANNOTATIONS - not a blind review',fontsize=13);fig.tight_layout();fig.canvas.draw()
 panels=[]
 for ax,view,kind in ((axes[0],w,'weekly'),(axes[1],bars[-80:],'daily')):
  box=ax.get_position();panels.append(dict(kind=kind,bounds=dict(left=box.x0*1000,right=box.x1*1000,top=(1-box.y1)*1000,bottom=(1-box.y0)*1000),xlim=list(ax.get_xlim()),ylim=list(ax.get_ylim()),bars=[dict(date=b.date,open=b.open,high=b.high,low=b.low,close=b.close) for b in view]))
 hover[c['id']]=panels
 fig.savefig(p/'annotated'/f"{c['id']}.png",dpi=110);plt.close(fig);audit.append(record)
(p/'chart-hover-data.json').write_text(json.dumps(hover,ensure_ascii=False),encoding='utf-8')
if '--assets-only' in sys.argv:
 print('Updated candle/date coordinates for 28 charts');sys.exit(0)
(p/'annotation-details.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
page=p/'review.html';text=page.read_text(encoding='utf-8');(p/'review-blind.html').write_text(text,encoding='utf-8');text=text.replace('charts/R','annotated/R').replace('结构识别盲审','结构标线检查').replace('结构盲审','结构标线检查');text=text.replace('图中不展示股票名称、算法标线、买卖或盈亏；现有数据已用于研究，不能当作独立保留样本。请先标注，不打开同目录的private文件。','图中显示v5.7算法候选的双底轮廓、两个底、颈线和突破点。蓝线是当前候选，灰线是已经失效的历史候选；这些不是人工认定的标准答案。当前页面不再属于盲审，导出标注只用于结构检查。');text=text.replace('reviewer:reviewer.value.trim(),labels:',"reviewer:reviewer.value.trim(),view_mode:'algorithm_annotated',labels:");page.write_text(text,encoding='utf-8')
previous=m['file_hashes']['review.html'];m['file_hashes']['review.html']=hashlib.sha256(page.read_bytes()).hexdigest();m['presentation_mode']='algorithm_annotated';m['blind_page']='review-blind.html';m['presentation_revisions'].append(dict(date='2026-10-09',reason='User explicitly requested algorithm W and neckline annotations',previous_page_sha256=previous,cases_and_predictions_unchanged=True));m['file_hashes']['review-blind.html']=hashlib.sha256((p/'review-blind.html').read_bytes()).hexdigest()
for q in (p/'annotated').glob('*.png'):m['file_hashes'][q.relative_to(p).as_posix()]=hashlib.sha256(q.read_bytes()).hexdigest()
(p/'manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2),encoding='utf-8');print('Annotated all 28 charts; labels marked as non-blind')
