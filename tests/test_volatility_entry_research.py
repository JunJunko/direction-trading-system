from dataclasses import replace
from trading_system.domain import Bar,Intent
from trading_system.volatility_entry_research import prior_atr,VolatilityEntryBacktest
from trading_system.engine import Backtest

def history():return [Bar('X',f'202601{i:02}',10,10.2,9.8,10,100,1) for i in range(1,16)]

def test_prior_atr_excludes_entry_and_future_bars():
    bars=history();expected=prior_atr(bars,'20260116',1)
    assert abs(expected[0]-.4)<1e-12 and expected[1]=='20260115'
    assert prior_atr(bars+[Bar('X','20260116',10,100,1,50,100),Bar('X','20260117',10,200,1,100,100)],'20260116',1)==expected

def test_factor_adjustment_and_insufficient_history():
    assert abs(prior_atr(history(),'20260116',2)[0]-.2)<1e-12
    assert prior_atr(history()[:14],'20260116',1)==(None,None)
    # Split inside the lookback must not create a false price gap.
    bars=[replace(b,open=b.open/2,high=b.high/2,low=b.low/2,close=b.close/2,factor=2) if i>=8 else b for i,b in enumerate(history())]
    assert abs(prior_atr(bars,'20260116',2)[0]-.2)<1e-12

def test_gate_only_at_execution_and_preserves_original_rejection(monkeypatch):
    monkeypatch.setattr(Backtest,'assess_entry',lambda *a:dict(quantity=100,risk_reason='approved'))
    e=object.__new__(VolatilityEntryBacktest)
    e.config={'volatility_entry_filter':dict(scope='W',period=14,min_stop_atr=.5)}
    e.histories={'X':history()};e.execution_factors={'X':1}
    i=Intent('s','X','20260115',10,9.9,12,'id','direct_w',dict(entry_mode='w_retest'))
    assert e.assess_entry(i,10,1000,1000,{},'20260115')['quantity']==100
    assert e.assess_entry(i,10,1000,1000,{},'20260116')['quantity']==0
    assert e.assess_entry(replace(i,stop=9.8),10,1000,1000,{},'20260116')['quantity']==100
    assert e.assess_entry(replace(i,evidence=dict(entry_mode='ihs_breakout')),10,1000,1000,{},'20260116')['quantity']==100
    monkeypatch.setattr(Backtest,'assess_entry',lambda *a:dict(quantity=0,risk_reason='max_positions'))
    assert e.assess_entry(i,10,1000,1000,{},'20260116')['risk_reason']=='max_positions'
