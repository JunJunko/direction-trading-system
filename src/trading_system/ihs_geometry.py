"""Frozen two-anchor neckline in calendar-date coordinates."""
from datetime import datetime
from functools import lru_cache

@lru_cache(maxsize=8192)
def ordinal(date):return datetime.strptime(date,'%Y%m%d').toordinal()

def neckline_at(e,date):
 a=ordinal(e['ihs_peak1_date']);b=ordinal(e['ihs_peak2_date'])
 if b<=a:raise ValueError('Invalid neckline anchor ordering')
 return e['ihs_peak1_price']+(e['ihs_peak2_price']-e['ihs_peak1_price'])*(ordinal(date)-a)/(b-a)

def atr_before(bars,index,n=14):
 if index<n+1:return None
 return sum(max(bars[j].high-bars[j].low,abs(bars[j].high-bars[j-1].close),abs(bars[j].low-bars[j-1].close)) for j in range(index-n,index))/n
