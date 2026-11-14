"""Frozen alternatives to the v13 small daily profit protection; separate arms."""
from .ihs_price_line_research import ProfitActivatedIHS
from .pressure_support_ihs import PressureSupportIHS


class LargerProfitStructureIHS(ProfitActivatedIHS):
    # Only change the scale: eleven-bar strict pivot versus five-bar pivot.
    profit_pivot_side = 5
    profit_support_source = 'profit_activated_larger_daily_low'


class HalfProfitRetentionIHS(PressureSupportIHS):
    """After 1R, retain half of peak marked profit; next-session close protection."""
    def __init__(self,name,params):
        super().__init__(name,params)
        self.profit_activation={};self.profit_peaks={}

    def manage_position(self,history,position):
        exits,events=super().manage_position(history,position)
        if exits:return exits,events
        bar=history[-1];pid=position.setup_id
        marked=(bar.close-position.entry)*position.quantity-position.entry_fee
        peak,peak_date=self.profit_peaks.get(pid,(float('-inf'),None))
        if marked>peak:peak,peak_date=marked,bar.date
        self.profit_peaks[pid]=(peak,peak_date)
        if pid not in self.profit_activation and marked>=position.initial_risk:
            self.profit_activation[pid]=bar.date
            events.append(dict(date=bar.date,symbol=position.symbol,strategy=self.name,setup_id=pid,event='profit_protection_activated',marked_profit=marked,initial_risk=position.initial_risk,activation_R=1,accounting='marked_profit_after_entry_fee_before_exit_fee'))
        if pid not in self.profit_activation:return exits,events
        # Entry fee is included once. Monetary P/L and the economic price are
        # invariant when the engine adjusts entry price and quantity for factors.
        level=(position.entry+(position.entry_fee+.5*peak)/position.quantity)*position.factor
        if level>=bar.close*bar.factor:return exits,events
        manager=self.managers[pid];added=[]
        manager._raise_support(level,bar,position,added,'profit_peak_retention_50pct',peak_date,bar.date)
        for e in added:e.update(symbol=position.symbol,strategy=self.name,setup_id=pid,activation_date=self.profit_activation[pid],peak_marked_profit=peak,peak_date=peak_date,retain_fraction=.5,accounting='marked_profit_after_entry_fee_before_exit_fee')
        events.extend(added)
        position.plan.update(dynamic_support_economic=manager.protection,main_trend_protection_economic=manager.protection,dynamic_support_source=manager.support_source)
        return exits,events
