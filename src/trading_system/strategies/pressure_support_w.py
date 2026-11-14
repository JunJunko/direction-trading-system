"""Qualified W entries with the same v7 pressure/support exit as IHS."""
import math
from dataclasses import replace
from .qualified_w_retest import QualifiedWRetest
from ..pressure_support_trend import PressureSupportTrend


class PressureSupportW(QualifiedWRetest):
    def __init__(self, name, params):
        params = dict(params)
        self.pressure_breakout_atr = params.pop('pressure_breakout_atr', .1)
        v = self.pressure_breakout_atr
        if type(v) not in (int, float) or not math.isfinite(v) or v < 0:
            raise ValueError('Invalid pressure breakout buffer')
        super().__init__(name, params)
        self.calendar = self.weekends = None
        self.managers = {}

    def set_trend_calendar(self, calendar, weekends):
        self.calendar, self.weekends = calendar, weekends

    def on_close(self, history, week_ends):
        intents, events = super().on_close(history, week_ends)
        # Exit metadata only; selection, bracket, price and timing stay unchanged.
        intents = [replace(i, evidence=dict(i.evidence, target_exit_rule='reference_only')) for i in intents]
        for e in events:
            if e['event'] == 'entry_intent':
                e['target_exit_rule'] = 'reference_only'
        return intents, events

    def manage_position(self, history, position):
        if self.calendar is None:
            raise ValueError('Weekly trend management requires exchange calendar')
        if position.setup_id not in self.managers:
            self.managers[position.setup_id] = PressureSupportTrend(
                self.name, self.calendar, self.weekends, breakout_atr=self.pressure_breakout_atr)
        manager = self.managers[position.setup_id]
        exits, events = manager.manage(history, position)
        position.plan.update(target_exit_rule='reference_only',
            dynamic_support_economic=manager.protection,
            dynamic_pressure_economic=manager.pressure,
            dynamic_support_source=manager.support_source)
        if manager.protection is not None:
            position.plan['main_trend_protection_economic'] = manager.protection
        for e in events:
            e.update(symbol=position.symbol, strategy=self.name, setup_id=position.setup_id)
        return exits, events
