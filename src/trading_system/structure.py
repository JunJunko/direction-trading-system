"""Causal structural measurements. Numerical definitions are research conventions."""
from dataclasses import dataclass, replace
from .analysis import pivot_lows
from math import isclose


@dataclass(frozen=True)
class Swing:
    kind: str
    index: int
    confirmed: int
    price: float


class SwingCache:
    """Exactly the confirmed swings of an append-only adjusted series."""
    def __init__(self,left=2,right=2):
        self.left,self.right=left,right
        self.count=0
        self.anchor=None
        self.values=[[],[]]
        self.starts=[None,None]
        self.waiting=[[],[]]
        self.points=[]
        self.ambiguous=[]

    def get(self,bars):
        if self.anchor!=bars[-1].factor or len(bars)<self.count:
            self.count=0;self.anchor=bars[-1].factor
            self.values=[[],[]];self.starts=[None,None];self.waiting=[[],[]];self.points=[];self.ambiguous=[]
        for index in range(self.count,len(bars)):
            found=[]
            for kind,value in enumerate((bars[index].low,-bars[index].high)):
                values=self.values[kind];values.append(value)
                start=self.starts[kind]
                if start is None:
                    self.starts[kind]=index
                elif not isclose(value,values[start],rel_tol=0,abs_tol=1e-10):
                    self.waiting[kind].append((start,index-1))
                    self.starts[kind]=index
                remaining=[]
                for start,end in self.waiting[kind]:
                    if end+self.right>index:
                        remaining.append((start,end));continue
                    if start>=self.left and all(values[start]<v for v in
                            values[start-self.left:start]+values[end+1:end+self.right+1]):
                        found.append(Swing('low' if kind==0 else 'high',end,end+self.right,
                                           bars[end].low if kind==0 else bars[end].high))
                self.waiting[kind]=remaining
            # Both extremes on the same outside bar have unknown intrabar order.
            if len(found)==2 and found[0].index==found[1].index:
                self.ambiguous.append(dict(index=found[0].index,confirmed=index,
                    low=bars[found[0].index].low,high=bars[found[0].index].high))
                found=[]
            for point in sorted(found,key=lambda p:p.index):
                if self.points and self.points[-1].kind==point.kind:
                    previous=self.points[-1]
                    extreme=point.price<previous.price if point.kind=='low' else point.price>previous.price
                    if extreme:self.points[-1]=point
                else:self.points.append(point)
        self.count=len(bars)
        return self.points


def swings(bars, left=2, right=2):
    lows=pivot_lows(bars,left,right)
    highs=pivot_lows([replace(b,low=-b.high) for b in bars],left,right)
    # An outside bar can be both extremes. Daily OHLC cannot order the two.
    ambiguous=set(lows)&set(highs)
    points=[Swing('low',i,i+right,bars[i].low) for i in lows if i not in ambiguous]
    points += [Swing('high',i,i+right,bars[i].high) for i in highs if i not in ambiguous]
    result=[]
    for point in sorted(points,key=lambda p:p.index):
        if result and result[-1].kind==point.kind:
            extreme=point.price<result[-1].price if point.kind=='low' else point.price>result[-1].price
            if extreme:
                result[-1]=point
        else:
            result.append(point)
    return result


def area(bars, start, end):
    """Bounding rectangle in bar-count x price units; no screen-angle dependence."""
    segment=bars[start:end+1]
    return len(segment)*(max(b.high for b in segment)-min(b.low for b in segment))


def correction_measure(bars, start, end):
    """Measure the decline AFTER a peak, excluding its unordered intrabar low."""
    if end<=start:
        return None
    drop=bars[start].high-min(b.low for b in bars[start+1:end+1])
    if drop<=0:
        return None
    return dict(duration=end-start,range=drop,area=(end-start+1)*drop)


def active_correction(bars, entry_date):
    eligible=[i for i,b in enumerate(bars) if b.date>=entry_date]
    if not eligible:
        return None
    # An unconfirmed new high already ends the old decline. Confirmation is
    # necessary for a protective trough, not for observing a traded new high.
    peak=max(eligible,key=lambda i:(bars[i].high,i))
    measured=correction_measure(bars,peak,len(bars)-1)
    return dict(peak=peak,**measured) if measured else None


def double_bottom(bars, left=2, right=2, tolerance=.06):
    points=swings(bars,left,right)
    lows=[p for p in points if p.kind=='low']
    if len(lows)<2:
        return None,'insufficient_troughs'
    a,c=lows[-2:]
    if c.index-a.index<2:
        return None,'no_neckline'
    neck=max(b.high for b in bars[a.index+1:c.index])
    floor=min(a.price,c.price)
    if abs(c.price/a.price-1)>tolerance:
        return None,'troughs_not_matched'
    before=[p for p in points if p.index<a.index]
    highs=[p for p in before if p.kind=='high']
    old_lows=[p for p in before if p.kind=='low']
    if (len(highs)<2 or not old_lows or highs[-1].price>=highs[-2].price
            or a.price>=old_lows[-1].price):
        return None,'no_declining_structure'
    # The descending structure starts at the last chain of lower highs.
    origin=highs[-2]
    for k in range(len(highs)-3,-1,-1):
        if highs[k].price<=origin.price:
            break
        origin=highs[k]
    pattern_area=area(bars,a.index,len(bars)-1)
    prior_areas=[area(bars,l.index,h.index) for l,h in zip(before,before[1:])
                 if l.kind=='low' and h.kind=='high' and l.index>=origin.index]
    if not prior_areas or pattern_area<=max(prior_areas):
        return None,'reversal_not_larger_than_continuations'
    if len(bars)-1-a.index>=a.index-origin.index:
        return None,'pattern_not_matched_to_prior_trend'
    left_volume=sum(b.volume for b in bars[a.index:c.index])/max(1,c.index-a.index)
    right_volume=sum(b.volume for b in bars[c.index:])/len(bars[c.index:])
    if right_volume<=left_volume:
        return None,'right_side_volume_not_stronger'
    return dict(first=a.index,second=c.index,confirmed=c.confirmed,
                neckline=neck,bottom=floor,origin=origin.index,
                pattern_area=pattern_area,prior_area=max(prior_areas),
                left_volume=left_volume,right_volume=right_volume),'qualified'


def n_structure(bars, left=2, right=2, points=None, ownership=False, origin_date=None):
    """Latest confirmed low-high-low: core impulse, correction and independent space."""
    points=swings(bars,left,right) if points is None else points
    for i in range(len(points)-3,-1,-1):
        a,b,c=points[i:i+3]
        if (a.kind,b.kind,c.kind)!=('low','high','low'):
            continue
        if ownership:
            # A newer completed daily correction owns the current wave, even
            # when it fails qualification. Never fall back to an older wave.
            selected, reason = n_structure(bars,left,right,points=[a,b,c])
            if not selected:
                return None,'latest_core_not_qualified'
            if origin_date and bars[a.index].date[:8]<origin_date[:8]:
                return None,'core_precedes_direction_origin'
            selected['owner_id']=':'.join(bars[p.index].date for p in (a,b,c))
            return selected,reason
        if c.price<=a.price or b.price<=c.price:
            continue
        impulse=b.price-a.price
        correction=bars[b.index:c.index+1]
        correction_span=max(x.high for x in correction)-min(x.low for x in correction)
        duration=c.index-b.index
        if duration<3 or duration>b.index-a.index:
            continue
        impulse_speed=impulse/(b.index-a.index)
        correction_speed=(b.price-c.price)/duration
        if correction_speed>=impulse_speed:
            continue
        if correction_span>=impulse:
            continue
        # C is the active correction floor. Breaking it invalidates this N,
        # even while price remains above A; wait for a new confirmed correction.
        if min(x.low for x in bars[c.index:])<c.price:
            continue
        # Do not recycle the space of a wave that already reached its projection.
        if max(x.high for x in bars[c.index:])>=c.price+impulse:
            continue
        return dict(a=a.index,b=b.index,c=c.index,confirmed=c.confirmed,
                    impulse=impulse,correction_area=area(bars,b.index,c.index),
                    correction_duration=duration,correction_low=c.price,
                    target=c.price+impulse),'qualified'
    return None,'no_core_n'


def effective_pressures(bars, points, core, trigger, ambiguities=()):
    """Unbroken daily peaks with a resolved correction of matching scale.

    Scale uses the current daily correction's duration and range, rather than
    accepting every microscopic historical pivot. This is a quant convention.
    A prior closing breakout consumes resistance; no age cutoff is imposed.
    """
    levels=[];audit=[]
    core_range=bars[core['b']].high-bars[core['c']].low
    for peak,trough in zip(points,points[1:]):
        if peak.kind!='high' or trough.kind!='low' or peak.index>=core['a']:
            continue
        reason='effective'
        if peak.price<=trigger:reason='below_trigger'
        elif any(peak.index<=r['index']<=trough.index for r in ambiguities):reason='order_unknown'
        elif trough.index>core['a']:reason='unresolved_before_core'
        elif any(x.close>peak.price for x in bars[peak.index+1:]):reason='previously_broken'
        elif (trough.index-peak.index<core['correction_duration']
              or peak.price-trough.price<core_range):reason='smaller_than_core_correction'
        audit.append(dict(date=bars[peak.index].date,price=peak.price,
                          trough_date=bars[trough.index].date,reason=reason))
        if reason=='effective':levels.append(peak.price)
    return levels,audit


def hierarchy_double_bottom(bars, left=2, right=2, tolerance=.06):
    candidates,reason=hierarchy_double_bottom_candidates(bars,left,right,tolerance)
    return (max(candidates,key=lambda x:x['pattern_area']),'qualified') if candidates else (None,reason)


def hierarchy_double_bottom_candidates(bars, left=2, right=2, tolerance=.06,
                                       allow_delayed=False, points=None, floor_mode='low'):
    """Find enclosing W on its first observed closing breakout, without future bars.

    Interior extrema remain visible but do not replace the enclosing troughs.
    Reject pairs containing a deeper third trough: that is a different structure.
    Volume is evidence, not a compulsory reversal definition.
    """
    if floor_mode not in ('low','close'):raise ValueError('floor_mode')
    # Necessary condition for a first closing breakout; exact shortcut, not a
    # new filter. Any neckline below the latest close was already crossed if
    # the previous close was at least as high.
    if len(bars)<2 or (not allow_delayed and bars[-1].close<=bars[-2].close):
        return [],'no_enclosing_w_breakout'
    if points is None:points=swings(bars,left,right)
    lows=[p for p in points if p.kind=='low']
    # Reuse each suffix maximum rather than rescanning it for every old trough.
    prior_close_max=[float('-inf')]*len(bars)
    for i in range(len(bars)-2,-1,-1):
        prior_close_max[i]=max(bars[i].close,prior_close_max[i+1])
    candidates=[]
    for j,c in enumerate(lows):
        # A delayed breakout can first become observable today only when the
        # right trough is newly confirmed today. Otherwise today's close must
        # exceed every earlier close since that trough, even in delayed mode.
        if (not allow_delayed or c.confirmed<len(bars)-1) and prior_close_max[c.index]>=bars[-1].close:
            continue
        for a in lows[:j]:
            if abs(c.price/a.price-1)>tolerance:
                continue
            segment=bars[a.index:c.index+1]
            floor=min(a.price,c.price)
            if min(getattr(x,floor_mode) for x in segment)<floor or min(getattr(x,floor_mode) for x in bars[c.index:])<floor:
                continue
            neck=max(x.high for x in bars[a.index+1:c.index])
            if bars[c.index].close>neck:
                continue
            # A stale historical breakout is not a new directional opportunity.
            breakout=next((i for i in range(c.index+1,len(bars)) if bars[i].close>neck),None)
            observable=max(c.confirmed,breakout) if breakout is not None else None
            # Once the right trough is first known, price can already be in a
            # neck retest. Registration uses the historical first breakout;
            # the pool applies the same failure tolerance as existing candidates.
            if (observable!=len(bars)-1 if allow_delayed else
                    bars[-1].close<=neck or breakout!=len(bars)-1):
                continue
            before=[p for p in points if p.index<a.index]
            origins=[p for p in before if p.kind=='high' and p.price>neck]
            if not origins:
                continue
            origin=origins[-1]
            prior=[area(bars,l.index,h.index) for l,h in zip(before,before[1:])
                   if l.kind=='low' and h.kind=='high' and l.index>=origin.index]
            measured=area(bars,a.index,c.index)
            if prior and measured<=max(prior):
                continue
            candidates.append(dict(first=a.index,second=c.index,confirmed=c.confirmed,
                neckline=neck,bottom=floor,origin=origin.index,pattern_area=measured,
                prior_area=max(prior,default=0),
                first_breakout_index=breakout,first_observable_index=observable,
                left_volume=sum(x.volume for x in bars[a.index:c.index])/(c.index-a.index),
                right_volume=sum(x.volume for x in bars[c.index:])/len(bars[c.index:])))
    if not candidates:
        return [],'no_enclosing_w_breakout'
    return candidates,'qualified'


def retest_confirmation(bars, pending, minimum=3):
    """Sloping retest turns up; horizontal retest holds and recovers internally.

    A horizontal hold need not exceed its initial upper wick. All observations
    include only completed bars, and every branch requires a recovery signal.
    """
    start=pending.get('retest_start')
    if start is None or len(bars)-1-start<minimum:
        return None
    segment=bars[start:]
    floor=min(x.low for x in segment)
    width=max(x.high for x in segment)-floor
    impulse=max(x.high for x in bars[pending['second']:start+1])-pending['bottom']
    if width>=impulse or bars[-1].close<pending['neckline']:
        return None
    last,previous=segment[-1],segment[-2]
    if last.low>=previous.low and last.close>previous.high:
        return dict(kind='sloping',floor=floor)
    # Stable closing range above the neck; higher low and recovery through the
    # closing range's midpoint, rather than an additional whole-box breakout.
    closes=[x.close for x in segment]
    if (min(closes)>=pending['neckline'] and last.low>=previous.low
            and last.close>previous.close
            and last.close>=(min(closes)+max(closes))/2):
        return dict(kind='horizontal',floor=floor)
    return None


def structured_retest(bars, pending, minimum=3, maximum=14, recovery_mode='local'):
    """Observe a complete post-breakout adjustment using completed bars only.

    Engineering convention: two declining closes distinguish an adjustment
    from a single pause; overlapping ranges distinguish horizontal holds.
    Peak-bar lows are excluded because intrabar ordering is unknown.
    """
    if recovery_mode not in ('local', 'boundary'):
        raise ValueError('Invalid recovery_mode')
    breakout=pending['breakout_index']
    if len(bars)-1<=breakout:
        return None,dict(reason='waiting_post_breakout')
    if len(bars)-1-breakout>maximum:
        return None,dict(reason='retest_expired')
    peak=max(range(breakout,len(bars)-1),key=lambda i:(bars[i].high,i))
    start=peak+1
    prior=bars[start:-1]
    observation=dict(peak_date=bars[peak].date,retest_start_date=bars[start].date,
                     retest_start_index=start,correction_duration=len(prior))
    if len(prior)<minimum:
        return None,dict(observation,reason='adjustment_not_complete')
    if len(prior)>maximum:
        return None,dict(observation,reason='retest_expired')
    impulse=bars[peak].high-pending['bottom']
    segment=bars[start:]
    floor=min(b.low for b in segment)
    width=max(b.high for b in segment)-floor
    closes=[bars[peak].close]+[b.close for b in prior]
    declines=sum(y<x for x,y in zip(closes,closes[1:]))
    trough=min(range(start,len(bars)-1),key=lambda i:(bars[i].low,-i))
    observation.update(trough_date=bars[trough].date,correction_range=width,
                       declining_closes=declines)
    if impulse<=0 or width>=impulse or declines<2 or min(closes[1:])>=closes[0]:
        return None,dict(observation,reason='no_matched_adjustment')
    last,previous=bars[-1],bars[-2]
    if last.close<pending['neckline'] or last.low<previous.low or last.low<bars[trough].low:
        return None,dict(observation,reason='recovery_not_confirmed')
    # A falling leg needs an observed trough and recovery through the prior bar.
    falling=prior[-1].close<prior[0].close
    # Boundary mode is an explicit conservative execution convention, not a
    # claim that the book defines recovery with this numerical rule. A single
    # small bullish bar at the end of a long decline is insufficient: recover
    # the last rebound high already confirmed before this decision. Without a
    # rebound, use the first post-peak adjustment bar's high.
    rebound=[p for p in swings(bars[:-1],2,2)
             if p.kind=='high' and start<=p.index<trough]
    sloping_trigger=(rebound[-1].price if rebound else bars[start].high)
    if falling and last.close>previous.high:
        trigger=sloping_trigger if recovery_mode=='boundary' else previous.high
        observation.update(recovery_trigger=trigger, recovery_mode=recovery_mode)
        if last.close>trigger:
            return dict(kind='sloping',floor=floor,**observation),observation
        return None,dict(observation,reason='adjustment_boundary_not_recovered')
    overlapping=all(max(a.low,b.low)<=min(a.high,b.high) for a,b in zip(prior,prior[1:]))
    box_closes=[b.close for b in prior]
    trigger=(max(box_closes) if recovery_mode=='boundary'
             else (min(box_closes)+max(box_closes))/2)
    observation.update(recovery_trigger=trigger,recovery_mode=recovery_mode)
    if (overlapping and min(box_closes)>=pending['neckline']
            and last.close>previous.close
            and last.close>trigger):
        return dict(kind='horizontal',floor=floor,**observation),observation
    return None,dict(observation,reason='recovery_not_confirmed')


def rhythm(bars, core, left=1, right=1, lower_bars=None, hours_per_day=4, points=None, planned=False, ownership=False):
    """A smaller N must follow the core correction, not merely a bullish candle."""
    observed=lower_bars if lower_bars is not None else bars
    if not observed:
        return None,'missing_lower_cycle'
    points=swings(observed,left,right) if points is None else points
    for i in range(len(points)-3,-1,-1):
        a,b,c=points[i:i+3]
        if ((a.kind,b.kind,c.kind)!=('low','high','low')
                or observed[a.index].date[:8]<core.get('rhythm_start_date',bars[core['c']].date)[:8]
                or observed[c.index].date[:8]<core.get('rhythm_floor_date',bars[core['c']].date)[:8]):
            continue
        if ownership and (b.price<=a.price or c.price>=b.price):
            return None,'small_n_invalid_geometry'
        duration=c.index-b.index
        impulse_time=b.index-a.index
        divisor=hours_per_day if lower_bars is not None else 1
        if (c.price<=a.price or duration<1 or duration/divisor>=core['correction_duration']
                or duration>impulse_time):
            return None,'small_n_not_matched'
        if min(x.low for x in observed[c.index:])<c.price:
            return None,'small_rhythm_failed'
        small_area=area(observed,b.index,c.index)/divisor
        if small_area>=core['correction_area']:
            return None,'small_n_not_smaller'
        impulse=b.price-a.price
        retracement=b.price-c.price
        if retracement/duration>=impulse/impulse_time:
            return None,'small_correction_too_fast'
        if not planned and (observed[-1].close<=b.price or observed[-1].close<=observed[-1].open):
            return None,'rhythm_not_triggered'
        kind='outside' if min(x.low for x in observed[a.index:c.index+1])>max(
            x.high for x in bars[core['b']:core['c']+1]) else 'inside'
        return dict(a=a.index,b=b.index,c=c.index,kind=kind,
                    stop=c.price,trigger=b.price,small_area=small_area,date=observed[c.index].date,
                    owner_id=core.get('owner_id'),a_date=observed[a.index].date,
                    b_date=observed[b.index].date,confirmed_date=observed[c.confirmed].date),'qualified'
    return None,'no_small_n'
