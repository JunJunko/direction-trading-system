class MainboardUniverse:
    """Dated listing and historical ST eligibility; missing ST coverage fails closed."""
    def __init__(self, stocks, st_by_date):
        self.stocks = {r['ts_code']: r for r in stocks}
        self.st_by_date = {d: set(codes) for d, codes in st_by_date.items()}

    def eligible(self, symbol, date):
        r = self.stocks.get(symbol)
        return bool(r and date in self.st_by_date and r['list_date'] <= date
                    and (not r.get('delist_date') or date < r['delist_date'])
                    and symbol not in self.st_by_date[date])
