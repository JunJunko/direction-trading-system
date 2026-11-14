"""Experimental daily-core exits inspired by book pp.295,302-305.

Two-right-bar pivots and close execution are implementation hypotheses,
not literal rules supplied by the book. Weekly v7 support remains a floor.
"""
from .pressure_support_trend import PressureSupportTrend
import math


class CoreCycleExit(PressureSupportTrend):
    def __init__(self, name, calendar, weekends, *, require_resume=True, breakout_atr=.1):
        super().__init__(name, calendar, weekends, breakout_atr=breakout_atr)
        if type(require_resume) is not bool:
            raise ValueError('require_resume must be bool')
        self.require_resume = require_resume
        self.session_index = {d: i for i, d in enumerate(calendar)}
        self.daily_high = None
        self.daily_candidates = []

    def manage(self, history, position):
        if self.pending or self.last_date == history[-1].date:
            return [], []
        exits, events = super().manage(history, position)
        if exits:
            return exits, events
        b = history[-1]
        if len(history) < 5:
            return [], events
        window = history[-5:]
        indices = [self.session_index.get(v.date) for v in window]
        contiguous = (all(i is not None for i in indices)
                      and all(y == x + 1 for x, y in zip(indices, indices[1:])))
        if contiguous:
            p = window[2]
            low, high = p.low * p.factor, p.high * p.factor
            is_low = all(low < v.low*v.factor for j, v in enumerate(window) if j != 2)
            is_high = all(high > v.high*v.factor for j, v in enumerate(window) if j != 2)
            if is_low != is_high and p.date > position.entry_date:
                if is_high:
                    self.daily_high = dict(price=high, date=p.date)
                elif not self.require_resume or (self.daily_high and self.daily_high['date'] < p.date):
                    self.daily_candidates.append(dict(price=low, date=p.date,
                        confirmed=b.date, trigger=self.daily_high['price'] if self.daily_high else None))
        close = b.close*b.factor
        remaining = []
        for p in self.daily_candidates:
            # A broken, unpromoted valley can never be resurrected later.
            if close < p['price']:
                continue
            if not self.require_resume or close > p['trigger']:
                self._raise_support(p['price'], b, position, events,
                    'daily_resumed_low' if self.require_resume else 'daily_confirmed_low',
                    p['date'], b.date)
            else:
                remaining.append(p)
        self.daily_candidates = remaining
        return [], events


class ProfitGivebackExit(PressureSupportTrend):
    """Separate hypothesis: after a close >=2 initial price-risk units,
    retain 50% of the maximum close-to-entry price gain via close support.
    Threshold is experimental; it is not a promise of net profit retention.
    """
    def __init__(self, name, calendar, weekends, *, activation_r=2., retain=.5):
        super().__init__(name, calendar, weekends)
        if not all(type(x) in (int,float) and math.isfinite(x) for x in (activation_r,retain)):
            raise ValueError('Finite numeric parameters required')
        if activation_r <= 0 or not 0 < retain < 1:
            raise ValueError('Invalid giveback parameters')
        self.activation_r, self.retain = activation_r, retain
        self.entry_economic = self.unit_risk = self.peak_close = None

    def manage(self, history, position):
        if self.pending or self.last_date == history[-1].date:
            return [], []
        b=history[-1]
        if self.entry_economic is None:
            self.entry_economic=position.entry*position.factor
            self.unit_risk=position.initial_risk/position.quantity*position.factor
        exits,events=super().manage(history,position)
        if exits:
            return exits,events
        close=b.close*b.factor
        self.peak_close=max(close,self.peak_close if self.peak_close is not None else close)
        if self.peak_close-self.entry_economic >= self.activation_r*self.unit_risk:
            level=self.entry_economic+self.retain*(self.peak_close-self.entry_economic)
            self._raise_support(level,b,position,events,'close_profit_giveback',b.date,b.date)
        return [],events
