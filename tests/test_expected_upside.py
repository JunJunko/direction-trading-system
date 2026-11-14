from dataclasses import replace
import pytest
from trading_system.domain import Intent
from trading_system.risk import RiskManager

def cfg():return dict(risk_per_trade=.005,max_portfolio_risk=.02,max_position_weight=.1,max_gross_weight=.5,max_positions=5,min_rr=3,min_expected_upside=.05)
def assess(i,fill=10):return RiskManager(cfg()).assess(i,fill,1000000,1000000,{}, {},.0003,.0005,slippage=.001)

def test_strict_price_upside_and_execution_gap():
    i=Intent('s','X','20260101',10,9.95,10.5,'id','test')
    assert assess(i)['risk_reason']=='expected_upside_not_above_threshold'
    assert assess(replace(i,target=10.49))['quantity']==0
    assert assess(replace(i,target=10.51))['quantity']>0
    assert assess(replace(i,target=10.51),10.02)['risk_reason']=='expected_upside_not_above_threshold'

def test_rr_still_required_and_input_validation():
    i=Intent('s','X','20260101',10,9,10.6,'id','test')
    assert assess(i)['risk_reason']=='net_rr_not_above_threshold'
    for value in [-1,float('nan'),float('inf'),True,'5%']:
        with pytest.raises(ValueError):RiskManager(dict(cfg(),min_expected_upside=value))
