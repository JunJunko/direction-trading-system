"""Book pp.95-98 time/area matching; explicit research approximation."""
from dataclasses import replace
from math import ceil
from .domain import ExitIntent
from .ihs_geometry import atr_before
from .pressure_support_trend import PressureSupportTrend


class MatchedCycleExit(PressureSupportTrend):
    def __init__(self, name, calendar, weekends, *, expansion_exit=False):
        super().__init__(name, calendar, weekends)
        self.expansion_exit = expansion_exit
        self.indices = {d:i for i,d in enumerate(calendar)}
        self.anchor = self.peak = self.peak_index = self.peak_atr = None
        self.low = self.low_date = self.low_index = self.previous_index = None
        self.reference = None

    def manage(self, history, position):
        b = history[-1]
        if self.pending or self.last_date == b.date:
            return [], []
        exits, events = super().manage(history, position)
        if exits:
            return exits, events
        i = self.indices[b.date]
        price, high, low = b.close*b.factor, b.high*b.factor, b.low*b.factor
        economic = [replace(v,open=v.open*v.factor,high=v.high*v.factor,
                            low=v.low*v.factor,close=v.close*v.factor,factor=1)
                    for v in history[-16:]]
        atr = atr_before(economic,len(economic)-1)
        if self.peak is None or self.previous_index != i-1:
            self.anchor = self.peak_index = i
            self.peak, self.peak_atr = high, atr
            self.low = self.low_date = self.low_index = None
            self.reference = None
            self.previous_index = i
            return [],events
        self.previous_index = i
        if price > self.peak:
            # Do not infer whether today's low came before today's breakout.
            duration = i-self.peak_index-1
            impulse = self.peak_index-self.anchor+1
            depth = self.peak-self.low if self.low is not None else 0
            matched = (self.low is not None and self.peak_atr is not None
                       and duration >= max(2,ceil(impulse/3)) and depth >= self.peak_atr)
            events.append(dict(date=b.date,event='correction_match_review',matched=matched,
                duration=duration,impulse_duration=impulse,depth=depth,atr=self.peak_atr,
                formed=self.low_date,confirmed=b.date))
            if matched:
                self._raise_support(self.low,b,position,events,'matched_resumed_low',self.low_date,b.date)
                self.reference=dict(duration=duration,depth=depth,area=(duration+1)*depth)
                self.anchor=self.low_index
            self.peak,self.peak_index,self.peak_atr=high,i,atr
            self.low = self.low_date = self.low_index = None
            return [],events
        if self.low is None or low < self.low:
            self.low,self.low_date,self.low_index=low,b.date,i
        duration=i-self.peak_index
        depth=max(0,self.peak-self.low)
        ref=self.reference
        if (self.expansion_exit and ref and duration >= ref['duration']
                and (duration+1)*depth > ref['area'] and self.peak-price > ref['depth']):
            self.pending=True
            events.append(dict(date=b.date,event='matched_correction_expanded',duration=duration,
                depth=depth,area=(duration+1)*depth,reference=dict(ref),execution='next_executable_open'))
            return [ExitIntent(self.name,b.symbol,b.date,position.setup_id,'matched_correction_expanded')],events
        return [],events
