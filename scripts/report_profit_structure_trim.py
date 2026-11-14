"""Validate partial-exit accounting and report the frozen v10 experiment."""
import csv,json,html,shutil,hashlib
from collections import defaultdict,Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FIX=ROOT/'runs/20261026-profit-structure-trim-fixed'
SHARED=ROOT/'runs/20261026-profit-structure-trim-shared'
OUT=ROOT/'runs/20261026-profit-structure-trim-report'
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def save(p,rs):
    if not rs:return
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
def near(a,b):assert abs(a-b)<1e-6,(a,b)
def table(headers,rs):
    return '<table><thead><tr>'+''.join('<th>'+html.escape(str(v))+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in r)+'</tr>' for r in rs)+'</tbody></table>'

def main():
    OUT.mkdir(exist_ok=True)
    trades=rows(FIX/'paired-trades.csv');events=rows(FIX/'events.csv');legs=rows(FIX/'sale-legs.csv')
    grouped=defaultdict(list)
    for r in legs:grouped[r['arm'],r['cost'],r['setup_id']].append(r)
    for r in trades:
        ls=grouped[r['arm'],r['cost'],r['setup_id']]
        near(sum(float(v['pnl']) for v in ls),float(r['realized_pnl']))
        near(sum(float(v['leg_original_R']) for v in ls),float(r['realized_pnl'])/float(r['initial_R']))
        if r['closed']=='True':near(float(r['net_pnl']),float(r['realized_pnl']))
        assert sum(v['reason']=='profit_structure_trim' for v in ls)<=1
    standard=[e for e in events if e['arm']=='P1' and e['cost']=='1']
    funnel={name:len({e['setup_id'] for e in standard if e['event']==name}) for name in (
        'profit_protection_armed','profit_pullback_confirmed','profit_failed_rebound_confirmed','profit_structure_trim_signal','profit_trim_skipped_small_lot')}
    cal=load(ROOT/'runs/20261025-w-ihs-v7-shared-account/calendar.json')['open_dates']
    ix={d:i for i,d in enumerate(cal)}
    failures=[];price_paths=[]
    execution=load(ROOT/'configs/experiments/double_bottom_ihs_v10_profit_structure_trim.json')['execution']
    for r in trades:
        if r['arm']!='P1' or r['cost']!='1' or r['closed']!='True' or float(r['peak_close_net_R'])<2 or float(r['net_R'])>=0:continue
        es=[e for e in standard if e['setup_id']==r['setup_id']]
        armed=next(e for e in es if e['event']=='profit_protection_armed')
        path=[];factor0=None
        for day in cal[ix[r['entry_date']]:ix[r['exit_date']]+1]:
            raw=next(v for v in load(ROOT/f'data/raw/tushare/daily_trade_date-{day}.json') if v['ts_code']==r['symbol'])
            factor=next(v['adj_factor'] for v in load(ROOT/f'data/raw/tushare/adj_factor_trade_date-{day}.json') if v['ts_code']==r['symbol'])
            if factor0 is None:factor0=factor
            q=float(r['quantity'])*factor/factor0
            value=raw['close']*(1-execution['slippage'])*q
            tax=execution['sell_tax_before_20230828' if day<'20230828' else 'sell_tax_after_20230828']
            entry_cost=float(r['entry'])*float(r['quantity'])
            pnl=value-entry_cost-max(5,entry_cost*execution['commission_rate'])-max(5,value*execution['commission_rate'])-value*tax
            path.append(dict(symbol=r['symbol'],date=day,open=raw['open'],high=raw['high'],low=raw['low'],close=raw['close'],
                factor=factor,original_fill=float(r['entry']),initial_stop=float(r['initial_stop']),
                entry_relative_price_gain=raw['close']*factor/(float(r['entry'])*factor0)-1,
                hypothetical_close_net_pnl=pnl,hypothetical_close_net_R=pnl/float(r['initial_R']),
                close_after_position_exited=day==r['exit_date']))
        # An intraday stop exits before the day's close: do not count that close as held profit.
        peak=max(path[:-1],key=lambda v:v['hypothetical_close_net_R'])
        near(peak['hypothetical_close_net_R'],float(r['peak_close_net_R']))
        price_paths.extend(path)
        failures.append(dict(symbol=r['symbol'],entry_date=r['entry_date'],exit_date=r['exit_date'],
            sessions_entry_to_exit_inclusive=ix[r['exit_date']]-ix[r['entry_date']]+1,
            armed_date=armed['date'],armed_price_gain_ATR=armed['price_gain_ATR'],
            peak_close_net_R=float(r['peak_close_net_R']),final_net_R=float(r['net_R']),exit_reason=r['exit_reason'],
            entry_fill=float(r['entry']),initial_stop=float(r['initial_stop']),initial_risk_amount=float(r['initial_R']),
            peak_close_date=peak['date'],peak_close_price=peak['close'],peak_close_price_gain=peak['entry_relative_price_gain'],
            initial_stop_distance=(float(r['entry'])-float(r['initial_stop']))/float(r['entry']),
            pullback_confirmed=any(e['event']=='profit_pullback_confirmed' for e in es),
            failed_rebound_confirmed=any(e['event']=='profit_failed_rebound_confirmed' for e in es)))
    save(OUT/'2R-to-loss-audit.csv',failures);save(OUT/'giveback-price-paths.csv',price_paths);dump(OUT/'trigger-funnel.json',funnel)
    summaries=load(SHARED/'summaries.json');checks={}
    for arm in ('X0','P1'):
        p=SHARED/arm;s=summaries[arm];fills=[v for v in rows(p/'entry_audit.csv') if v['execution_reason']=='filled']
        assert all(float(v['net_rr'])>3 for v in fills)
        ls=rows(p/'trades.csv');groups=defaultdict(float)
        for v in ls:groups[v['setup_id']]+=float(v['pnl'])
        opened={v['setup_id'] for v in s['positions']};closed=[v for k,v in groups.items() if k not in opened]
        assert s['closed_trades']==len(closed)
        near(s['win_rate'],sum(v>0 for v in closed)/len(closed))
        curve=rows(p/'equity.csv');assert all(float(v['cash'])>=-1e-6 and int(v['positions'])<=5 for v in curve)
        checks[arm]=dict(minimum_filled_net_rr=min(float(v['net_rr']) for v in fills),
            fills=len(fills),closed_positions=len(closed),sale_legs=len(ls),trade_level_win_rate_verified=True)
    # Reproduce the already verified open-first shared-account baseline.
    a=rows(SHARED/'X0/equity.csv');b=rows(ROOT/'runs/20261026-book-stage2-shared/X0/equity.csv')
    assert len(a)==len(b)
    for x,y in zip(a,b):
        assert x['date']==y['date']
        for k in ('cash','equity','drawdown'):near(float(x[k]),float(y[k]))
    # Honest status: implementation complete; no empirical benefit established.
    fixed=load(FIX/'summary.json')
    body='<h1>v10：盈利状态＋结构转弱＋一次减仓</h1><p><b>实现及验证完成，但本样本没有触发减仓，未改善收益，也没有解决已观察到的2R回吐。</b>默认策略未切换。</p>'
    body+='<h2>已实现的规则</h2><ol><li>按实际成本参数估算收盘清算净利润，达到原始含成本风险的2倍后启动保护；盘中最高价不能启动。</li><li>启动后记录可观察高点H1，等待左右各2根日K确认回调低点L，再确认未超过H1的反弹高点H2；在H2确认之后的收盘跌破L，触发减仓。</li><li>每个持仓只申请一次1/3减仓，按100股向下取整；不足100股则跳过，不能变成全卖。剩余仓位继续v7管理。创新高或交易日缺失重置局部结构。</li><li>核心退出优先，能够替换尚未成交的减仓单。仍按下一可执行开盘、T+1、停牌和开盘跌停约束处理。</li></ol>'
    body+='<p>2R、1/3仓位和左右各2根K的确认均为冻结实验规则；ATR涨幅仅记录，不按本次结果另加过滤或调阈值。进入保护不等于保证保本，快速下跌可能没有完整反弹结构。</p>'
    body+='<h2>共享账户结果</h2>'+table(['规则','买入','完整平仓','卖出成交笔数','总收益（含持仓）','最大回撤'],[
        [arm,s['filled_buys'],s['closed_trades'],s['sell_fills'],f"{s['total_return']:.2%}",f"{-s['max_drawdown']:.2%}"] for arm,s in summaries.items()])
    body+='<p>X0是开盘优先v7基线，P1是新候选。两组同为7727个历史信号，资金重新计算。所有实际买入净收益风险比严格大于3，最小约3.00326；没有放宽1∶3要求。</p>'
    body+='<h2>固定146笔入场、成本压力测试</h2>'+table(['成本倍率','规则','净损益','最大回撤','实际减仓次数'],[
        [r['cost'],r['arm'],f"{r['net_pnl']:,.2f}",f"{r['max_drawdown']:.2%}",r['partial_fills']] for r in fixed])
    body+='<p>固定入场的E0等于开盘优先v7；三个成本倍率逐笔复现上阶段X0。佣金率及卖出滑点按1/1.5/2倍压力测试，买入成交价固定。固定入场和重新分配资金的共享账户口径不能混用。</p>'
    body+='<h2>为什么没有减仓</h2>'+table(['状态','不同持仓数量'],list(funnel.items()))
    body+='<p>只有已确认的完整结构才触发；“曾盈利”不是卖出信号。本样本中，回吐到亏损的4笔都没有被这套识别规则确认出完整失败反弹链。因此结果证明该版本覆盖不足，不能证明所有部分减仓都无效。</p>'
    body+=table(['股票','买入','退出','含首尾交易日','最高收盘净R','最终净R','回调确认','失败反弹确认'],[
        [r['symbol'],r['entry_date'],r['exit_date'],r['sessions_entry_to_exit_inclusive'],f"{r['peak_close_net_R']:.2f}",f"{r['final_net_R']:.2f}",r['pullback_confirmed'],r['failed_rebound_confirmed']] for r in failures])
    body+='<h2>价格核对：R倍数不等于股价涨幅</h2><p>以下用原始Tushare日线与复权因子缓存独立重算最高收盘净R，均与交易审计一致。买入价是次日开盘加模型滑点，并非买入日收盘。价格涨幅以实际模拟买入价为基准；R分母是初始止损风险金额。退出日止损后的收盘价不计入持仓浮盈。</p>'
    body+=table(['股票','模拟买入价','初始止损','止损距离','最高收盘日','原始收盘价','相对买价涨幅','净R'],[
        [r['symbol'],f"{r['entry_fill']:.5f}",f"{r['initial_stop']:.4f}",f"{r['initial_stop_distance']:.2%}",r['peak_close_date'],f"{r['peak_close_price']:.4f}",f"{r['peak_close_price_gain']:.2%}",f"{r['peak_close_net_R']:.2f}"] for r in failures])
    body+='<p>002234.SZ：2026-01-26开盘9.12元，模拟买入9.12912元；当日收盘9.39元，2026-01-30收盘9.48元。从模拟买价计算涨3.84%，但从买入日收盘9.39元计算只涨0.96%。原始止损9.08元，止损距离仅0.54%，因而不大的股价上涨也会显示为较大的R倍数。该持仓期复权因子恒为2.18。这个案例应描述为“小幅上涨相对很窄的初始风险形成高R后回吐”，不能描述为大幅趋势上涨。</p>'
    body+='<h2>账务与测试</h2><p>减仓分摊入场费用与剩余风险预算；完整交易R始终以原始总风险为分母。trades.csv记录卖出分笔，summary.closed_trades和胜率按完整持仓合并计算；部分卖出但仍持有的仓位不算一笔已平仓盈利。新增sell_fills字段保留卖出成交数。421项测试通过，包含2R净值门槛、结构时序、复权、整手取整、分批账务和完整退出覆盖阻塞减仓。</p>'
    body+='<h2>范围与后续研究</h2><p>本轮保留原W的2%入场限制，采用2025-10-09至2026-09-30的已知开发数据；不是取消限制后的重新扫描或样本外验证。日线成交与合成复权仍是近似。没有为了产生交易而在看过结果后放宽本版条件。下一项独立假设应针对“没有二次反弹、直接回落”的路径，不能把它与本轮完整反弹失败规则混为一谈。</p>'
    body+='<h2>复现文件</h2><ul><li>配置：configs/experiments/double_bottom_ihs_v10_profit_structure_trim.json</li><li>固定规则：configs/experiments/v10_profit_structure_trim_protocol.json</li><li>算法：src/trading_system/profit_structure_trim.py</li><li>策略适配：src/trading_system/strategies/profit_structure_trim.py</li><li>脚本：scripts/study_profit_structure_trim.py、scripts/backtest_profit_structure_trim_shared.py</li></ul>'
    body+='<p><a href="2R-to-loss-audit.csv">4笔回吐交易</a> · <a href="giveback-price-paths.csv">原始逐日价格及净R重算</a> · <a href="trigger-funnel.json">触发统计</a> · <a href="verification.json">核验</a> · <a href="tests.log">测试日志</a></p>'
    (OUT/'report.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>v10分批盈利保护验证</title><style>body{font:16px/1.7 system-ui;max-width:1100px;margin:32px auto;padding:0 24px}table{border-collapse:collapse;margin:20px 0;width:100%}td,th{border:1px solid #d1d5db;padding:8px;text-align:left}th{background:#edf2f7}h1{font-size:28px}h2{font-size:21px;margin-top:30px}</style>'+body+'</html>',encoding='utf-8')
    shutil.copy2(ROOT/'runs/profit-structure-trim-tests.log',OUT/'tests.log')
    shutil.copy2(ROOT/'configs/experiments/v10_profit_structure_trim_protocol.json',OUT/'protocol.json')
    shutil.copy2(ROOT/'tests/test_profit_structure_trim.py',OUT/'test_profit_structure_trim.py')
    dump(OUT/'verification.json',dict(shared_checks=checks,baseline_cash_equity_exact=True,
        fixed_partial_leg_accounting_checked=True,one_trim_max_per_position=True,
        known_development_sample=True,no_default_strategy_change=True,no_empirical_improvement=True))
    paths=[ROOT/'src/trading_system/engine.py',ROOT/'src/trading_system/profit_structure_trim.py',ROOT/'configs/experiments/v10_profit_structure_trim_protocol.json']
    dump(OUT/'source-hashes.json',{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    print(json.dumps(dict(funnel=funnel,failures=failures,checks=checks),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
