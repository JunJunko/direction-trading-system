"""Joint pressure/support management and an optional one-session limit entry."""
import math
from dataclasses import replace
from .dynamic_w_exit import DynamicWExit
from ..analysis import adjusted
from ..structure import swings
from ..domain import ExitIntent


class ValueW(DynamicWExit):
    def __init__(self,name,params):
        params=dict(params);self.entry_distance=params.pop('limit_entry_distance',None)
        if self.entry_distance is not None and (type(self.entry_distance) not in (int,float) or not math.isfinite(self.entry_distance) or not 0<self.entry_distance<.02):raise ValueError('limit_entry_distance')
        super().__init__(name,params)

    def price_intent(self,i):
        if self.entry_distance is None:return i
        cap=math.floor(min(i.trigger,i.stop/(1-self.entry_distance))*100+1e-9)/100
        return replace(i,trigger=cap,evidence=dict(i.evidence,entry_order='support_limit',entry_limit=cap))

    def on_close(self,history,week_ends):
        intents,events=super().on_close(history,week_ends)
        intents=[self.price_intent(i) for i in intents]
        lookup={i.setup_id:i for i in intents}
        for event in events:
            if event.get('event')=='entry_intent' and event.get('setup_id') in lookup:
                i=lookup[event['setup_id']]
                event.update(trigger=i.trigger,entry_order=i.evidence['entry_order'])
                if 'entry_limit' in i.evidence:event['entry_limit']=i.evidence['entry_limit']
        return intents,events

    def manage_position(self,history,position):
        bars=adjusted(history);b=bars[-1];p=position.plan;p['hold_limit_up_profit']=True
        points=swings(bars,2,2);pressure=p.get('dynamic_pressure',p['w_target']);events=[]
        higher=[x.price for x in points if x.kind=='high' and x.price>b.close and not any(v.close>x.price for v in bars[x.index+1:])]
        if pressure is not None and b.close>pressure:
            p['broken_pressure']=max(p.get('broken_pressure',0),pressure)
            p['dynamic_pressure']=min(higher) if higher else None
        elif pressure is None:
            p['dynamic_pressure']=min(higher) if higher else None
        lows=[x.price for x in points if x.kind=='low' and bars[x.index].date>position.entry_date and not any(v.low<=x.price for v in bars[x.index+1:])]
        candidates=[position.stop]+lows
        if p.get('broken_pressure',0)<b.close:candidates.append(p.get('broken_pressure',0))
        old=position.stop;position.stop=max(candidates)
        if position.stop>old:
            events.append(dict(date=b.date,symbol=b.symbol,strategy=self.name,event='dynamic_support_raised',setup_id=position.setup_id,old_stop=old,new_stop=position.stop))
        if b.up_limit and b.close>=b.up_limit-1e-5:return [],events
        if p.get('broken_pressure') and b.close<p['broken_pressure']:
            return [ExitIntent(self.name,b.symbol,b.date,position.setup_id,'broken_pressure_failed')],events
        return [],events
