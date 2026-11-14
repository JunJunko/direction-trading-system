"""One extra causal entry filter on top of the fixed no-gap-up IHS baseline."""
from .quality_entry_research import QualityEntryBacktest
from .volatility_entry_research import prior_atr

RULES={'solid_close','volume_confirmed','rising_ma20','limited_gap_down'}

def entry_features(intent,history,date,factor,opening):
    known=[b for b in history if b.date<date]
    signal=[b for b in known if b.date<=intent.date]
    if len(signal)<25 or len(known)<15 or signal[-1].date!=intent.date:
        return None
    s=signal[-1];previous=signal[-21:-1]
    volume=sum(b.volume for b in previous)/20
    atr,last=prior_atr(known,date,factor)
    closes=[b.close*b.factor for b in signal[-25:]]
    old_ma=sum(closes[:20])/20;new_ma=sum(closes[-20:])/20
    return dict(close_location=(s.close-s.low)/(s.high-s.low) if s.high>s.low else 0,
        volume_ratio=s.volume/volume if volume>0 else 0,
        ma20_change=new_ma/old_ma-1,
        gap_atr=(opening-known[-1].close*known[-1].factor/factor)/atr if atr else None,
        signal_known_at=s.date,atr_known_at=last)

def extra_pass(rule,features):
    if rule not in RULES:raise ValueError(rule)
    if features is None:return False
    if rule=='solid_close':return features['close_location']>=.5
    if rule=='volume_confirmed':return features['volume_ratio']>=1
    if rule=='rising_ma20':return features['ma20_change']>=0
    return features['gap_atr'] is not None and features['gap_atr']>=-.5

class IHSEntryQualityBacktest(QualityEntryBacktest):
    def __init__(self,config,strategies):
        if config.get('quality_entry_filter')!='no_gap_up':
            raise ValueError('IHS quality experiment requires the frozen no_gap_up base')
        rule=config.get('ihs_entry_quality_filter')
        if rule is not None and rule not in RULES:raise ValueError(rule)
        super().__init__(config,strategies)

    def assess_entry(self,intent,fill,equity,cash,marks,date,phase='signal'):
        result=super().assess_entry(intent,fill,equity,cash,marks,date,phase)
        rule=self.config.get('ihs_entry_quality_filter')
        if rule is None or phase!='execution':return result
        factor,opening=self.quality_today[intent.symbol]
        features=entry_features(intent,self.histories.get(intent.symbol,[]),date,factor,opening)
        passed=extra_pass(rule,features)
        result.update(ihs_quality_rule=rule,ihs_quality_pass=passed,pre_ihs_quality_reason=result['risk_reason'])
        if features:result.update({'ihs_quality_'+key:value for key,value in features.items()})
        if result['quantity'] and not passed:
            result.update(quantity=0,risk_reason='ihs_quality_'+rule)
            if 'decision' in result:result['decision']='NO_TRADE'
        return result
