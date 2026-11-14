import csv
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from .domain import Bar


def load_csv(path):
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    bars = [Bar(r['symbol'], r['date'], **{k: float(r[k]) for k in
            ('open','high','low','close','volume','factor','up_limit','down_limit')}) for r in rows]
    validate(bars)
    return sorted(bars, key=lambda b: (b.date,b.symbol))


def validate(bars):
    seen = set()
    for b in bars:
        datetime.strptime(b.date, '%Y%m%d')
        if (b.symbol,b.date) in seen:
            raise ValueError(f'Duplicate bar: {b.symbol} {b.date}')
        seen.add((b.symbol,b.date))
        import math
        if not all(math.isfinite(x) for x in (b.open,b.high,b.low,b.close,b.volume,b.factor,b.up_limit,b.down_limit)):
            raise ValueError('Non-finite market data')
        if not (0 < b.low <= min(b.open,b.close) <= max(b.open,b.close) <= b.high and b.factor > 0 and b.volume >= 0):
            raise ValueError(f'Invalid OHLC/factor: {b.symbol} {b.date}')


def validate_intraday(bars):
    seen=set()
    sessions={}
    import math
    for b in bars:
        dt=datetime.strptime(b.date,'%Y%m%d%H%M%S')
        if dt.strftime('%H%M%S') not in ('103000','113000','140000','150000'):
            raise ValueError('Hourly bars must carry completed A-share session end timestamps')
        if (b.symbol,b.date) in seen:
            raise ValueError('Duplicate hourly bar')
        seen.add((b.symbol,b.date))
        sessions.setdefault((b.symbol,b.date[:8]),set()).add(b.date[8:])
        if not all(math.isfinite(x) for x in (b.open,b.high,b.low,b.close,b.volume,b.factor)):
            raise ValueError('Non-finite hourly data')
        if not (0<b.low<=min(b.open,b.close)<=max(b.open,b.close)<=b.high and b.volume>=0 and b.factor>0):
            raise ValueError('Invalid hourly OHLC/factor')
    if any(times!={'103000','113000','140000','150000'} for times in sessions.values()):
        raise ValueError('Each supplied hourly session must contain four completed bars')


def load_intraday_csv(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        rows=list(csv.DictReader(f))
    bars=[Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor')}) for r in rows]
    validate_intraday(bars)
    return sorted(bars,key=lambda b:(b.date,b.symbol))


class TushareSource:
    def __init__(self, cache_dir='data/raw/tushare'):
        token = os.environ.get('TUSHARE_TOKEN')
        if not token:
            raise RuntimeError('Set TUSHARE_TOKEN in the environment; never put it in config files')
        import tushare
        self.api = tushare.pro_api(token)
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)

    def query(self, endpoint, **params):
        key = endpoint + '_' + '_'.join(f'{k}-{v}' for k,v in sorted(params.items()))
        path = self.cache / (key+'.json')
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
        for attempt in range(3):
            try:
                rows = getattr(self.api, endpoint)(**params).to_dict('records')
                path.write_text(json.dumps(rows, ensure_ascii=False, allow_nan=False), encoding='utf-8')
                time.sleep(.35)
                return rows
            except Exception:
                if attempt == 2:
                    # Do not echo SDK exception strings that may contain credentials.
                    raise RuntimeError(f'Tushare endpoint {endpoint} failed; check connectivity, permissions and quota') from None
                time.sleep(attempt+1)

    def fetch(self, symbols, start, end):
        calendar_end = (datetime.strptime(end,'%Y%m%d')+timedelta(days=7)).strftime('%Y%m%d')
        calendar = self.query('trade_cal', exchange='SSE', start_date=start, end_date=calendar_end)
        if not calendar:
            raise RuntimeError('Empty trading calendar')
        open_dates = sorted(r['cal_date'] for r in calendar if int(r['is_open'])==1)
        groups = {}
        for d in open_dates:
            groups.setdefault(datetime.strptime(d,'%Y%m%d').isocalendar()[:2], []).append(d)
        week_ends = {max(ds) for ds in groups.values()}
        result = []
        # Year chunks keep each request below the documented daily result limit.
        for symbol in symbols:
            for year in range(int(start[:4]), int(end[:4])+1):
                lo, hi = max(start,f'{year}0101'), min(end,f'{year}1231')
                args = dict(ts_code=symbol,start_date=lo,end_date=hi)
                daily = self.query('daily', **args)
                if not daily:
                    continue
                factors = {r['trade_date']:r['adj_factor'] for r in self.query('adj_factor', **args)}
                limits = {r['trade_date']:r for r in self.query('stk_limit', **args)}
                for r in daily:
                    d = r['trade_date']
                    if d not in factors or d not in limits:
                        raise RuntimeError(f'Missing factor/price-limit data: {symbol} {d}; refusing approximate limits')
                    result.append(Bar(symbol,d,float(r['open']),float(r['high']),float(r['low']),
                                      float(r['close']),float(r['vol']),float(factors[d]),
                                      float(limits[d]['up_limit']),float(limits[d]['down_limit'])))
        validate(result)
        if not result:
            raise RuntimeError('No daily data fetched')
        return sorted(result,key=lambda b:(b.date,b.symbol)), [d for d in open_dates if d<=end], week_ends


def save_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text('',encoding='utf-8')
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
