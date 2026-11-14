"""Audit v3 held-bar excursions using actual fills and entry-factor share units."""
import csv,html,json,math,shutil
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v3-retest'
OUT=ROOT/'audits/20261025-ihs-v3-profit-paths'
def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def load(p):return json.loads(p.read_text(encoding='utf-8'))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    fills=[r for r in rows(RUN/'entry_audit.csv') if r['execution_reason']=='filled']
    trades={r['setup_id']:r for r in rows(RUN/'trades.csv')}
    config=load(RUN/'config.json');summary=load(RUN/'summary.json')
    symbols={a['symbol'] for a in fills};data=defaultdict(list)
    with (RUN/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in symbols and r['date']<= '20260930':data[r['symbol']].append(r)
    records=[];plots=[]
    for a in fills:
        symbol=a['symbol'];pid=a['setup_id'];trade=trades.get(pid)
        bars=sorted(data[symbol],key=lambda r:r['date'])
        entrybar=next(b for b in bars if b['date']==a['date']);factor=float(entrybar['factor'])
        entry=float(a['fill']);qty=float(a['filled_quantity']);fee=float(a['entry_fee']);risk=float(a['expected_loss'])
        capital=qty*entry
        held=[b for b in bars if b['date']>=a['date'] and (not trade or b['date']<trade['exit_date'])]
        assert held
        price=lambda b,key:float(b[key])*float(b['factor'])/factor
        highbar=max(held,key=lambda b:price(b,'high'));closebar=max(held,key=lambda b:price(b,'close'))
        highprice=price(highbar,'high');closeprice=price(closebar,'close')
        highgross=max(0,(highprice-entry)*qty);closegross=max(0,(closeprice-entry)*qty)
        net=lambda v:(v-entry)*qty-fee-max(5,v*qty*config['execution']['commission_rate'])-v*qty*config['execution']['sell_tax_after_20230828']
        last=next(b for b in bars if b['date']==trade['exit_date']) if trade else held[-1]
        if trade:
            terminal=float(trade['pnl'])
            proceeds=float(trade['exit'])*float(trade['quantity'])
            recomputed=proceeds-capital-fee-max(5,proceeds*config['execution']['commission_rate'])-proceeds*config['execution']['sell_tax_after_20230828']
            assert math.isclose(recomputed,terminal,abs_tol=1e-6)
        else:terminal=(price(last,'close')-entry)*qty-fee
        terminalreturn=(float(trade['exit'])*float(last['factor'])/factor/entry-1) if trade else price(last,'close')/entry-1
        record=dict(symbol=symbol,setup_id=pid,buy_date=a['date'],sell_date=trade['exit_date'] if trade else None,
            status='closed_stop' if trade else 'open',entry=entry,quantity_at_entry=qty,initial_risk=risk,
            held_close_bars=len(held),peak_high_date=highbar['date'],peak_high_gross_return=highprice/entry-1,
            peak_high_gross_profit=highgross,peak_high_gross_R=highgross/risk,
            peak_close_date=closebar['date'],peak_close_gross_return=closeprice/entry-1,
            peak_close_gross_R=closegross/risk,peak_close_estimated_net_profit=net(closeprice),
            peak_close_estimated_net_R=net(closeprice)/risk,
            target_gross_return=float(a['target'])/entry-1,
            held_high_touched_target=highprice>=float(a['target']),
            held_close_reached_target=closeprice>=float(a['target']),
            ever_close_net_positive=net(closeprice)>0,final_gross_return=terminalreturn,
            final_net_pnl=terminal,peak_high_to_terminal_net_gap=highgross-terminal,
            classification='at_least_2R_then_loss' if trade and highgross/risk>=2 else
                'at_least_1R_then_loss' if trade and highgross/risk>=1 else
                'below_1R_then_loss' if trade else 'open_unresolved')
        records.append(record)
        returns=[price(b,'close')/entry-1 for b in held]
        highs=[price(b,'high')/entry-1 for b in held];lows=[price(b,'low')/entry-1 for b in held]
        if trade:
            returns.append(terminalreturn);highs.append(terminalreturn);lows.append(terminalreturn)
        lower=min(lows+[0]);upper=max(highs+[0]);padding=max(.005,(upper-lower)*.12)
        lower-=padding;upper+=padding
        x=lambda i:60+800*i/max(1,len(returns)-1)
        y=lambda v:260-215*(v-lower)/(upper-lower)
        points=' '.join(f'{x(i):.2f},{y(v):.2f}' for i,v in enumerate(returns))
        ranges=''.join(f'<path d="M{x(i):.2f} {y(lows[i]):.2f} V{y(highs[i]):.2f}" stroke="#a9bed4"/>' for i in range(len(returns)))
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 320"><rect width="960" height="320" fill="#f2f6fa"/>{ranges}<path d="M60 {y(0):.2f} H860" stroke="#9b7575" stroke-dasharray="5 4"/><polyline points="{points}" fill="none" stroke="#2076ad" stroke-width="2"/><text x="60" y="24" font-size="15">{symbol} · 最大盘中涨幅 {highprice/entry-1:.2%} · 最大收盘涨幅 {closeprice/entry-1:.2%}</text><text x="60" y="295" font-size="13">{a["date"]} 买入 → {last["date"]} {"止损" if trade else "期末持仓"}；收盘收益率；灰线为持仓日高低范围</text></svg>'
        filename=symbol+'-'+a['date']+'.svg';(OUT/filename).write_text(svg,encoding='utf-8')
        plots.append(f'<details><summary>{symbol} · {record["classification"]}</summary><img style="width:100%" src="{filename}"/></details>')
    closed=[r for r in records if r['status']=='closed_stop'];opened=[r for r in records if r['status']=='open']
    stats=dict(total=len(records),closed=len(closed),open=len(opened),
        closed_under_1R=sum(r['peak_high_gross_R']<1 for r in closed),
        closed_at_least_1R=sum(r['peak_high_gross_R']>=1 for r in closed),
        closed_at_least_2R=sum(r['peak_high_gross_R']>=2 for r in closed),
        closed_at_least_1R_on_close=sum(r['peak_close_gross_R']>=1 for r in closed),
        closed_at_least_1R_net_on_close=sum(r['peak_close_estimated_net_R']>=1 for r in closed),
        closed_high_touched_target=sum(r['held_high_touched_target'] for r in closed),
        closed_close_reached_target=sum(r['held_close_reached_target'] for r in closed),
        closed_close_ever_net_positive=sum(r['ever_close_net_positive'] for r in closed),
        closed_max_high_below_3pct=sum(r['peak_high_gross_return']<.03 for r in closed),
        closed_net_pnl=sum(r['final_net_pnl'] for r in closed),open_marked_pnl=sum(r['final_net_pnl'] for r in opened))
    assert len(records)==14 and len(closed)==11
    assert math.isclose(sum(r['final_net_pnl'] for r in records),summary['final_equity']-summary['initial_cash'],abs_tol=1e-6)
    with (OUT/'trade-paths.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
    (OUT/'summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')
    table='<table><tr><th>股票</th><th>买入日</th><th>盘中最高涨幅</th><th>最高收盘涨幅</th><th>盘中最大浮盈 / R</th><th>最终净损益</th><th>状态</th></tr>'
    for r in sorted(records,key=lambda r:r['peak_high_gross_R'],reverse=True):
        table+=f'<tr><td>{r["symbol"]}</td><td>{r["buy_date"]}</td><td>{r["peak_high_gross_return"]:.2%}</td><td>{r["peak_close_gross_return"]:.2%}</td><td>{r["peak_high_gross_R"]:.2f}</td><td>{r["final_net_pnl"]:,.2f}</td><td>{"止损" if r["status"]=="closed_stop" else "持仓"}</td></tr>'
    body=f'<h1>v3 买入后走弱，还是利润回吐？</h1><p>14 笔交易；11 笔已平仓均亏，3 笔未平仓。</p><p>11 笔止损中，{stats["closed_at_least_1R"]} 笔曾有至少 1R 的盘中毛浮盈，其中 {stats["closed_at_least_2R"]} 笔超过 2R；其余 {stats["closed_under_1R"]} 笔不足 1R。{stats["closed_at_least_1R_on_close"]} 笔最高收盘毛浮盈也达到 1R。两种路径同时存在，不能把所有止损理解为买后持续下跌。</p>'+table+'</table>'
    body+='<p>R 为含成本的初始计划风险；百分比为相对实际买入价的复权毛涨幅。净损益包含实际费用。统计只使用收盘仍持仓的完整日线，排除退出日高低点，避免把卖出后高点算成曾经持有的利润。灰色范围仅表示已知日线高低点，不推断盘中路径。最高价不等于能按该价格卖出；本次未测试新的止盈规则。</p>'
    body+='<h2>逐笔路径</h2>'+''.join(plots)+'<p><a href="trade-paths.csv">逐笔数据</a> · <a href="summary.json">汇总</a> · <a href="../../runs/20261025-mainboard-inverse-head-shoulders-v3-retest/report.html">原回测报告</a></p>'
    css='body{max-width:1100px;margin:40px auto;padding:20px;font:16px/1.8 system-ui;color:#20364c}table{width:100%;border-collapse:collapse}td,th{padding:9px;border:1px solid #ccd5df;text-align:right}th{background:#edf4fa}details{padding:12px;margin:12px 0;border:1px solid #ccd5df}summary{cursor:pointer}'
    (OUT/'report.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>v3 交易利润路径</title><style>'+css+'</style>'+body+'</html>',encoding='utf-8')
    shutil.copy2(__file__,OUT/'source.py')
    print(json.dumps(stats,ensure_ascii=False,indent=2))
    for r in sorted(closed,key=lambda r:r['peak_high_gross_R'],reverse=True):
        print(r['symbol'],f'high={r["peak_high_gross_return"]:.2%}',f'close={r["peak_close_gross_return"]:.2%}',f'R={r["peak_high_gross_R"]:.2f}',f'pnl={r["final_net_pnl"]:.2f}')

if __name__=='__main__':main()
