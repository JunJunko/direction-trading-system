"""Causal support zones attached to a confirmed entry-rhythm trough."""


def confirmed_trough_zone(bars, small, known_at, max_entry_risk):
    """Use only the already-confirmed C candle, at the current factor."""
    c=small['c']
    if not 0<=c<len(bars):
        raise ValueError('Missing support candle')
    candle=bars[c]
    confirmed=small.get('confirmed_date')
    if (candle.date!=small['date'] or not confirmed or
            not candle.date<confirmed<=known_at or candle.low!=small['stop']):
        raise ValueError('Support requires an observed, confirmed rhythm trough')
    return dict(support_mode='confirmed_trough',support_lower=candle.low,
                support_upper=min(candle.open,candle.close),
                support_source_date=candle.date,support_known_at=confirmed,
                support_max_entry_risk=max_entry_risk,support_exit_on_touch=True)


def support_rebound(bars, small, max_entry_risk, tighten=False):
    """Completed bullish recovery near a known trough; executable next session."""
    current=bars[-1]
    zone=confirmed_trough_zone(bars,small,current.date,max_entry_risk)
    if any(b.low<=zone['support_lower'] for b in bars[small['c']+1:]):
        return None,'support_already_touched'
    if current.close<=current.open or current.close<=bars[-2].close:
        return None,'bullish_recovery_not_confirmed'
    active=zone['support_lower']
    if tighten:
        known=next(i for i,b in enumerate(bars) if b.date==zone['support_known_at'])
        if known<14:return None,'insufficient_frozen_true_range_history'
        atr=sum(max(bars[i].high-bars[i].low,abs(bars[i].high-bars[i-1].close),abs(bars[i].low-bars[i-1].close)) for i in range(known-13,known+1))/14
        active=max(active,zone['support_upper']-.15*atr)
        if active>=current.close:return None,'invalid_tightened_stop'
        zone.update(support_stop_rule='rebound_upper_band',support_active_stop_kind='upper_retest_band',support_defense_lower=active,support_defense_upper=zone['support_upper'],support_reference_atr=atr)
    if (current.close-active)/current.close>max_entry_risk+1e-12:
        return None,'confirmation_too_far_from_support'
    return dict(zone,entry_mode='support_rebound',entry_order='next_open',
                rebound_confirmed_at=current.date,rebound_signal_close=current.close), 'qualified'


def support_band_retest(bars,small,max_entry_risk,atr_lookback=14,atr_fraction=.15,max_width=.005):
    """A frozen band INSIDE known support, activated by a later upper-edge retest.

    The initial stop is the band's lower edge. The original support floor is
    context, never a wider fallback after a band breach.
    """
    current=bars[-1]
    zone=confirmed_trough_zone(bars,small,current.date,max_entry_risk)
    known_at=zone['support_known_at']
    if current.date<=known_at:return None,'waiting_after_support_confirmation'
    known=next(i for i,b in enumerate(bars) if b.date==known_at)
    if known<atr_lookback:return None,'insufficient_frozen_true_range_history'
    ranges=[max(bars[i].high-bars[i].low,abs(bars[i].high-bars[i-1].close),
                abs(bars[i].low-bars[i-1].close)) for i in range(known-atr_lookback+1,known+1)]
    atr=sum(ranges)/atr_lookback
    upper=zone['support_upper'];lower=max(zone['support_lower'],upper-atr*atr_fraction)
    width=(upper-lower)/upper
    if not 0<width<=max_width+1e-12:return None,'support_defense_band_not_narrow'
    if any(b.low<=zone['support_lower'] for b in bars[small['c']+1:]):
        return None,'support_already_touched'
    previous=bars[-2]
    if previous.date<known_at or previous.low<=upper:
        return None,'upper_edge_not_previously_held'
    if current.low>upper:return None,'no_upper_edge_retest'
    if current.low<=lower:return None,'defense_band_breached_during_confirmation'
    if current.close<=upper or current.close<=current.open or current.close<=previous.close:
        return None,'upper_edge_recovery_not_confirmed'
    if (current.close-lower)/current.close>max_entry_risk+1e-12:
        return None,'confirmation_too_far_from_defense_band'
    return dict(zone,entry_mode='support_band_retest',entry_order='next_open',
        support_stop_rule='upper_retest_band',support_active_stop_kind='upper_retest_band',
        support_defense_lower=lower,support_defense_upper=upper,support_defense_max_width=max_width,
        support_defense_width_pct=width,support_reference_atr=atr,support_atr_fraction=atr_fraction,
        support_band_known_at=known_at,support_stand_date=previous.date,support_retest_date=current.date,
        rebound_confirmed_at=current.date,rebound_signal_close=current.close),'qualified'
