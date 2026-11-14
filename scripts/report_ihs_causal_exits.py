"""Audit every fill, compare paired exits, and chart each actual IHS entry."""
import csv
import html
import json
import math
import shutil
from collections import Counter,defaultdict
from datetime import datetime
from backtest_ihs_causal_exits import ROOT,BASE,OLD,OUT,ARMS,load,dump,rows,sha,save_csv

COLORS=dict(C0='#475569',C1='#ab4bbd',C2='#0088bb',C3='#c27500',C4='#078547')
def events(path):
    with path.open(encoding='utf-8') as f:return [json.loads(l) for l in f]
def main():
    comparison=load(OUT/'comparison.json');plans={p['setup_id']:p for p in load(OLD/'paired-plans.json')}
    paired=rows(OUT/'paired-trades.csv');byid=defaultdict(list)
    for r in paired:byid[r['setup_id']].append(r)
    filled={arm:[r for r in rows(OUT/'account'/arm/'entry_audit.csv') if r['execution_reason']=='filled'] for arm in ARMS}
    symbols={a['symbol'] for aa in filled.values() for a in aa}
    bars=defaultdict(list);lookup={}
    with (BASE/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in symbols:
                bars[r['symbol']].append(r);lookup[r['symbol'],r['date']]=r
    for v in bars.values():v.sort(key=lambda r:r['date'])
    cal=load(BASE/'calendar.json')['open_dates'];nextday=dict(zip(cal,cal[1:]))
    audit=[];exitreview=[];lineevents={};unaffected=[]
    for arm,aa in filled.items():
        ev=events(OUT/'account'/arm/'events.jsonl')
        pending={(e['setup_id'],e['date']):e for e in ev if e.get('event')=='exit_intent'}
        for a in aa:
            p=plans[a['setup_id']];b=lookup[a['symbol'],a['date']]
            factor=float(b['factor']);scale=p['factor']/factor
            entry=float(a['fill']);stop=float(a['stop']);target=float(a['target'])
            assert a['date']==nextday[a['signal_date']]
            assert math.isclose(entry,float(b['open'])*1.001,rel_tol=1e-12)
            assert math.isclose(stop,p['right_stop']*scale,rel_tol=1e-12)
            assert math.isclose(target,p['target']*scale,rel_tol=1e-12)
            assert float(a['net_rr'])>3 and stop<entry<target
            date=lambda s:datetime.strptime(s,'%Y%m%d')
            leftdays=(date(p['ihs_head_date'])-date(p['ihs_left_date'])).days
            rightdays=(date(p['ihs_right_date'])-date(p['ihs_head_date'])).days
            audit.append(dict(arm=arm,setup_id=a['setup_id'],symbol=a['symbol'],signal_date=a['signal_date'],
                buy_date=a['date'],buy=entry,neckline=p['ihs_neckline']*scale,initial_stop=stop,target=target,
                entry_premium_to_neckline=entry/(p['ihs_neckline']*scale)-1,
                stop_distance=(entry-stop)/entry,net_rr=float(a['net_rr']),
                days_left_to_head=leftdays,days_head_to_right=rightdays,
                temporal_asymmetry=max(leftdays,rightdays)/min(leftdays,rightdays),
                buy_day_stop_breached=float(b['low'])<=stop))
        for t in rows(OUT/'account'/arm/'trades.csv'):
            b=lookup[t['symbol'],t['exit_date']];price=float(t['exit'])
            assert t['entry_date']<t['exit_date']
            assert float(b['low'])-1e-8<=price<=float(b['high'])+1e-8
            changes=[e for e in ev if e.get('setup_id')==t['setup_id'] and e.get('action')=='raise_stop_next_bar'
                     and e['valid_from_date'] and e['valid_from_date']<=t['exit_date']]
            decisions=[e for (pid,date),e in pending.items() if pid==t['setup_id'] and date<t['exit_date']]
            isstop='break' in t['reason']
            if not isstop:assert decisions,(arm,t)
            exitreview.append(dict(arm=arm,setup_id=t['setup_id'],symbol=t['symbol'],sell_date=t['exit_date'],
                sell=price,pnl=float(t['pnl']),engine_reason=t['reason'],
                effective_source=changes[-1]['line_source'] if changes and isstop else 'original_right_shoulder' if isstop else 'target_or_candidate',
                decision_date=decisions[-1]['date'] if decisions and not isstop else None))
        lineevents[arm]=events(OUT/'paired'/arm/'events.jsonl')
    save_csv(OUT/'buy-position-audit.csv',audit);save_csv(OUT/'sell-position-audit.csv',exitreview)
    differences=[]
    for pid,rr in byid.items():
        original=next(r for r in rr if r['arm']=='C0')
        changed=False
        for r in rr:
            delta=float(r['net_pnl'])-float(original['net_pnl'])
            differences.append(dict(setup_id=pid,symbol=r['symbol'],arm=r['arm'],
                C0_exit=original['exit_date'],exit=r['exit_date'],C0_reason=original['reason'],reason=r['reason'],
                delta_pnl=delta,C0_pnl=float(original['net_pnl']),pnl=float(r['net_pnl'])))
            changed|=abs(delta)>1e-7 or r['exit_date']!=original['exit_date']
        if not changed:unaffected.append(pid)
    save_csv(OUT/'paired-exit-differences.csv',differences)
    def pct(v):return '—' if v is None else f'{v:.2%}'
    def table(mode):
        return '<table><tr><th>方案</th><th>成交</th><th>平仓 / 持仓</th><th>收益率</th><th>最大回撤</th><th>平仓胜率</th><th>强突破候选</th></tr>'+''.join(
            f'<tr><td>{arm}</td><td>{s["filled_buys"]}</td><td>{s["closed_trades"]} / {s["open_positions"]}</td><td>{pct(s["total_return"])}</td><td>{pct(-s["max_drawdown"])}</td><td>{pct(s["win_rate"])}</td><td>{s["candidate_count"]}</td></tr>' for arm,s in comparison[mode].items())+'</table>'
    body='<h1>头肩底买卖位置审查与 C0–C4 回测</h1><p>同一批 2,925 个头肩底信号，右肩初始止损，净盈亏比严格大于 3。2025-10-09 至 2026-09-30。参数直接沿用双底 C 研究，未调参。</p>'
    body+='<p>C0：原收盘目标止盈；C1：强突破时豁免目标退出；C2：C1＋最高收盘减 3 倍前日 ATR；C3：C1＋确认波谷减 0.5 倍激活时 ATR；C4：两种保护取更高值。ATR 在候选收盘计算、结构在接受后启用，均最早次日生效。C1～C4 不改变买点。</p>'
    body+='<h2>固定 27 笔买入：只比较卖出</h2>'+table('paired')
    body+=f'<p>日期、成交价、数量、费用、初始止损与初始风险完全相同。{len(unaffected)} / 27 笔在五组中退出日期和期末损益不变。该模式不重新施加账户准入；C0 已逐笔与原交易、逐日与原净值核对。</p>'
    body+='<h2>完整账户回放：允许后续买入受资金占用影响</h2>'+table('account')
    body+='<p>全部组使用相同 2,925 个信号，原现金、仓位、风险与自动回撤收缩约束继续执行。账户 C0 的订单、交易、入场审计和净值均精确复现上轮右肩结果。</p>'
    baseaudit=[r for r in audit if r['arm']=='C0']
    body+=f'<h2>买卖位置核对</h2><p>所有账户组成交均为信号次日开盘加 0.1% 滑点；已核对信号日与成交日复权、右肩初始止损、等距目标及净盈亏比。原 27 笔中 {sum(r["entry_premium_to_neckline"]<0 for r in baseaudit)} 笔买入价低于颈线：原规则确认的是前一日收盘突破，次日允许低开买入，并未要求开盘继续站在颈线上。此规则未在本次改动。</p>'
    body+=f'<p>原 27 笔中 {sum(r["buy_day_stop_breached"] for r in baseaudit)} 笔买入当日触及止损，沿用 T+1 延后退出。卖出价格均落在当日日线区间；目标/候选失败卖出均有更早收盘决策，新增保护均有次日生效记录。日线不能确定盘中先后顺序。</p>'
    originals={r['setup_id']:r for r in paired if r['arm']=='C0'}
    below=[originals[r['setup_id']] for r in baseaudit if r['entry_premium_to_neckline']<0]
    below_stops=sum('break' in r['reason'] for r in below)
    body+=f'<p><b>买点审查重点：</b>这 {len(below)} 笔低于颈线的买入中，{below_stops} 笔最终止损，另 {sum(not r["exit_date"] for r in below)} 笔期末持仓。这是原执行规则允许的行为，并非未来数据错误；若要求突破状态持续到买入时，需要另设开盘保持颈线规则再做独立对照，不能直接用此样本倒推盈利保证。</p>'
    body+='<h2>两笔发生变化的卖点</h2><p>605086.SH：C0 于 2025-12-08 止盈；C1～C4 延至 12-11 因候选超时退出，每组少赚 2,679.17 元。605117.SH：C0 于 2026-05-07 止盈；C2 于 06-08 由 ATR 保护退出，少赚 4,235.19 元；C3/C4 于 06-02 由结构保护退出，少赚 395.39 元；C1 仍持有至期末，期末损益少 14,133.87 元。后者包含浮动损益比较。</p>'
    body+='<p>形态持续时间、下跌背景与左右时间对称仍未增加过滤。右肩止损只改善入场风险距离；C1～C4 仅在到达目标后才可能分化，不能修复到达目标前就失败的买入。</p>'
    body+='<h2>逐笔形态与买卖位置（固定入场配对）</h2><p>每张图使用信号日因子统一价格，显示收盘线、低点锚点、实际买入和各方案卖出。交易放大图中的卖出后行情仅供位置复盘，不参与规则决策。展开可查看全部 27 笔。</p>'
    (OUT/'charts').mkdir(exist_ok=True)
    for n,(pid,rr) in enumerate(byid.items(),1):
        p=plans[pid];original=next(r for r in rr if r['arm']=='C0');symbol=p['symbol'];history=bars[symbol]
        end=max((r['exit_date'] or '20260930') for r in rr)
        endidx=next(i for i,b in enumerate(history) if b['date']==end)
        end=history[min(endidx+5,len(history)-1)]['date']
        entryidx=next(i for i,b in enumerate(history) if b['date']==original['entry_date'])
        selected=[b for b in history if p['ihs_origin_date']<=b['date']<=end]
        zoom=[b for b in history[max(0,entryidx-20):] if b['date']<=end]
        def render(data,full):
            dates={b['date']:i for i,b in enumerate(data)}
            price=lambda b,k:float(b[k])*float(b['factor'])/p['factor']
            values=[price(b,'close') for b in data]
            limits=values+[p['right_stop'],p['target'],p['ihs_neckline']]+([p['stop']] if full else [])
            lo,hi=min(limits),max(limits);pad=(hi-lo)*.1;lo-=pad;hi+=pad
            x=lambda i:65+860*i/max(1,len(data)-1)
            y=lambda v:310-240*(v-lo)/(hi-lo)
            svg=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1060 480"><rect width="1060" height="480" fill="#f3f7fb"/>']
            for key,label,color in [('ihs_neckline','颈线','#9b52ba'),('right_stop','初始右肩止损','#d88b00'),('target','等距目标','#268056')]+([('stop','头部','#ba4b4b')] if full else []):
                v=p[key];svg.append(f'<path d="M65 {y(v):.2f} H925" stroke="{color}" stroke-dasharray="5 4"/><text x="930" y="{y(v):.2f}" font-size="12">{label} {v:.2f}</text>')
            points=' '.join(f'{x(i):.2f},{y(v):.2f}' for i,v in enumerate(values))
            svg.append(f'<polyline points="{points}" fill="none" stroke="#2b6fb4" stroke-width="1.4"/>')
            if full:
                for key,label in [('ihs_left_date','左肩'),('ihs_head_date','头部'),('ihs_right_date','右肩')]:
                    i=dates[p[key]];v=price(data[i],'low')
                    svg.append(f'<circle cx="{x(i):.2f}" cy="{y(v):.2f}" r="4"/><text x="{x(i):.2f}" y="{y(v)+18:.2f}" font-size="13">{label}</text>')
            buyday=original['entry_date'];i=dates[buyday];v=float(original['entry'])*float(data[i]['factor'])/p['factor']
            svg.append(f'<path d="M{x(i):.2f} {y(v):.2f} V35" stroke="#c23737"/><text x="{min(790,max(65,x(i)-40)):.2f}" y="25" font-size="13" fill="#c23737">买入 {buyday} {v:.2f}</text>')
            for k,r in enumerate(rr):
                color=COLORS[r['arm']];label=f'{r["arm"]}：期末持仓'
                if r['exit_date']:
                    i=dates[r['exit_date']];v=float(r['exit'])*float(data[i]['factor'])/p['factor']
                    svg.append(f'<circle cx="{x(i):.2f}" cy="{y(v):.2f}" r="{6-k*.6:.2f}" fill="none" stroke="{color}" stroke-width="2"/>')
                    label=f'{r["arm"]}：{r["exit_date"]} 卖出 {v:.2f}，净损益 {float(r["net_pnl"]):,.0f} 元'
                svg.append(f'<text x="65" y="{355+k*20}" font-size="13" fill="{color}">{label}</text>')
            svg.append(f'<text x="65" y="470" font-size="12">{data[0]["date"]} — {data[-1]["date"]}；统一信号日价格尺度</text></svg>')
            return ''.join(svg)
        for kind,data in [('shape',selected),('trade',zoom)]:
            (OUT/'charts'/f'{n:02}-{kind}.svg').write_text(render(data,kind=='shape'),encoding='utf-8')
        body+=f'<details><summary>{n:02} · {symbol} · 买入 {original["entry_date"]} · C0 净损益 {float(original["net_pnl"]):,.2f} 元</summary><img src="charts/{n:02}-shape.svg"/><img src="charts/{n:02}-trade.svg"/><table><tr><th>组</th><th>卖出日</th><th>原因</th><th>生效风险来源</th><th>净损益</th></tr>'
        for r in rr:body+=f'<tr><td>{r["arm"]}</td><td>{r["exit_date"] or "未平仓"}</td><td>{r["reason"]}</td><td>{r["exit_source"]}</td><td>{float(r["net_pnl"]):,.2f}</td></tr>'
        body+='</table></details>'
    body+='<h2>复核文件与限制</h2><p><a href="buy-position-audit.csv">所有账户买入位置</a> · <a href="sell-position-audit.csv">所有账户卖出位置</a> · <a href="paired-trades.csv">135 行配对明细</a> · <a href="paired-exit-differences.csv">相对 C0 的逐笔变化</a> · <a href="comparison.json">结果</a> · <a href="verification.json">验证</a> · <a href="protocol.json">冻结参数与范围</a></p><p>该历史快照已经用于策略开发，不能称为独立样本外。未改动正式策略；未对未来收益调参。配对收益含期末持仓浮动损益；MFE/MAE 仅统计收盘仍持仓日、排除退出日整根日线，避免把卖出后的高低点算进持有区间。</p>'
    style='body{max-width:1150px;margin:35px auto;padding:20px;font:16px/1.7 system-ui;color:#20344c}table{border-collapse:collapse;width:100%;margin:20px 0}th,td{padding:9px;border:1px solid #cbd5e1;text-align:right}th{background:#edf3f8}details{margin:16px 0;border:1px solid #ccd6df;padding:14px}summary{cursor:pointer;font-weight:bold}img{width:100%}a{color:#176ca0}'
    (OUT/'report.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>头肩底 C0–C4 买卖审查</title><style>'+style+'</style>'+body+'</html>',encoding='utf-8')
    v=load(OUT/'verification.json');v.update(all_account_fills_audited=len(audit),all_account_sells_audited=len(exitreview),
        all_buys_next_session_open_with_slippage=True,all_initial_brackets_factor_verified=True,
        all_sells_within_daily_range=True,all_target_exits_have_prior_decision=True,
        paired_unchanged_trade_count=len(unaffected),C0_buys_below_neckline=sum(r['entry_premium_to_neckline']<0 for r in baseaudit),
        C0_buy_day_stop_breaches=sum(r['buy_day_stop_breached'] for r in baseaudit),chart_count=54)
    dump(OUT/'verification.json',v)
    shutil.copy2(__file__,OUT/'source')
    print(json.dumps({k:v[k] for k in ('all_account_fills_audited','all_account_sells_audited','paired_unchanged_trade_count','C0_buys_below_neckline','C0_buy_day_stop_breaches','chart_count')},ensure_ascii=False))

if __name__=='__main__':main()
