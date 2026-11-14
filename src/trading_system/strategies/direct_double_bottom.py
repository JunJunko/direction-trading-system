"""One W owns its entry, structural floor and measured target."""
import math
from ..analysis import adjusted
from ..domain import Intent, ExitIntent
from ..structure import SwingCache, hierarchy_double_bottom_candidates


class DirectDoubleBottom:
    def __init__(self,name,params):
        self.name=name
        self.p=dict(left=2,right=2,bottom_tolerance=.06)
        if set(params)-set(self.p):raise ValueError('Unknown direct W parameters')
        self.p.update(params)
        for k in ('left','right'):
            if type(self.p[k]) is not int or self.p[k]<1:raise ValueError(k)
        t=self.p['bottom_tolerance']
        if isinstance(t,bool) or not isinstance(t,(int,float)) or not math.isfinite(t) or not 0<=t<1:raise ValueError('tolerance')
        self.caches={};self.seen=set();self.last={};self.adjusted_bars={}

    def normalized_history(self,history):
        """Exact adjusted() prices, cached only for immutable append-only histories."""
        b=history[-1];cached=self.adjusted_bars.get(b.symbol)
        if cached is not None and cached[0]==b.factor:
            values=cached[2]
            if len(history)==len(values) and b==cached[1]:return values
            if len(history)==len(values)+1 and history[-2]==cached[1]:
                values.extend(adjusted(history[-1:]));self.adjusted_bars[b.symbol]=(b.factor,b,values)
                return values
        values=adjusted(history);self.adjusted_bars[b.symbol]=(b.factor,b,values)
        return values

    def candidate_layouts(self,bars,points):
        layouts,_=hierarchy_double_bottom_candidates(bars,self.p['left'],self.p['right'],self.p['bottom_tolerance'],allow_delayed=True,points=points)
        return layouts,[]

    def on_close(self,history,week_ends):
        if not history:return [],[]
        b=history[-1]
        if self.last.get(b.symbol)==b.date:return [],[]
        self.last[b.symbol]=b.date
        bars=self.normalized_history(history)
        points=self.caches.setdefault(b.symbol,SwingCache(self.p['left'],self.p['right'])).get(bars)
        layouts,audit=self.candidate_layouts(bars,points)
        layouts=[w for w in layouts if (b.symbol,bars[w['first']].date,bars[w['second']].date) not in self.seen]
        if not layouts:return [],audit
        # Freeze a deterministic selection without using subsequent returns.
        w=max(layouts,key=lambda w:(w['pattern_area'],w['second'],w['first']))
        for x in layouts:self.seen.add((b.symbol,bars[x['first']].date,bars[x['second']].date))
        neck=w['neckline'];floor=w['bottom'];target=neck+(neck-floor)
        identity=f'{self.name}:{b.symbol}:{bars[w["first"]].date}:{bars[w["second"]].date}'
        evidence=dict(entry_mode='w_neckline',entry_order='next_open',rebound_confirmed_at=b.date,
            breakout_reference=neck,w_left_date=bars[w['first']].date,w_right_date=bars[w['second']].date,
            w_breakout_date=bars[w['first_breakout_index']].date,w_known_at=b.date,
            w_neckline=neck,w_floor=floor,w_target=target,w_owner=identity,
            target_rule='neckline_plus_W_height',target_exit_rule='close_confirmed_next_open',
            support_exit_on_touch=True,factor=b.factor)
        evidence.update(w.get('qualification',{}))
        event=dict(date=b.date,symbol=b.symbol,strategy=self.name,setup_id=identity,**evidence)
        if b.close<=neck:
            return [],audit+[dict(event,event='w_neckline_not_held')]
        if not floor<b.close<target:
            return [],audit+[dict(event,event='w_space_exhausted')]
        intent=Intent(self.name,b.symbol,b.date,b.close,floor,target,identity,'direct_w',evidence)
        return [intent],audit+[dict(event,event='entry_intent',trigger=b.close,stop=floor,target=target)]

    def trailing_stop(self,history,position):return position.stop

    def manage_position(self,history,position):
        b=history[-1]
        if b.close>=position.plan['w_target']:
            return [ExitIntent(self.name,b.symbol,b.date,position.setup_id,'w_target_close_confirmed')],[]
        return [],[]
