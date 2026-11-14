"""v10 partial protection experiment; entry rules and min-RR unchanged."""
from .pressure_support_w import PressureSupportW
from .pressure_support_ihs import PressureSupportIHS
from ..profit_structure_trim import ProfitStructureTrim


class TrimCosts:
    def set_execution_costs(self,execution):self.trim_execution=dict(execution)

    def make_trim_manager(self,name,calendar,weekends):
        if not hasattr(self,'trim_execution'):raise ValueError('Execution cost injection required')
        m=ProfitStructureTrim(name,calendar,weekends,execution=self.trim_execution)
        m.breakout_atr=self.pressure_breakout_atr
        return m


class ProfitStructureTrimW(TrimCosts,PressureSupportW):
    def manage_position(self,history,position):
        if self.calendar is None:raise ValueError('Trend calendar required')
        if position.setup_id not in self.managers:
            self.managers[position.setup_id]=self.make_trim_manager(self.name,self.calendar,self.weekends)
        return super().manage_position(history,position)


class ProfitStructureTrimIHS(TrimCosts,PressureSupportIHS):
    def trend_manager_class(self,name,calendar,weekends):
        return self.make_trim_manager(name,calendar,weekends)
