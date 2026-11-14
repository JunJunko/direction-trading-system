from datetime import date,timedelta,datetime
from .domain import Bar


def demo_data():
    """Deliberately scripted W and losing/trending tails, for pipeline validation only."""
    weekly_closes = [16,15,14,13,12,11,10,10.5,11,11.5,12,11.5,11,10.5,10.1,10.6,11.2,11.8,12.5]
    closes=[]
    prev=16.5
    for end in weekly_closes:
        closes.extend(prev+(end-prev)*(i+1)/5 for i in range(5))
        prev=end
    closes.extend([12.35,12.15,12.08,12.32,12.48,12.7,13,13.3,13.2,13.1,
                   13.5,13.9,14.3,14.7,15,15.5,15.8,15.6,15.2,14.8,14.3,13.8,12.8])
    dates=[]
    d=date(2024,1,1)
    while len(dates)<len(closes)+7:
        if d.weekday()<5:
            dates.append(d.strftime('%Y%m%d'))
        d+=timedelta(days=1)
    groups={}
    for day in dates:
        groups.setdefault(datetime.strptime(day,'%Y%m%d').isocalendar()[:2],[]).append(day)
    week_ends={max(ds) for ds in groups.values() if len(ds)==5}
    result=[]
    for symbol,offset,losing in [('DEMO.WIN',1,False),('DEMO.LOSS',.8,True)]:
        last=16.5
        for i,c in enumerate(closes):
            if losing and i>=100:
                c=11.8-(i-100)*.05
            op=(last+c)/2
            # Clean rebound candle and subsequent next-session trigger.
            if i==98:
                op=12.08
            high=max(op,c)+.04
            low=min(op,c)-.04
            result.append(Bar(symbol,dates[i],op*offset,high*offset,low*offset,c*offset,
                              100000,1,round(last*offset*1.1,2),round(last*offset*.9,2)))
            last=c
    return sorted(result,key=lambda b:(b.date,b.symbol)),dates[:len(closes)],week_ends
