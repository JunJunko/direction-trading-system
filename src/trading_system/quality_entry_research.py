"""Research-only entry rejection. Read only completed history and current open."""
from .engine import Backtest
from .volatility_entry_research import prior_atr
from .ihs_geometry import neckline_at


def quality_measure(rule, intent, history, date, factor, opening, fill):
    known=[b for b in history if b.date<date]
    if rule=='span120':
        value=intent.evidence['w_separation_sessions']
        return value,value<=120,intent.date
    if rule=='no_gap_up':
        if not known:return None,False,''
        previous=known[-1]
        value=opening/(previous.close*previous.factor/factor)-1
        return value,value<=1e-12,previous.date
    if rule=='neck_half_atr':
        atr,last=prior_atr(known,date,factor)
        if atr is None:return None,False,last
        value=(fill-neckline_at(intent.evidence,date))/atr
        return value,value<.5,last
    raise ValueError(rule)


class QualityEntryBacktest(Backtest):
    def execute_interval(self,today,date,universe,entry_cash,window=None):
        self.quality_today={s:(b.factor,b.open) for s,b in today.items()}
        return super().execute_interval(today,date,universe,entry_cash,window)

    def assess_entry(self,intent,fill,equity,cash,marks,date,phase='signal'):
        result=super().assess_entry(intent,fill,equity,cash,marks,date,phase)
        rule=self.config.get('quality_entry_filter')
        if not rule or phase!='execution':return result
        factor,opening=self.quality_today[intent.symbol]
        value,passed,known=quality_measure(rule,intent,self.histories.get(intent.symbol,[]),date,factor,opening,fill)
        result.update(quality_rule=rule,quality_value=value,quality_pass=passed,quality_known_at=known,
                      pre_quality_reason=result['risk_reason'])
        if result['quantity'] and not passed:
            result.update(quantity=0,risk_reason='quality_'+rule)
            if 'decision' in result:result['decision']='NO_TRADE'
        return result
