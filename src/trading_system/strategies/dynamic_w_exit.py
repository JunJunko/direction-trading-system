"""Keep limit-up profits; promote crossed pressure to closing support."""
from .qualified_w_retest import QualifiedWRetest
from ..analysis import adjusted
from ..structure import swings
from ..domain import ExitIntent


class DynamicWExit(QualifiedWRetest):
    def manage_position(self,history,position):
        bars=adjusted(history);b=bars[-1];p=position.plan
        p['hold_limit_up_profit']=True
        pressure=p.get('dynamic_pressure',p['w_target'])
        events=[]
        points=swings(bars,2,2)
        if pressure is not None and b.close>pressure:
            p['broken_pressure']=pressure
            higher=[x.price for x in points if x.kind=='high' and x.price>b.close and
                    not any(v.close>x.price for v in bars[x.index+1:])]
            p['dynamic_pressure']=min(higher) if higher else None
            events.append(dict(date=b.date,symbol=b.symbol,strategy=self.name,event='pressure_promoted',
                setup_id=position.setup_id,broken_pressure=pressure,next_pressure=p['dynamic_pressure']))
        if b.up_limit and b.close>=b.up_limit-1e-5:return [],events
        support=p.get('broken_pressure')
        if support is not None and b.close<support:
            return [ExitIntent(self.name,b.symbol,b.date,position.setup_id,'broken_pressure_failed')],events
        if support is not None:
            lows=[x for x in points if x.kind=='low' and bars[x.index].date>position.entry_date and
                  not any(v.low<=x.price for v in bars[x.index+1:])]
            if lows:position.stop=max(position.stop,max(x.price for x in lows))
        return [],events
