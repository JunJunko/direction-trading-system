"""Explicit, causal W quality requirements; unchanged local retest execution."""
import math
from .w_retest import WRetest
from ..structure import hierarchy_double_bottom_candidates


class QualifiedWRetest(WRetest):
    def __init__(self,name,params):
        params=dict(params)
        self.quality=dict(trend_lookback=20,min_prior_decline=.05,min_rebound=.03,
            tolerance_mode='percent',atr_lookback=14,atr_multiplier=1.,
            min_separation=None,max_separation=None,breakout_volume_ratio=None,volume_lookback=20)
        for k in self.quality:
            if k in params:self.quality[k]=params.pop(k)
        for k in ('trend_lookback','atr_lookback','volume_lookback'):
            if type(self.quality[k]) is not int or self.quality[k]<2:raise ValueError(k)
        for k in ('min_prior_decline','min_rebound','atr_multiplier'):
            v=self.quality[k]
            if type(v) not in (int,float) or not math.isfinite(v) or v<=0:raise ValueError(k)
        if self.quality['min_prior_decline']>=1 or self.quality['min_rebound']>=1:raise ValueError('fraction')
        if self.quality['tolerance_mode'] not in ('percent','percent_or_atr'):raise ValueError('tolerance_mode')
        for k in ('min_separation','max_separation'):
            v=self.quality[k]
            if v is not None and (type(v) is not int or v<2):raise ValueError(k)
        lo=self.quality['min_separation'];hi=self.quality['max_separation']
        if lo is not None and hi is not None and lo>hi:raise ValueError('separation range')
        v=self.quality['breakout_volume_ratio']
        if v is not None and (type(v) not in (int,float) or not math.isfinite(v) or v<=0):raise ValueError('volume ratio')
        params.setdefault('bottom_tolerance',.05)
        super().__init__(name,params)

    def structure_broken(self,after,floor):
        # W invalidation is a close; local execution stops still use intraday lows.
        return min(x.close for x in after)<floor

    def qualify(self,bars,w):
        q=self.quality;a=w['first'];c=w['second'];k=w['first_breakout_index']
        evidence=dict(w_structure_invalidation='close_below_W_floor',w_quality_version='v5.19')
        left=bars[a].low;right=bars[c].low
        allowance=left*self.p['bottom_tolerance']
        if q['tolerance_mode']=='percent_or_atr':
            n=q['atr_lookback']
            if c<n:return False,'insufficient_atr_history',evidence
            atr=sum(max(bars[i].high-bars[i].low,abs(bars[i].high-bars[i-1].close),abs(bars[i].low-bars[i-1].close)) for i in range(c-n+1,c+1))/n
            allowance=max(allowance,atr*q['atr_multiplier'])
            evidence.update(w_tolerance_atr_pct=atr/left,w_atr_known_at=bars[c].date)
        evidence.update(w_bottom_difference=abs(right-left)/left,w_allowed_difference=allowance/left)
        if abs(right-left)>allowance+1e-12:return False,'bottoms_not_close',evidence
        gap=c-a;evidence['w_separation_sessions']=gap
        if (q['min_separation'] is not None and gap<q['min_separation'] or
                q['max_separation'] is not None and gap>q['max_separation']):return False,'bottom_separation',evidence
        rebound=(w['neckline']-max(left,right))/max(left,right)
        evidence['w_rebound_fraction']=rebound
        if rebound<q['min_rebound']:return False,'rebound_too_shallow',evidence
        n=q['trend_lookback']
        if a<n:return False,'insufficient_prior_trend_history',evidence
        # Entire window precedes bottom 1; no post-bottom data can establish a trend.
        seq=bars[a-n:a];prices=[b.close for b in seq];mean=sum(prices)/n;mid=(n-1)/2
        slope=sum((i-mid)*(v-mean) for i,v in enumerate(prices))/sum((i-mid)**2 for i in range(n))
        decline=(prices[0]-prices[-1])/prices[0]
        evidence.update(w_prior_decline=decline,w_prior_slope_pct=slope/mean,
            w_trend_start=seq[0].date,w_trend_end=seq[-1].date)
        if decline<q['min_prior_decline'] or slope>=0:return False,'prior_downtrend_not_confirmed',evidence
        if q['breakout_volume_ratio'] is not None:
            n=q['volume_lookback']
            if k<n:return False,'insufficient_volume_history',evidence
            avg=sum(b.volume for b in bars[k-n:k])/n
            ratio=bars[k].volume/avg if avg>0 else 0
            evidence['w_breakout_volume_ratio']=ratio
            if ratio<q['breakout_volume_ratio']:return False,'breakout_volume_insufficient',evidence
        return True,'qualified',evidence

    def candidate_layouts(self,bars,points):
        # Defer tolerance to qualify so ATR support is not prefiltered by 5%.
        tolerance=self.p['bottom_tolerance'] if self.quality['tolerance_mode']=='percent' else float('inf')
        layouts,_=hierarchy_double_bottom_candidates(bars,self.p['left'],self.p['right'],
            tolerance,allow_delayed=True,points=points,floor_mode='close')
        accepted=[];events=[];b=bars[-1]
        for w in layouts:
            ok,reason,evidence=self.qualify(bars,w)
            events.append(dict(date=b.date,symbol=b.symbol,strategy=self.name,event='w_quality_checked',
                w_left_date=bars[w['first']].date,w_right_date=bars[w['second']].date,
                qualified=ok,reason=reason,**evidence))
            if ok:accepted.append(dict(w,qualification=evidence))
        return accepted,events
