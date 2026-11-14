"""Add a confirmed daily higher-low support to the original weekly manager."""
from .pressure_support_ihs import PressureSupportIHS
from ..volatility_entry_research import prior_atr


class DailyProtectedIHS(PressureSupportIHS):
    def __init__(self, name, params):
        super().__init__(name, params)
        self.daily_lows = {}

    def manage_position(self, history, position):
        exits, events = super().manage_position(history, position)
        if exits:
            return exits, events
        bars = [b for b in history if b.date >= position.entry_date]
        if len(bars) < 6:
            return exits, events
        bar, pivot = bars[-1], bars[-3]
        low = pivot.low*pivot.factor
        neighbors = bars[-5:-3]+bars[-2:]
        if low >= min(b.low*b.factor for b in neighbors):
            return exits, events
        previous = self.daily_lows.get(position.setup_id, bars[0].low*bars[0].factor)
        self.daily_lows[position.setup_id] = low
        if low <= previous:
            return exits, events
        atr, _ = prior_atr(history, bar.date, bar.factor)
        level = low - .5*atr*bar.factor
        if bar.close*bar.factor <= level:
            return exits, events
        manager = self.managers[position.setup_id]
        added = []
        manager._raise_support(level,bar,position,added,'confirmed_daily_higher_low',pivot.date,bar.date)
        for event in added:
            event.update(symbol=position.symbol,strategy=self.name,setup_id=position.setup_id,
                         daily_low=low,previous_daily_low=previous,buffer_atr=.5,atr_economic=atr*bar.factor)
        events.extend(added)
        position.plan.update(dynamic_support_economic=manager.protection,
                             main_trend_protection_economic=manager.protection,
                             dynamic_support_source=manager.support_source)
        return exits, events
