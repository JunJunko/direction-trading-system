"""Read-only study of entry features and realized holding paths in two frozen accounts."""
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'runs'
OUT = RUNS / '20261110-pattern-trade-review'
COMPARISON = RUNS / '20261109-algorithm-combination-comparison'
W_SCAN = RUNS / '20261025-mainboard-qualified-w-v519-signals'
IHS_SCAN = RUNS / '20261025-mainboard-inverse-head-shoulders-v7-pressure-support'
sys.path.insert(0, str(ROOT / 'src'))
from trading_system.domain import Bar
from trading_system.volatility_entry_research import prior_atr


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def save(path, records):
    fields = list(dict.fromkeys(field for record in records for field in record))
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fields)
        writer.writeheader()
        writer.writerows(records)


def tail(identifier):
    return identifier.split(':', 1)[1]


def price(bar, field, factor):
    return getattr(bar, field) * bar.factor / factor


def history(symbols):
    result = defaultdict(list)
    with (IHS_SCAN / 'bars.csv').open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            if row['symbol'] in symbols:
                result[row['symbol']].append(Bar(row['symbol'], row['date'], **{
                    key: float(row[key]) for key in ('open', 'high', 'low', 'close', 'volume', 'factor', 'up_limit', 'down_limit')
                }))
    for stock in result.values():
        stock.sort(key=lambda bar: bar.date)
    return result


def audit(family, plan, fill, trade, stock, dates, execution, position):
    signal, entry = fill['signal_date'], fill['date']
    exit_date = trade['exit_date'] if trade else dates[-1]
    local = {bar.date: i for i, bar in enumerate(stock)}
    exchange = {date: i for i, date in enumerate(dates)}
    i, j, k = (local[date] for date in (signal, entry, exit_date))
    sigbar, first, last = stock[i], stock[j], stock[k]
    buy, stop, target, risk, quantity, fee = (
        float(fill[key]) for key in ('fill', 'stop', 'target', 'expected_loss', 'filled_quantity', 'entry_fee')
    )
    slip, commission, tax, floor = (execution[key] for key in (
        'slippage', 'commission_rate', 'sell_tax_after_20230828', 'minimum_commission'))
    factor = first.factor
    assert signal == plan['date'] and plan['symbol'] == fill['symbol']
    assert exchange[entry] == exchange[signal] + 1 and plan['entry_order'] == 'next_open'
    assert math.isclose(buy, first.open * (1 + slip), abs_tol=1e-8)
    assert math.isclose(stop, plan['stop'] * sigbar.factor / factor, abs_tol=1e-8)
    assert math.isclose(target, plan['target'] * sigbar.factor / factor, abs_tol=1e-8)
    assert float(fill['net_rr']) > 3 and float(fill['expected_upside']) > .05
    if trade:
        proceeds = float(trade['exit']) * float(trade['quantity'])
        pnl = proceeds - buy * quantity - fee - max(floor, proceeds * commission) - proceeds * tax
        assert math.isclose(pnl, float(trade['pnl']), abs_tol=1e-5)
        assert last.low * (1 - slip) - 1e-7 <= float(trade['exit']) <= last.high + 1e-7, (trade, last)
    else:
        pnl = (price(last, 'close', factor) - buy) * quantity - fee
        assert math.isclose(position['entry'] * position['quantity'], buy * quantity, abs_tol=1e-5)

    atr, known = prior_atr(stock, entry, factor)
    assert known < entry
    held = stock[j:k] if trade else stock[j:k+1]
    assert held and held[0].date == entry
    peak = max(held, key=lambda bar: price(bar, 'close', factor))
    peak_price = price(peak, 'close', factor)
    peak_proceeds = peak_price * (1 - slip) * quantity
    peak_net = peak_proceeds - buy * quantity - fee - max(floor, peak_proceeds * commission) - peak_proceeds * tax
    forward_end = exchange[entry] + 19
    complete = forward_end < len(dates)
    forward_date = dates[min(forward_end, len(dates) - 1)]
    forward = [bar for bar in stock[j:] if bar.date <= forward_date]
    forward_peak = max(forward, key=lambda bar: price(bar, 'close', factor))
    post_exit_five = bool(trade and complete and peak_price / buy < 1.05 and any(
        bar.date >= exit_date and price(bar, 'close', factor) / buy >= 1.05 for bar in forward))

    if family == 'W':
        left, right = (plan[key] for key in ('w_left_date', 'w_right_date'))
        span = local[right] - local[left]
        assert span == plan['w_separation_sessions']
        details = dict(prior_decline=plan['w_prior_decline'], middle_rebound=plan['w_rebound_fraction'],
                       bottom_difference=plan['w_bottom_difference'],
                       wait=i-local[plan['w_known_at']], structure_known=plan['w_known_at'],
                       right_to_signal=i-local[right])
    else:
        left, p1, head, p2, right = (plan[f'ihs_{key}_date'] for key in ('left','peak1','head','peak2','right'))
        legs = [local[b]-local[a] for a,b in zip((left,p1,head,p2),(p1,head,p2,right))]
        span = sum(legs)
        details = dict(prior_decline=plan['ihs_prior_decline'], outer_min=min(legs[0],legs[3]),
                       shoulder_core_ratio=min(legs[0]/legs[1], legs[3]/legs[2]),
                       four_leg_balance=min(legs)/max(legs), legs=legs,
                       wait=i-local[plan['ihs_known_at']], structure_known=plan['ihs_known_at'],
                       right_to_signal=i-local[right])
    assert details['wait'] >= 0 and span > 0
    return dict(family=family, symbol=fill['symbol'], setup_id=fill['setup_id'], signal=signal,
                entry=entry, exit=exit_date if trade else '', left=left, right=right, span=span,
                **details, closed=bool(trade), reason=trade['reason'] if trade else 'open', pnl=pnl,
                exit_below_raw_low=bool(trade and float(trade['exit']) < last.low - 1e-7),
                exit_price=float(trade['exit']) if trade else None,
                realized_R=float(trade['realized_r']) if trade else None,
                entry_price=buy, initial_stop=stop, target=target, net_rr=float(fill['net_rr']),
                upside=float(fill['expected_upside']), entry_gap=buy/price(sigbar,'close',factor)-1,
                atr=atr, stop_atr=(buy-stop)/atr, stop_pct=(buy-stop)/buy,
                neck_atr=(buy-float(fill['execution_neckline']))/atr if family=='IHS' else None,
                t0_stop=first.low<=stop, t0_close_change=first.close/buy-1,
                held_sessions=exchange[exit_date]-exchange[entry], peak_close_date=peak.date,
                peak_close_gain=peak_price/buy-1, peak_close_net_R=peak_net/risk,
                forward20_complete=complete, forward20_peak_date=forward_peak.date,
                forward20_peak_gain=price(forward_peak,'close',factor)/buy-1,
                post_exit_five=post_exit_five)


def stats(records):
    closed = [r for r in records if r['closed']]
    losses = [r for r in closed if r['pnl'] < 0]
    return dict(buys=len(records), closed=len(closed), wins=sum(r['pnl']>0 for r in closed),
                losses=len(losses), pnl=sum(r['pnl'] for r in closed),
                mean_R=mean(r['realized_R'] for r in closed) if closed else None,
                median_R=median(r['realized_R'] for r in closed) if closed else None,
                t0_stop=sum(r['t0_stop'] for r in records),
                next_session_losses=sum(r['held_sessions']==1 for r in losses),
                losses_peak_lt3=sum(r['peak_close_gain']<.03 for r in losses),
                losses_peak_ge5=sum(r['peak_close_gain']>=.05 for r in losses),
                losses_peak_ge2R=sum(r['peak_close_net_R']>=2 for r in losses),
                losses_forward20_complete=sum(r['forward20_complete'] for r in losses),
                losses_post_exit_five=sum(r['post_exit_five'] for r in losses),
                exit_reasons=dict(Counter(r['reason'] for r in closed)))


def bucket(records, key, ranges):
    return {label:stats([r for r in records if low <= r[key] < high]) for label, low, high in ranges}


def account_stats(records):
    inf = float('inf')
    groups = {}
    for family in ('W','IHS'):
        own = [r for r in records if r['family']==family]
        groups[family] = dict(total=stats(own), splits={})
        features = dict(
            net_rr=[('3–5',3,5),('5–8',5,8),('≥8',8,inf)],
            entry_gap=[('<0%',-inf,0),('0%–2%',0,.02),('≥2%',.02,inf)],
            held_sessions=[('1日后卖出',0,2),('2–5日',2,6),('6–20日',6,21),('>20日',21,inf)],
        )
        if family=='W':
            features.update(span=[('≤20',0,21),('21–60',21,61),('61–120',61,121),('>120',121,inf)],
                            wait=[('≤3',0,4),('4–7',4,8),('≥8',8,inf)],
                            stop_atr=[('<0.25',0,.25),('0.25–0.5',.25,.5),('0.5–1',.5,1),('≥1',1,inf)],
                            prior_decline=[('5%–10%',0,.1),('≥10%',.1,inf)],
                            middle_rebound=[('<5%',0,.05),('5%–10%',.05,.1),('≥10%',.1,inf)])
        else:
            features.update(span=[('≤120',0,121),('121–250',121,251),('>250',251,inf)],
                            wait=[('≤10',0,11),('11–30',11,31),('>30',31,inf)],
                            outer_min=[('≤2',0,3),('≥3',3,inf)],
                            shoulder_core_ratio=[('<10%',0,.1),('≥10%',.1,inf)],
                            neck_atr=[('<0.5',-inf,.5),('≥0.5',.5,inf)])
        groups[family]['splits'] = {key:bucket(own,key,ranges) for key,ranges in features.items()}
        groups[family]['time_halves'] = {label:stats([r for r in own if (r['entry']<'20260401')==first])
                                          for label,first in [('2025-10-09 至 2026-03-31',True),('2026-04-01 至 2026-09-30',False)]}
    return groups


def main():
    OUT.mkdir(exist_ok=True)
    dates = [d for d in load(IHS_SCAN/'calendar.json')['open_dates'] if d<='20260930']
    config = [('W','W_v7_only',W_SCAN,6014,230),('IHS','IHS_v7_only',IHS_SCAN,1713,38)]
    accounts, symbols = [], set()
    for family, name, scan, signal_count, buy_count in config:
        folder = COMPARISON/name
        plan_rows = load(scan/'plans.json')
        plans = {(tail(p['setup_id']),p['date']):p for p in plan_rows}
        fills = [a for a in rows(folder/'entry_audit.csv') if a['execution_reason']=='filled']
        trades = {(t['setup_id'],t['entry_date']):t for t in rows(folder/'trades.csv')}
        summary = load(folder/'summary.json')
        positions = {(p['setup_id'],p['entry_date']):p for p in summary['positions']}
        assert len(plans)==len(plan_rows)==signal_count and len(fills)==buy_count
        assert len(trades)+len(positions)==buy_count
        symbols.update(a['symbol'] for a in fills)
        accounts.append((family,plans,fills,trades,positions,summary,load(folder/'config.json')['execution']))
    hist=history(symbols)
    records=[]
    for family, plans, fills, trades, positions, summary, execution in accounts:
        own=[]
        for fill in fills:
            key=fill['setup_id'],fill['date']
            trade=trades.get(key)
            assert bool(trade) != (key in positions)
            record=audit(family,plans[tail(key[0]),fill['signal_date']],fill,trade,
                         hist[fill['symbol']],dates,execution,positions.get(key))
            own.append(record)
        assert math.isclose(sum(r['pnl'] for r in own),summary['final_equity']-summary['initial_cash'],abs_tol=1e-4)
        records.extend(own)
    save(OUT/'trade-features.csv',records)
    dump(OUT/'summary.json',account_stats(records))
    dump(OUT/'method.json',dict(
        sources=[str(COMPARISON/name) for _,name,*_ in config],
        evaluation='20251009–20260930, 3214-stock frozen universe, two separate standard-cost single-family accounts',
        unit='filled buy; closed-only for realized profit/R. The two accounts are not pooled.',
        span='observed stock K-line index distance. W between bottoms. IHS left to right shoulder.',
        wait='first observable W registration or confirmed IHS right shoulder through signal, in observed stock bars',
        held='exchange sessions between entry and exit. Exit-date prices excluded from holding peaks.',
        follow_up='20 exchange sessions including entry. Incomplete windows excluded. At/after exit close is follow-up only.',
        binning='Exploratory fixed descriptive groups. Historical development sample, no threshold selected from the tables.',
        checks='full plan-to-fill lineage; next-open price; adjusted stop/target; gates; exit within daily range allowing modeled slippage below the low; realized/marked PnL reconciliation'))
    print(f'AUDITED {len(records)} buys, {sum(r["closed"] for r in records)} closed, {len(symbols)} symbols')


if __name__=='__main__':
    main()
