from dataclasses import replace
from datetime import datetime
from math import isclose
from functools import lru_cache
from .domain import Bar


def adjusted(history: list[Bar]) -> list[Bar]:
    """Prices normalized to the latest *known* factor, never the dataset's future endpoint."""
    anchor = history[-1].factor
    return [Bar(b.symbol,b.date,b.open*b.factor/anchor,b.high*b.factor/anchor,
                b.low*b.factor/anchor,b.close*b.factor/anchor,b.volume,b.factor,b.up_limit,b.down_limit)
            for b in history]


@lru_cache(maxsize=10000)
def week_key(day):
    return datetime.strptime(day,'%Y%m%d').isocalendar()[:2]


def weekly(history: list[Bar], week_ends: set[str]) -> list[Bar]:
    if not history:
        return []
    end_by_week = {week_key(d):d for d in week_ends}
    groups: dict[tuple, list[Bar]] = {}
    for b in history:
        key = week_key(b.date)
        groups.setdefault(key, []).append(b)
    result = []
    for key, group in groups.items():
        end = end_by_week.get(key)
        if end is None or end > history[-1].date:
            continue
        result.append(replace(group[-1], date=end, open=group[0].open,
                              high=max(b.high for b in group), low=min(b.low for b in group),
                              volume=sum(b.volume for b in group)))
    return result


class WeeklyCache:
    """Incremental equivalent of weekly(adjusted(history)), with factor-change rebuilds."""
    def __init__(self):
        self.count=0
        self.anchor=None
        self.groups={}
        self.ends=None

    def get(self,history,end_by_week):
        anchor=history[-1].factor
        if anchor!=self.anchor or len(history)<self.count or self.ends is not end_by_week:
            self.count=0
            self.groups={}
            self.anchor=anchor
            self.ends=end_by_week
        for raw in history[self.count:]:
            b=Bar(raw.symbol,raw.date,raw.open*raw.factor/anchor,raw.high*raw.factor/anchor,
                  raw.low*raw.factor/anchor,raw.close*raw.factor/anchor,raw.volume,raw.factor,
                  raw.up_limit,raw.down_limit)
            key=week_key(b.date)
            group=self.groups.get(key)
            if group is None:
                self.groups[key]=b
            else:
                self.groups[key]=replace(b,open=group.open,high=max(group.high,b.high),
                                         low=min(group.low,b.low),volume=group.volume+b.volume)
        self.count=len(history)
        today=history[-1].date
        return [group if group.date==end_by_week[key] else replace(group,date=end_by_week[key]) for key,group in self.groups.items()
                if key in end_by_week and end_by_week[key]<=today]


class AdjustedCache:
    """Append-only adjusted history; rebuild whenever the known anchor changes."""
    def __init__(self):
        self.bars=[]
        self.anchor=None

    def get(self,history):
        anchor=history[-1].factor
        if anchor!=self.anchor or len(history)<len(self.bars):
            self.bars=[]
            self.anchor=anchor
        for b in history[len(self.bars):]:
            self.bars.append(Bar(b.symbol,b.date,b.open*b.factor/anchor,b.high*b.factor/anchor,
                b.low*b.factor/anchor,b.close*b.factor/anchor,b.volume,b.factor,b.up_limit,b.down_limit))
        return self.bars


def pivot_lows(bars: list[Bar], left: int, right: int) -> list[int]:
    """A flat trough is one pivot at its last bar, confirmed only after its end."""
    result, start = [], 0
    while start < len(bars):
        end = start
        while end+1 < len(bars) and isclose(bars[end+1].low,bars[start].low,rel_tol=0,abs_tol=1e-10):
            end += 1
        if start>=left and end+right<len(bars):
            neighbours = bars[start-left:start]+bars[end+1:end+right+1]
            if all(bars[start].low < b.low for b in neighbours):
                result.append(end)
        start=end+1
    return result
