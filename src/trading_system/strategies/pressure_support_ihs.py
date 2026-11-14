"""v7: v5 entries, dynamic pressure-to-support holding experiment."""
import math
from .breakout_trend_ihs import BreakoutTrendIHS
from ..pressure_support_trend import PressureSupportTrend


class PressureSupportIHS(BreakoutTrendIHS):
    def __init__(self, name, params):
        params = dict(params)
        self.pressure_breakout_atr = params.pop('pressure_breakout_atr', .1)
        v = self.pressure_breakout_atr
        if type(v) not in (int, float) or not math.isfinite(v) or v < 0:
            raise ValueError('Invalid pressure breakout buffer')
        super().__init__(name, params)

    def trend_manager_class(self, name, calendar, weekends):
        return PressureSupportTrend(name, calendar, weekends, breakout_atr=self.pressure_breakout_atr)

    def manage_position(self, history, position):
        exits, events = super().manage_position(history, position)
        manager = self.managers[position.setup_id]
        position.plan.update(dynamic_support_economic=manager.protection,
                             dynamic_pressure_economic=manager.pressure,
                             dynamic_support_source=manager.support_source)
        return exits, events
