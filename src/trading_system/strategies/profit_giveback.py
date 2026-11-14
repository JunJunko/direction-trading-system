"""Independent v8 experiment; v7 entry selection and initial stops preserved."""
from .pressure_support_w import PressureSupportW
from .pressure_support_ihs import PressureSupportIHS
from ..core_cycle_exit import ProfitGivebackExit


class ProfitGivebackW(PressureSupportW):
    def manage_position(self, history, position):
        if self.calendar is None:
            raise ValueError('Trend management requires exchange calendar')
        if position.setup_id not in self.managers:
            self.managers[position.setup_id] = ProfitGivebackExit(
                self.name, self.calendar, self.weekends)
            self.managers[position.setup_id].breakout_atr = self.pressure_breakout_atr
        return super().manage_position(history, position)


class ProfitGivebackIHS(PressureSupportIHS):
    def trend_manager_class(self, name, calendar, weekends):
        manager = ProfitGivebackExit(name, calendar, weekends)
        manager.breakout_atr = self.pressure_breakout_atr
        return manager
