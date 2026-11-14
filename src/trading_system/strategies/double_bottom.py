from dataclasses import dataclass
import math
from ..analysis import adjusted, pivot_lows, weekly, WeeklyCache, week_key
from ..domain import Intent


@dataclass
class Setup:
    identity: str
    neckline: float
    bottom: float
    breakout_date: str
    age: int = 0
    retest_index: int | None = None
    price_factor: float = 1.0
    pullback_index: int | None = None


class DoubleBottom:
    """Upper-cycle W -> close breakout -> daily retest -> close-confirmed restart."""
    def __init__(self, name, params):
        self.name = name
        self.p = dict(rule_version='v3', direction_cycle='weekly', left=2, right=2,
                      min_separation=3, max_separation=30, bottom_tolerance=.06,
                      min_depth=.08, prior_decline=.10, prior_lookback=12,
                      breakout_buffer=.005, retest_tolerance=.025,
                      max_retest_days=30, retest_min_days=3,
                      stop_buffer=.005, trigger_buffer=.001,
                      restart_body=.005, trail_left=2, trail_right=2)
        unknown = set(params)-set(self.p)
        if unknown:
            raise ValueError(f'Unknown double-bottom parameters: {sorted(unknown)}')
        self.p.update(params)
        if self.p['rule_version'] not in ('v3', 'v4'):
            raise ValueError('rule_version must be v3 or v4')
        if self.p['direction_cycle'] not in ('weekly', 'daily'):
            raise ValueError('direction_cycle must be weekly or daily')
        integer_keys = ('left','right','min_separation','max_separation','prior_lookback',
                        'max_retest_days','retest_min_days','trail_left','trail_right')
        for key in integer_keys:
            if type(self.p[key]) is not int or self.p[key]<1:
                raise ValueError(f'{key} must be a positive integer')
        for key in ('bottom_tolerance','min_depth','prior_decline','breakout_buffer',
                    'retest_tolerance','stop_buffer','trigger_buffer','restart_body'):
            value=self.p[key]
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<1:
                raise ValueError(f'{key} must be finite and within [0,1)')
        if self.p['min_separation']<2 or self.p['max_separation']<self.p['min_separation']:
            raise ValueError('Two troughs need an intervening neckline bar and valid separation bounds')
        if self.p['max_retest_days']<self.p['retest_min_days']:
            raise ValueError('Retest expiry must not precede minimum wait')
        self.active = {}
        self.used = set()
        self.last_processed = {}
        self.last_direction_processed = {}
        self.weekly_caches={}
        self.week_ends_ref=None
        self.end_by_week={}

    def on_close(self, history, week_ends):
        p, events = self.p, []
        if not history:
            return [], events
        last=history[-1]
        previous=self.last_processed.get(last.symbol)
        if previous==last.date:
            return [], events
        if previous and previous>last.date:
            raise ValueError('Strategy histories must advance chronologically')
        self.last_processed[last.symbol]=last.date
        b = adjusted(history[-1:])[0]
        setup = self.active.get(b.symbol)
        if setup:
            daily = adjusted(history)
            setup.age += 1
            # A known factor change rescales all stored price levels to today's raw basis.
            scale = setup.price_factor / b.factor
            setup.neckline *= scale
            setup.bottom *= scale
            setup.price_factor=b.factor
            invalid_reason = None
            if b.low < setup.bottom:
                invalid_reason='bottom_broken'
            elif b.close < setup.neckline * (1-p['retest_tolerance']):
                invalid_reason='neckline_lost'
            elif setup.age > p['max_retest_days']:
                invalid_reason='retest_expired'
            if invalid_reason:
                events.append(self.event(b, 'setup_invalidated', setup.identity,
                                         reason=invalid_reason,neckline=setup.neckline,bottom=setup.bottom))
                del self.active[b.symbol]
                return [], events
            v4 = p['rule_version']=='v4'
            if (v4 and setup.pullback_index is None and len(daily)>1
                    and b.close < daily[-2].close):
                setup.pullback_index = len(daily)-1
                events.append(self.event(b, 'pullback_started', setup.identity))
            retest_ready = (setup.pullback_index is not None) if v4 else setup.age >= p['retest_min_days']
            if (setup.retest_index is None and retest_ready
                    and setup.neckline*(1-p['retest_tolerance']) <= b.low <= setup.neckline*(1+p['retest_tolerance'])
                    and b.close >= setup.neckline):
                setup.retest_index = len(daily)-1
                events.append(self.event(b, 'retest_observed', setup.identity))
            idx = setup.retest_index
            if idx is not None and len(daily)-1 > idx:
                if v4:
                    idx = setup.pullback_index
                    # Count completed pullback observations, excluding the restart bar.
                    if len(daily)-1-idx < p['retest_min_days']:
                        return [], events
                earlier = daily[idx:-1]
                if (b.close > max(x.high for x in earlier)
                        and b.close > b.open*(1+p['restart_body'])):
                    stop = min(x.low for x in daily[idx:])*(1-p['stop_buffer'])
                    trigger = b.high*(1+p['trigger_buffer'])
                    target = setup.neckline + (setup.neckline-setup.bottom)
                    intent = Intent(self.name, b.symbol, b.date, trigger, stop, target,
                                    setup.identity, 'double_bottom_retest_restart')
                    del self.active[b.symbol]
                    events.append(self.event(b, 'entry_intent', setup.identity,
                                             trigger=trigger, stop=stop, target=target))
                    return [intent], events
            return [], events

        if p['direction_cycle']=='weekly':
            if p['rule_version']=='v3' and b.date not in week_ends:
                return [], events
            if self.week_ends_ref is not week_ends:
                self.week_ends_ref=week_ends
                self.end_by_week={week_key(d):d for d in week_ends}
            cache=self.weekly_caches.setdefault(b.symbol,WeeklyCache())
            bars=cache.get(history,self.end_by_week)
        else:
            bars=adjusted(history)
        if len(bars) < p['left']+p['right']+p['min_separation']+1:
            return [], events
        # v4 consumes each newly observable completed direction bar once, including
        # a suspended week-end first visible at resumption. Events stay on today's date.
        direction = bars[-1]
        if p['rule_version']=='v4':
            if self.last_direction_processed.get(b.symbol)==direction.date:
                return [], events
            self.last_direction_processed[b.symbol]=direction.date
        elif direction.date != b.date:
            return [], events
        lows = pivot_lows(bars, p['left'], p['right'])
        # v2 strictly models two adjacent confirmed troughs. Multi-bottom merging needs
        # its own explicit structural rule, not arbitrary combinations of old pivots.
        for j in lows[-1:]:
            for i in lows[-2:-1]:
                separation = j-i
                if not p['min_separation'] <= separation <= p['max_separation']:
                    continue
                a, c = bars[i], bars[j]
                neck = max(x.high for x in bars[i+1:j])
                floor = min(a.low, c.low)
                if abs(c.low/a.low-1) > p['bottom_tolerance'] or neck/floor-1 < p['min_depth']:
                    continue
                prior = bars[max(0,i-p['prior_lookback']):i]
                if not prior or max(x.high for x in prior)/a.low-1 < p['prior_decline']:
                    continue
                identity = f'{self.name}:{b.symbol}:{a.date}:{c.date}'
                if identity in self.used:
                    continue
                # A breakout inside the right-confirmation window becomes actionable only
                # when the second trough is confirmed. Never backdate that actionable event.
                level = neck*(1+p['breakout_buffer'])
                confirmed_at=j+p['right']
                if direction.close <= level or any(x.close > level for x in bars[confirmed_at:-1]):
                    continue
                if any(x.low < floor for x in bars[j+1:]):
                    continue
                if p['rule_version']=='v4' and (b.low < floor or b.close < neck*(1-p['retest_tolerance'])):
                    continue
                self.used.add(identity)
                first_breakout=next(x.date for x in bars[j+1:] if x.close>level)
                self.active[b.symbol] = Setup(identity, neck, floor, b.date,price_factor=b.factor)
                events.append(self.event(b, 'double_bottom_breakout', identity,
                                         neckline=neck, bottom=floor,
                                         first_bottom=a.date, second_bottom=c.date,
                                         second_bottom_confirmed=bars[confirmed_at].date,
                                         first_breakout_observed=first_breakout,
                                         **({'actionable_direction_bar':direction.date}
                                            if p['rule_version']=='v4' else {})))
                return [], events
        return [], events

    def trailing_stop(self, history, position):
        bars = adjusted(history)
        indices = pivot_lows(bars, self.p['trail_left'], self.p['trail_right'])
        candidates = [bars[i].low*(1-self.p['stop_buffer']) for i in indices
                      if bars[i].date > position.entry_date]
        return max([position.stop]+candidates)

    def event(self, bar, event, setup_id, **details):
        return dict(date=bar.date, symbol=bar.symbol, strategy=self.name,
                    event=event, setup_id=setup_id, **details)
