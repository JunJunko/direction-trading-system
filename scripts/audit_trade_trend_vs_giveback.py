"""Entry-anchored, fee-aware path audit; exit-day highs/closes excluded."""
import csv,json,sys,html,shutil
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'runs/20261027-trend-vs-giveback'
DATA=ROOT/'runs/20261026-c2-full-comparable'
CASES={'v7':DATA/'combined_v7','IHS_only':ROOT/'runs/20261026-volatility-entry-ablation/IHS_only'}
sys.path.insert(0,str(ROOT/'src'))
from trading_system.domain import Bar
from trading_system.volatility_entry_research import prior_atr
def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def save(p,data):
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
def main():
 OUT.mkdir();shutil.copy2(__file__,OUT/Path(__file__).name)
 cases={k:dict(trades=rows(p/'trades.csv'),fills={(a['setup_id'],a['date']):a for a in rows(p/'entry_audit.csv') if a['execution_reason']=='filled'},cfg=load(p/'config.json')) for k,p in CASES.items()}
 needed={t['symbol'] for c in cases.values() for t in c['trades']};hist=defaultdict(list)
 print('Loading price paths',flush=True)
 with (DATA/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   if r['symbol'] in needed:hist[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
 for h in hist.values():h.sort(key=lambda b:b.date)
 cal=load(DATA/'calendar.json')['open_dates'];ix={d:i for i,d in enumerate(cal)}
 results=[];daily=[];summaries={}
 for name,c in cases.items():
  records=[];ex=c['cfg']['execution']
  for t in c['trades']:
   a=c['fills'][t['setup_id'],t['entry_date']];h=hist[t['symbol']];bydate={b.date:b for b in h};b0=bydate[t['entry_date']]
   entry=float(a['fill']);qty=float(a['filled_quantity']);fee=float(a['entry_fee']);risk=float(a['expected_loss']);cost=entry*qty
   def val(b,price):
    scaled=price*b.factor/b0.factor;value=scaled*(1-ex['slippage'])*qty
    tax=ex['sell_tax_after_20230828'] if b.date>='20230828' else ex['sell_tax_before_20230828']
    return scaled/entry-1,value-cost-fee-max(5,value*ex['commission_rate'])-value*tax
   exitbar=bydate[t['exit_date']]
   actual=value_actual=float(t['exit'])*float(t['quantity'])-cost-fee-max(5,float(t['exit'])*float(t['quantity'])*ex['commission_rate'])-float(t['exit'])*float(t['quantity'])*ex['sell_tax_after_20230828']
   assert abs(actual-float(t['pnl']))<1e-5,(name,t['symbol'],actual,t['pnl'])
   held=[b for b in h if t['entry_date']<=b.date<t['exit_date']]
   assert held
   peak=max(held,key=lambda b:val(b,b.close)[1]);gain,pnl=val(peak,peak.close)
   high=max(held,key=lambda b:val(b,b.high)[1]);high_gain,high_pnl=val(high,high.high)
   atr,known=prior_atr(h,t['entry_date'],b0.factor)
   sellable=[b for b in held if b.date>t['entry_date']]
   sellable_peak=max([val(b,b.close)[1] for b in sellable],default=None)
   nextdate=cal[ix[peak.date]+1];nb=bydate.get(nextdate)
   nextpnl=val(nb,nb.open)[1] if nb and nb.volume>0 and (not nb.down_limit or nb.open>nb.down_limit+1e-5) else None
   endidx=ix[t['entry_date']]+19;complete=endidx<len(cal) and cal[endidx]<='20260930'
   end=cal[endidx] if complete else '20260930'
   forward=[b for b in h if t['entry_date']<=b.date<=end]
   fp=max(forward,key=lambda b:val(b,b.close)[1]);fg,fn=val(fp,fp.close)
   r=dict(case=name,symbol=t['symbol'],family='W' if 'double_bottom' in t['strategy'] else 'IHS',setup_id=t['setup_id'],entry_date=t['entry_date'],exit_date=t['exit_date'],entry=entry,initial_stop=float(a['stop']),stop_pct=(entry-float(a['stop']))/entry*100,initial_risk=risk,atr=atr,atr_known_at=known,stop_atr=(entry-float(a['stop']))/atr,
    holding_sessions=ix[t['exit_date']]-ix[t['entry_date']]+1,peak_close_date=peak.date,peak_close_gain_pct=gain*100,peak_close_net_pnl=pnl,peak_close_net_R=pnl/risk,peak_close_gain_ATR=gain*entry/atr,
    peak_high_date=high.date,peak_high_gain_pct=high_gain*100,peak_high_net_R=high_pnl/risk,sellable_close_peak_pnl=sellable_peak,peak_close_next_open_pnl=nextpnl,
    final_pnl=float(t['pnl']),final_R=float(t['realized_r']),giveback_from_positive_peak=max(0,pnl)-float(t['pnl']),exit_reason=t['reason'],
    forward20_complete=complete,forward20_peak_close_date=fp.date,forward20_peak_close_gain_pct=fg*100,forward20_peak_after_exit=fp.date>=t['exit_date'])
   records.append(r);results.append(r)
   for b in held:
    g,n=val(b,b.close);daily.append(dict(case=name,setup_id=t['setup_id'],symbol=t['symbol'],date=b.date,raw_close=b.close,factor=b.factor,entry_factor=b0.factor,entry=entry,gain_pct=g*100,net_pnl=n,net_R=n/risk,entry_day_T1_locked=b.date==t['entry_date']))
  def summary(rs):
   losses=[r for r in rs if r['final_pnl']<0]
   bins=[]
   for lo,hi in [(-1e9,0),(0,1),(1,3),(3,5),(5,10),(10,1e9)]:
    x=[r for r in losses if lo<=r['peak_close_gain_pct']<hi]
    bins.append(dict(lower_pct=lo,upper_pct=hi,count=len(x),final_loss=-sum(r['final_pnl'] for r in x)))
   return dict(closed=len(rs),losses=len(losses),loss_sum=-sum(r['final_pnl'] for r in losses),positive_net_close_then_loss=sum(r['peak_close_net_pnl']>0 for r in losses),
    peak_net2R_then_loss=sum(r['peak_close_net_R']>=2 for r in losses),peak_5pct_then_loss=sum(r['peak_close_gain_pct']>=5 for r in losses),
    peak_2ATR_then_loss=sum(r['peak_close_gain_ATR']>=2 for r in losses),peak_5pct_and2ATR_then_loss=sum(r['peak_close_gain_pct']>=5 and r['peak_close_gain_ATR']>=2 for r in losses),loss_bins=bins,
    forward20_complete_losses=sum(r['forward20_complete'] for r in losses),post_exit_5pct_peak=sum(r['forward20_complete'] and r['peak_close_gain_pct']<5 and r['forward20_peak_close_gain_pct']>=5 and r['forward20_peak_after_exit'] for r in losses))
  summaries[name]={family:summary([r for r in records if family=='all' or r['family']==family]) for family in ('all','W','IHS')}
 save(OUT/'trades.csv',results);save(OUT/'holding-close-paths.csv',daily);dump(OUT/'summary.json',summaries)
 dump(OUT/'protocol.json',dict(source_cases={k:str(v) for k,v in CASES.items()},held_window='entry day through day before exit; exit-day highs and closes excluded',peak_definition='hindsight close net liquidation estimate, not achievable rule',T1='entry-day peak separately flagged; next-open counterfactual diagnostic only',forward='20 exchange sessions including entry, complete only by 20260930; after-exit gains not assigned to held trade',thresholds='descriptive 0/1/3/5/10 percent and 2 ATR, not optimized decision rules',accounting='all final net pnl reconciled against original entry fee, actual exit amount and sell fee; synthetic factor convention unchanged'))
 print(json.dumps(summaries,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
