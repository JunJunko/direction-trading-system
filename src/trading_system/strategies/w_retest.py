"""A neckline retest of the same confirmed W, with a local execution stop."""
from dataclasses import replace
import math
from .direct_double_bottom import DirectDoubleBottom
from ..analysis import adjusted
from ..domain import Intent


class WRetest(DirectDoubleBottom):
    def __init__(self,name,params):
        params=dict(params)
        self.rules=dict(retest_sessions=14,touch_tolerance=.005,failure_tolerance=.025,max_entry_risk=.02)
        for k in self.rules:
            if k in params:self.rules[k]=params.pop(k)
        if type(self.rules['retest_sessions']) is not int or self.rules['retest_sessions']<1:raise ValueError('retest_sessions')
        for k in ('touch_tolerance','failure_tolerance','max_entry_risk'):
            v=self.rules[k]
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<v<1:raise ValueError(k)
        super().__init__(name,params)
        self.waiting={}

    def structure_broken(self,after,floor):
        return min(x.low for x in after)<=floor

    def on_close(self,history,week_ends):
        if not history or self.last.get(history[-1].symbol)==history[-1].date:return [],[]
        bars=self.normalized_history(history);b=bars[-1];events=[];intents=[];remaining=[]
        for seed in self.waiting.get(b.symbol,[]):
            e=dict(seed.evidence);scale=e['factor']/b.factor
            for k in ('w_neckline','w_floor','w_target','breakout_reference'):e[k]*=scale
            e['factor']=b.factor
            after=[x for x in bars if x.date>e['w_known_at']]
            base=dict(date=b.date,symbol=b.symbol,strategy=self.name,setup_id=seed.setup_id)
            reason=None
            if len(after)>self.rules['retest_sessions']:reason='expired'
            elif self.structure_broken(after,e['w_floor']):reason='W_floor_broken'
            elif min(x.low for x in after)<e['w_neckline']*(1-self.rules['failure_tolerance']):reason='neckline_retest_failed'
            elif max(x.high for x in after)>=e['w_target']:reason='target_already_touched'
            if reason:
                events.append(dict(base,event='w_retest_invalidated',reason=reason));continue
            low=min(after,key=lambda x:(x.low,-int(x.date)))
            recovered=(low.low<=e['w_neckline']*(1+self.rules['touch_tolerance']) and
                       b.close>e['w_neckline'] and b.close>b.open and b.close>bars[-2].close)
            if not recovered:
                remaining.append(seed);continue
            e.update(entry_mode='w_retest',rebound_confirmed_at=b.date,
                     w_retest_low=low.low,w_retest_low_date=low.date,w_retest_confirmed=b.date,
                     w_max_entry_risk=self.rules['max_entry_risk'],execution_stop_rule='W_neckline_retest_low')
            intent=Intent(self.name,b.symbol,b.date,b.close,low.low,e['w_target'],seed.setup_id,'direct_w',e)
            intents.append(intent)
            events.append(dict(base,event='entry_intent',trigger=intent.trigger,stop=intent.stop,target=intent.target,**e))
        seeds,source_events=super().on_close(history,week_ends)
        for event in source_events:
            events.append(dict(event,event='w_retest_registered' if event['event']=='entry_intent' else event['event']))
        remaining.extend(seeds);self.waiting[b.symbol]=remaining
        return intents,events
