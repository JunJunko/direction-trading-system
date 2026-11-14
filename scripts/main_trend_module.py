"""Research-only weekly main trend protection, fixed specification MT1."""
from datetime import datetime
from trading_system.domain import ExitIntent

def week(d):return datetime.strptime(d,'%Y%m%d').isocalendar()[:2]

def completed_weeks(history,calendar):
 last=history[-1].date;known={b.date:b for b in history};groups={}
 for d in calendar:
  groups.setdefault(week(d),[]).append(d)
 out=[]
 for index,dates in enumerate(groups.values()):
  if dates[-1]>last or any(d not in known for d in dates):continue
  bars=[known[d] for d in dates]
  out.append(dict(index=index,date=dates[-1],start=dates[0],high=max(b.high*b.factor for b in bars),low=min(b.low*b.factor for b in bars),close=bars[-1].close*bars[-1].factor))
 return out

def confirmed_sequences(ws):
 pivots=[];sequences=[]
 for t in range(2,len(ws)-2):
  window=ws[t-2:t+3]
  if window[-1]['index']-window[0]['index']!=4:continue
  low=all(ws[t]['low']<b['low'] for b in window if b is not ws[t]);high=all(ws[t]['high']>b['high'] for b in window if b is not ws[t])
  if low==high:continue # Ambiguous outside bar has no known high/low ordering.
  kind='L' if low else 'H';v=dict(ws[t],kind=kind,price=ws[t]['low' if low else 'high'],confirmed=ws[t+2]['date'])
  if pivots and pivots[-1]['kind']==kind:
   if (kind=='L' and v['price']>=pivots[-1]['price']) or (kind=='H' and v['price']<=pivots[-1]['price']):continue
   pivots[-1]=v
  else:pivots.append(v)
  if len(pivots)>=4 and ''.join(x['kind'] for x in pivots[-4:])=='HLHL':
   a,b,c,d=pivots[-4:]
   if c['price']>a['price'] and d['price']>b['price']:sequences.append(dict(d,prior_high=a['price'],new_high=c['price'],prior_low=b['price']))
 return sequences

class MainTrend:
 def __init__(self,name,calendar,weekends):
  self.name=name;self.calendar=calendar;self.weekends=set(weekends);self.protection=None;self.pending=False
 def manage(self,history,p):
  b=history[-1];events=[]
  if self.pending or b.date not in self.weekends:return [],events
  ws=completed_weeks(history,self.calendar)
  if not ws or ws[-1]['date']!=b.date:return [],events
  # Exit only against the previously active level; never retroactively apply a new level.
  if self.protection is not None and b.close*b.factor<self.protection:
   self.pending=True
   return [ExitIntent(self.name,b.symbol,b.date,p.setup_id,'weekly_main_trend_break')],[dict(date=b.date,event='weekly_close_break',protection=self.protection/b.factor)]
  for v in confirmed_sequences(ws):
   if v['start']<=p.entry_date or v['confirmed']!=b.date:continue
   floor=p.stop*p.factor
   if v['price']>max(floor,self.protection or floor):
    old=self.protection;self.protection=v['price']
    events.append(dict(date=b.date,event='main_protection_raised',formed=v['date'],confirmed=v['confirmed'],old=old,new=self.protection,raw_protection=self.protection/b.factor,prior_high=v['prior_high'],new_high=v['new_high'],prior_low=v['prior_low']))
  return [],events
