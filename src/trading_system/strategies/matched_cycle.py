"""v9 experimental entries unchanged, matched-cycle holding management."""
from .pressure_support_w import PressureSupportW
from .pressure_support_ihs import PressureSupportIHS
from ..matched_cycle_exit import MatchedCycleExit


class MatchedCycleW(PressureSupportW):
    def __init__(self,name,params):
        params=dict(params)
        self.expansion_exit=params.pop('expansion_exit',False)
        if type(self.expansion_exit) is not bool:raise ValueError('expansion_exit must be bool')
        super().__init__(name,params)

    def manage_position(self,history,position):
        if self.calendar is None:raise ValueError('Trend management requires calendar')
        if position.setup_id not in self.managers:
            m=MatchedCycleExit(self.name,self.calendar,self.weekends,expansion_exit=self.expansion_exit)
            m.breakout_atr=self.pressure_breakout_atr
            self.managers[position.setup_id]=m
        return super().manage_position(history,position)


class MatchedCycleIHS(PressureSupportIHS):
    def __init__(self,name,params):
        params=dict(params)
        self.expansion_exit=params.pop('expansion_exit',False)
        if type(self.expansion_exit) is not bool:raise ValueError('expansion_exit must be bool')
        super().__init__(name,params)

    def trend_manager_class(self,name,calendar,weekends):
        m=MatchedCycleExit(name,calendar,weekends,expansion_exit=self.expansion_exit)
        m.breakout_atr=self.pressure_breakout_atr
        return m
