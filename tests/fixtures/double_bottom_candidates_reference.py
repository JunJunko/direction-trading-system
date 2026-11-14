"""Unoptimized v5.12 enumerator frozen before backtest acceleration."""
from trading_system.structure import swings,area

def hierarchy_double_bottom_candidates(bars, left=2, right=2, tolerance=.06,
                                       allow_delayed=False):
    """Find enclosing W on its first observed closing breakout, without future bars.

    Interior extrema remain visible but do not replace the enclosing troughs.
    Reject pairs containing a deeper third trough: that is a different structure.
    Volume is evidence, not a compulsory reversal definition.
    """
    # Necessary condition for a first closing breakout; exact shortcut, not a
    # new filter. Any neckline below the latest close was already crossed if
    # the previous close was at least as high.
    if len(bars)<2 or (not allow_delayed and bars[-1].close<=bars[-2].close):
        return [],'no_enclosing_w_breakout'
    points=swings(bars,left,right)
    lows=[p for p in points if p.kind=='low']
    candidates=[]
    for j,c in enumerate(lows):
        if not allow_delayed and max(x.close for x in bars[c.index:-1])>=bars[-1].close:
            continue
        for a in lows[:j]:
            if abs(c.price/a.price-1)>tolerance:
                continue
            segment=bars[a.index:c.index+1]
            floor=min(a.price,c.price)
            if min(x.low for x in segment)<floor or min(x.low for x in bars[c.index:])<floor:
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


