"""v5: causal sloped-neckline breakout entry and independent weekly trend exit."""
import math
from ..domain import Intent
from ..structure import SwingCache
from ..ihs_geometry import neckline_at,atr_before
from ..main_trend import MainTrend
from .enclosing_inverse_head_shoulders import EnclosingInverseHeadShoulders,_PriceRanges

class BreakoutTrendIHS(EnclosingInverseHeadShoulders):
    trend_manager_class = MainTrend
    def __init__(self,name,params):
        params=dict(params)
        self.rules=dict(breakout_atr=.1,stop_buffer_atr=.5,min_stop_atr=1.,max_entry_atr=1.,prior_trend_sessions=20,min_prior_decline=.05,min_head_atr=1.)
        for k in self.rules:
            if k in params:self.rules[k]=params.pop(k)
        for k,v in self.rules.items():
            if k=='prior_trend_sessions':
                if type(v) is not int or v<2:raise ValueError(k)
            elif type(v) not in (int,float) or not math.isfinite(v) or v<=0:raise ValueError(k)
        if self.rules['min_prior_decline']>=1:raise ValueError('min_prior_decline')
        if self.rules['breakout_atr']>=self.rules['max_entry_atr']:raise ValueError('breakout buffer exceeds entry allowance')
        super().__init__(name,params)
        self.calendar=None;self.weekends=None;self.managers={}

    def set_trend_calendar(self,calendar,weekends):
        self.calendar=calendar;self.weekends=weekends

    def candidate_layouts(self, bars, points, ranges):
        """Enumerate shoulders; the enclosing intervals determine head and peaks."""
        now = len(bars) - 1
        atr=atr_before(bars,now);prev_atr=atr_before(bars,now-1)
        if atr is None or prev_atr is None:return []
        lows = [p for p in points if p.kind == 'low' and p.confirmed <= now]
        low_by_index = {p.index: p for p in lows}
        highs = [p for p in points if p.kind == 'high' and p.confirmed <= now]
        high_by_index = {p.index: p for p in highs}
        layouts = []
        for r, right in enumerate(lows):
            if r < 2 or right.index >= now:
                continue
            # The right shoulder must still own the post-peak valley.
            if ranges.query('low', right.index, now + 1)[0] < right.price:
                continue
            for left in lows[:r - 1]:
                floor, head_index = ranges.query('low', left.index + 1, right.index)
                head = low_by_index.get(head_index)
                if head is None or not 0 < floor < min(left.price, right.price):
                    continue
                if head.index <= left.index + 1 or right.index <= head.index + 1:
                    continue
                peak1_price, peak1_index = ranges.query('high', left.index + 1, head.index)
                peak2_price, peak2_index = ranges.query('high', head.index + 1, right.index)
                peak1, peak2 = high_by_index.get(peak1_index), high_by_index.get(peak2_index)
                # Equal-height touches may have been compressed by SwingCache.
                # A previously confirmed occurrence of the same maximum is valid.
                if peak1 is None:
                    peak1 = next((p for p in reversed(highs) if left.index < p.index < head.index
                                  and p.price == peak1_price), None)
                if peak2 is None:
                    peak2 = next((p for p in reversed(highs) if head.index < p.index < right.index
                                  and p.price == peak2_price), None)
                # An ambiguous outside bar or unconfirmed extreme cannot own a peak.
                if peak1 is None or peak2 is None:
                    continue
                neck = max(peak1_price, peak2_price)
                if min(peak1_price, peak2_price) <= max(left.price, right.price):
                    continue
                anchors=dict(ihs_peak1_date=bars[peak1.index].date,ihs_peak2_date=bars[peak2.index].date,
                             ihs_peak1_price=peak1_price,ihs_peak2_price=peak2_price)
                neck=neckline_at(anchors,bars[-1].date)
                head_neck=neckline_at(anchors,bars[head.index].date)
                height = head_neck - floor
                if height<=0 or neck<=right.price:continue
                prominence = (min(left.price, right.price) - floor) / height
                shoulder_gap = abs(left.price - right.price) / height
                neck_gap = abs(peak1_price - peak2_price) / height
                if (prominence + 1e-12 < self.p['min_head_height'] or
                        shoulder_gap > self.p['max_shoulder_height'] + 1e-12 or
                        neck_gap > self.p['max_neckline_height'] + 1e-12):
                    continue
                origins = [p for p in highs if p.index < left.index and p.price > neck]
                if not origins:
                    continue
                origin = origins[-1]
                # Each shoulder is the valley of its enclosing side. Internal
                # higher troughs are allowed; deeper troughs cannot be skipped.
                if ranges.query('low', origin.index + 1, peak1.index)[0] < left.price:
                    continue
                if ranges.query('low', peak2.index + 1, now + 1)[0] < right.price:
                    continue
                # A flat head is one trough, but separated equal/deeper heads
                # are a different structure. Do not join two heads together.
                head_start = head.index
                while head_start > peak1.index + 1 and bars[head_start - 1].low == floor:
                    head_start -= 1
                if (head_start > peak1.index + 1 and
                        ranges.query('low', peak1.index + 1, head_start)[0] <= floor):
                    continue
                if ranges.query('low', head.index + 1, now + 1)[0] <= floor:
                    continue
                known = max(p.confirmed for p in (left, peak1, head, peak2, right))
                if known>now:continue
                if not (bars[now].close>neck+self.rules['breakout_atr']*atr and
                        bars[now-1].close<=neckline_at(anchors,bars[now-1].date)+self.rules['breakout_atr']*prev_atr):continue
                # Reject stale breakthroughs even if the shoulder was not yet confirmed.
                if any(atr_before(bars,j) is not None and bars[j].close>neckline_at(anchors,bars[j].date)+self.rules['breakout_atr']*atr_before(bars,j) for j in range(right.index+1,now)):continue
                n=self.rules['prior_trend_sessions']
                if left.index<n:continue
                prior=bars[left.index-n:left.index];closes=[x.close for x in prior]
                xm=(n-1)/2;ym=sum(closes)/n
                slope=sum((j-xm)*(v-ym) for j,v in enumerate(closes))/sum((j-xm)**2 for j in range(n))
                decline=1-left.price/max(x.high for x in prior)
                if slope>=0 or decline<self.rules['min_prior_decline']:continue
                if min(left.price,right.price)-floor<self.rules['min_head_atr']*atr:continue
                breakout=now
                layouts.append(dict(left=left, head=head, right=right, peak1=peak1, peak2=peak2,
                    origin=origin, neckline=neck, floor=floor, breakout=breakout,
                    prominence=prominence, shoulder_gap=shoulder_gap, neck_gap=neck_gap,
                    area=(right.index-left.index+1)*height,anchors=anchors,head_neck=head_neck,atr=atr,prior_slope=slope,prior_decline=decline))
        return layouts

    def on_close(self,history,week_ends):
        if not history:return [],[]
        b=history[-1]
        if self.last.get(b.symbol)==b.date:return [],[]
        self.last[b.symbol]=b.date;bars=self.normalized_history(history)
        points=self.caches.setdefault(b.symbol,SwingCache(self.p['left'],self.p['right'])).get(bars)
        ranges=self.ranges.setdefault(b.symbol,_PriceRanges()).update(bars)
        candidates=[];events=[]
        for w in self.candidate_layouts(bars,points,ranges):
            left,head,right=(w[k] for k in ('left','head','right'))
            identity=':'.join([self.name,b.symbol]+[bars[p.index].date for p in (left,head,right)])
            if identity in self.seen:continue
            target=w['neckline']+w['head_neck']-head.price
            stop=right.price-self.rules['stop_buffer_atr']*w['atr']
            e=dict(w['anchors'],entry_mode='ihs_breakout',entry_order='next_open',rebound_confirmed_at=b.date,
                breakout_reference=w['neckline'],ihs_left_date=bars[left.index].date,ihs_head_date=bars[head.index].date,
                ihs_right_date=bars[right.index].date,ihs_known_at=bars[max(p.confirmed for p in (left,head,right,w['peak1'],w['peak2']))].date,
                ihs_breakout_date=b.date,ihs_neckline=w['neckline'],ihs_head_neckline=w['head_neck'],ihs_floor=head.price,
                ihs_target=target,ihs_right_low=right.price,ihs_entry_atr=w['atr'],ihs_stop_buffer_atr=self.rules['stop_buffer_atr'],
                ihs_min_stop_atr=self.rules['min_stop_atr'],ihs_max_entry_atr=self.rules['max_entry_atr'],
                ihs_breakout_atr=self.rules['breakout_atr'],ihs_risk_version=5,ihs_prior_slope=w['prior_slope'],
                ihs_prior_decline=w['prior_decline'],target_rule='break_neck_plus_head_height',target_exit_rule='reference_only',
                execution_stop_rule='right_shoulder_below_atr',support_exit_on_touch=True,factor=b.factor)
            intent=Intent(self.name,b.symbol,b.date,b.close,stop,target,identity,'inverse_head_shoulders',e)
            candidates.append((intent,w))
        if not candidates:return [],events
        selected,selection_events=self.select_candidates(candidates,b)
        events.extend(selection_events)
        for intent in selected:
            events.append(dict(date=b.date,symbol=b.symbol,strategy=self.name,setup_id=intent.setup_id,event='entry_intent',
                decision='BUY_CANDIDATE',trigger=intent.trigger,stop=intent.stop,target=intent.target,**intent.evidence))
        return selected,events

    def select_candidates(self,candidates,bar):
        self.seen.update(intent.setup_id for intent,_ in candidates)
        intent,_=max(candidates,key=lambda v:(v[1]['area'],v[1]['right'].index,v[0].setup_id))
        return [intent],[]

    def manage_position(self,history,position):
        if self.calendar is None:raise ValueError('Weekly trend management requires exchange calendar')
        manager=self.managers.setdefault(position.setup_id,self.trend_manager_class(self.name,self.calendar,self.weekends))
        exits,events=manager.manage(history,position)
        if manager.protection is not None:position.plan['main_trend_protection_economic']=manager.protection
        for e in events:e.update(symbol=position.symbol,strategy=self.name,setup_id=position.setup_id)
        # Initial right-shoulder protection stays a separate intraday hard stop.
        return exits,events
