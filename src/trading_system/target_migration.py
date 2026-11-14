"""Causal target decisions and factual level registry, research v0.1.

ATR version: arithmetic mean of 14 true ranges ending at t-1.
No target, resistance breach, or trend acceptance is itself a support pivot.
"""
from dataclasses import dataclass, field
from enum import Enum

RESEARCH_PARAMETERS=dict(atr_period=14,breakout_excess_atr=.35,breakout_body_ratio_min=.55,
    breakout_close_location_min=.75,touch_to_breakout_max_bars=0,acceptance_min_consecutive_closes=2,
    acceptance_above_target_atr=.1,candidate_max_bars_after_break=3,candidate_failure_atr=.25,
    support_buffer_atr=.5,swing_left_bars=2,swing_right_bars=2,resistance_zone_atr=.25,
    volatility_guard_atr=3.,acceptance_route='consecutive_closes',support_route='confirmed_swing_low')


class State(str,Enum):
    PRE_TARGET='PRE_TARGET'
    TARGET_TOUCHED='TARGET_TOUCHED'
    BREAKOUT_CANDIDATE='BREAKOUT_CANDIDATE'
    TREND_HOLD='TREND_HOLD'
    PRESSURE_WATCH='PRESSURE_WATCH'
    EXIT_PENDING='EXIT_PENDING'
    EXITED='EXITED'


@dataclass
class Level:
    id: str
    kind: str
    price: float
    zone_low: float
    zone_high: float
    pivot_at: int | None
    confirmed_at: int
    valid_from: int
    status: str
    origin: str


@dataclass
class PositionContext:
    trade_id: str
    entry_at: int
    entry_price: float
    shares: float
    initial_stop: float
    execution_stop: float
    neckline: float
    measured_target: float
    factor: float=1.
    state: State=State.PRE_TARGET
    target_touch_at: int | None=None
    breakout_candidate_at: int | None=None
    trend_confirmed_at: int | None=None
    consecutive_closes: int=0
    known_resistance_ids: list=field(default_factory=list)
    confirmed_support_ids: list=field(default_factory=list)
    active_pressure_warning_id: str | None=None
    structural_support: float | None=None
    volatility_guard: float | None=None


def atr_pre(bars,period=14):
    t=len(bars)-1
    if t<period+1:return None
    return sum(max(bars[i].high-bars[i].low,abs(bars[i].high-bars[i-1].close),
        abs(bars[i].low-bars[i-1].close)) for i in range(t-period,t))/period


class TargetDecisionEngine:
    def __init__(self,mode='dynamic',tick=.01,params=None):
        if mode not in ('hard','soft','dynamic'):raise ValueError('target mode')
        if tick is None or tick<=0:raise ValueError('Explicit market tick required')
        self.mode=mode;self.tick=tick;self.p=dict(RESEARCH_PARAMETERS,**(params or {}))
        if self.p['touch_to_breakout_max_bars']!=0 or self.p['acceptance_route']!='consecutive_closes':
            raise ValueError('Other touch windows / acceptance routes require a separate experiment')

    def close(self,ctx,t,bar,atr):
        if ctx.state in (State.EXIT_PENDING,State.EXITED):return None
        target=ctx.measured_target
        if self.mode=='hard':
            # Compatibility with the repository's OLD close-target execution,
            # not an invented resting intraday limit order.
            if bar.close>=target:
                ctx.state=State.EXIT_PENDING;return 'legacy_target_close'
            return None
        if ctx.state==State.PRE_TARGET and bar.high>=target:
            ctx.target_touch_at=t;ctx.state=State.TARGET_TOUCHED
            span=max(bar.high-bar.low,self.tick)
            strong=(atr is not None and atr>0 and bar.close>=target+self.p['breakout_excess_atr']*atr and bar.close>bar.open
                and (bar.close-bar.open)/span>=self.p['breakout_body_ratio_min']
                and (bar.close-bar.low)/span>=self.p['breakout_close_location_min'])
            if self.mode=='soft' or not strong:
                ctx.state=State.EXIT_PENDING;return 'target_touch_not_decisive' if self.mode=='dynamic' else 'soft_target_touch'
            ctx.state=State.BREAKOUT_CANDIDATE;ctx.breakout_candidate_at=t;ctx.consecutive_closes=1
            return 'breakout_candidate'
        if ctx.state==State.BREAKOUT_CANDIDATE:
            if atr is None:return None
            if bar.close<target-self.p['candidate_failure_atr']*atr or t-ctx.breakout_candidate_at>self.p['candidate_max_bars_after_break']:
                ctx.state=State.EXIT_PENDING;return 'candidate_failed'
            ctx.consecutive_closes=ctx.consecutive_closes+1 if bar.close>target+self.p['acceptance_above_target_atr']*atr else 0
            if ctx.consecutive_closes>=self.p['acceptance_min_consecutive_closes']:
                ctx.state=State.TREND_HOLD;ctx.trend_confirmed_at=t;return 'acceptance_confirmed'
            if t-ctx.breakout_candidate_at>=self.p['candidate_max_bars_after_break']:
                ctx.state=State.EXIT_PENDING;return 'candidate_expired'
        return None


class KeyLevelRegistry:
    def __init__(self,left=2,right=2,zone_atr=.25):
        self.left=left;self.right=right;self.zone_atr=zone_atr;self.levels={}

    def rescale(self,scale):
        for level in self.levels.values():
            level.price*=scale;level.zone_low*=scale;level.zone_high*=scale

    def update(self,bars,atr):
        t=len(bars)-1;created=[]
        for kind,attr in (('RESISTANCE','high'),('SUPPORT','low')):
            i=0
            while i<len(bars):
                start=i;price=getattr(bars[i],attr)
                while i+1<len(bars) and abs(getattr(bars[i+1],attr)-price)<1e-10:i+=1
                end=i;i+=1
                confirmed=end+self.right
                if start<self.left or confirmed>t:continue
                neighbours=[getattr(b,attr) for b in bars[start-self.left:start]+bars[end+1:confirmed+1]]
                good=all(price>x for x in neighbours) if kind=='RESISTANCE' else all(price<x for x in neighbours)
                if not good:continue
                key=f'{kind}:{bars[start].date}:{bars[end].date}'
                if key in self.levels:continue
                level=Level(key,kind,price,price,price,end,confirmed,confirmed+1,
                    'ACTIVE' if kind=='RESISTANCE' else 'CONFIRMED','SWING_HIGH' if kind=='RESISTANCE' else 'SWING_LOW')
                # Historical already-breached levels must not be resurrected.
                if kind=='RESISTANCE' and any(b.close>price for b in bars[confirmed+1:]):level.status='BREACHED'
                self.levels[key]=level;created.append(level)
        for level in self.levels.values():
            if level.kind=='RESISTANCE' and level.valid_from<=t and bars[-1].close>level.zone_high:
                level.status='BREACHED'
        return created

    def resistances(self,close,t,atr,tick):
        known=sorted((x for x in self.levels.values() if x.kind=='RESISTANCE' and x.status=='ACTIVE'
            and x.valid_from<=t and x.price>close+tick),key=lambda x:(x.price,x.confirmed_at,x.id))
        zones=[]
        for level in known:
            if zones and level.price-zones[-1]['zone_low']<=self.zone_atr*(atr or 0):
                z=zones[-1];z['zone_high']=level.price;z['ids'].append(level.id)
                # Deterministic earliest confirmed representative.
                if (level.confirmed_at,level.id)<(z['confirmed_at'],z['representative']):
                    z.update(price=level.price,confirmed_at=level.confirmed_at,representative=level.id)
            else:zones.append(dict(price=level.price,zone_low=level.price,zone_high=level.price,
                ids=[level.id],confirmed_at=level.confirmed_at,representative=level.id))
        return zones


class ConfirmedSupportTrail:
    def __init__(self,buffer_atr=.5):self.buffer_atr=buffer_atr

    def propose(self,ctx,registry,bars,atr):
        if atr is None:return ctx.execution_stop,None
        t=len(bars)-1
        levels=[x for x in registry.levels.values() if x.kind=='SUPPORT' and x.pivot_at>ctx.entry_at
            and x.confirmed_at<=t and x.price>ctx.initial_stop
            and (ctx.structural_support is None or x.price>=ctx.structural_support)
            and not any(b.low<=x.price for b in bars[x.pivot_at+1:])]
        if not levels:return ctx.execution_stop,None
        best=max(levels,key=lambda x:(x.price,x.confirmed_at))
        return max(ctx.execution_stop,best.price-self.buffer_atr*atr),best
