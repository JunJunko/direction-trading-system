"""Fixed-horizon, exit-independent retrospective audit of all actual IHS entries."""
import csv, hashlib, html, json
from pathlib import Path
from collections import Counter
from statistics import mean, median
from types import SimpleNamespace
from PIL import Image
from audit_candidate_policy import candles, plt

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'runs/20261110-ihs-profit-protection'
OUT=ROOT/'runs/20261111-ihs-entry-point-review'
HORIZONS=(5,10,20,40,60)
def load(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def rows(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def save(p,rs):
    with p.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rs for k in r)));w.writeheader();w.writerows(rs)
def pct(x):return '—' if x is None else f'{x:+.2%}'
def window(bs,fill):
    hi=max(bs,key=lambda b:b.high);lo=min(bs,key=lambda b:b.low)
    return dict(n=len(bs),end=bs[-1].date,high_return=hi.high/fill-1,low_return=lo.low/fill-1,
                end_return=bs[-1].close/fill-1,high_date=hi.date,low_date=lo.date,
                max_close_return=max(b.close for b in bs)/fill-1)
def first_touch(bs,fill,up=.05,down=-.05):
    for i,b in enumerate(bs,1):
        u=b.high>=fill*(1+up);d=b.low<=fill*(1+down)
        if u or d:return dict(result='same_day_ambiguous' if u and d else 'up_first' if u else 'down_first',date=b.date,session=i)
    return dict(result='neither',date='',session=None)

def main():
    OUT.mkdir(exist_ok=True);(OUT/'charts').mkdir(exist_ok=True)
    case=SOURCE/'larger_cost1';summary=load(case/'summary.json')
    entries=sorted([a for a in rows(case/'entry_audit.csv') if a['execution_reason']=='filled'],key=lambda a:(a['date'],a['symbol']))
    trades={t['setup_id']:t for t in rows(case/'trades.csv')}
    oldpaths={r['setup_id']:r for r in rows(SOURCE/'trade-paths.csv') if r['case']=='larger_cost1'}
    hist={a['symbol']:[] for a in entries}
    with (SOURCE/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for b in csv.DictReader(f):
            if b['symbol'] in hist:
                hist[b['symbol']].append(SimpleNamespace(date=b['date'],**{k:float(b[k]) for k in ('open','high','low','close','factor')}))
    for h in hist.values():h.sort(key=lambda b:b.date)
    names={s['ts_code']:s['name'] for s in load(SOURCE/'universe.json')['stocks']}
    records=[];long=[];checks=[]
    for num,a in enumerate(entries,1):
        h=hist[a['symbol']];i=next(i for i,b in enumerate(h) if b.date==a['date']);factor=h[i].factor;fill=float(a['fill'])
        adjusted=[SimpleNamespace(date=b.date,**{k:getattr(b,k)*b.factor/factor for k in ('open','high','low','close')}) for b in h]
        after=adjusted[i+1:];t=trades.get(a['setup_id']);old=oldpaths[a['setup_id']]
        r=dict(number=num,symbol=a['symbol'],name=names.get(a['symbol'],''),entry=a['date'],fill=fill,initial_stop=float(a['stop']),
               stop_return=float(a['stop'])/fill-1,available_sessions=len(after),exit=t['exit_date'] if t else '',
               actual_pnl=float(old['pnl']),closed=bool(t),holding_peak_close_return=float(old['peak_close_gain']),
               holding_peak_net_profit=float(old['peak_net_profit']),holding_giveback=float(old['giveback_from_peak']),
               d0_high_return=adjusted[i].high/fill-1,d0_low_return=adjusted[i].low/fill-1,d0_close_return=adjusted[i].close/fill-1)
        if t:
            j=next(j for j,b in enumerate(h) if b.date==t['exit_date'])
            r['actual_exit_price_return']=float(t['exit'])*h[j].factor/factor/fill-1
        for n in HORIZONS:
            bs=after[:n];m=window(bs,fill) if bs else {};complete=len(bs)==n
            long.append(dict(number=num,symbol=a['symbol'],entry=a['date'],horizon=n,complete=complete,**m))
            r[f'n{n}']=len(bs)
            for k,v in m.items():r[f'd{n}_{k}']=v if complete else None
            if n==20:
                r.update({f'observed20_{k}':v for k,v in m.items()});touch=first_touch(bs,fill)
                r.update({f'first5_{k}':v for k,v in touch.items()})
                r['initial_stop_touched20']=any(b.low<=float(a['stop']) for b in bs)
                r['first1R_result']=first_touch(bs,fill,up=1-float(a['stop'])/fill,down=float(a['stop'])/fill-1)['result']
        # Independent arithmetic on unadjusted source data for all complete windows.
        for n in HORIZONS:
            if len(after)<n:continue
            raw=h[i+1:i+1+n]
            for field,expected in [('high_return',max(b.high*b.factor for b in raw)/(fill*factor)-1),('low_return',min(b.low*b.factor for b in raw)/(fill*factor)-1),('end_return',raw[-1].close*raw[-1].factor/(fill*factor)-1)]:
                assert abs(r[f'd{n}_{field}']-expected)<1e-12
            checks.append(dict(number=num,horizon=n,passed=True))
        # Fixed view: ten previous sessions, D0, and up to sixty future sessions.
        start=max(0,i-10);view=adjusted[start:i+61];entry_x=i-start
        fig,ax=plt.subplots(figsize=(12,4.8),layout='constrained');candles(ax,view)
        ax.axhline(fill,color='#2367aa',lw=1,label=f'Buy {fill:.3f}')
        ax.axhline(float(a['stop']),color='#a65353',ls=':',label=f'Initial stop {float(a["stop"]):.3f}')
        ax.scatter(entry_x,fill,marker='^',color='#2367aa',s=65,zorder=5);ax.axvline(entry_x,color='#2367aa',alpha=.4)
        if len(after)>=20:ax.axvline(entry_x+20,color='#bd851e',ls='--',label='D+20')
        if t and t['exit_date'] in [b.date for b in view]:
            x=next(j for j,b in enumerate(view) if b.date==t['exit_date'])
            ax.scatter(x,fill*(1+r['actual_exit_price_return']),marker='v',color='#8d379c',s=65,zorder=5,label='Actual sell '+t['exit_date'])
            ax.axvspan(x,len(view)-.5,color='#cccccc',alpha=.14)
        ax.set_ylabel('Price adjusted to entry-date factor');ax.legend(fontsize=8,loc='best')
        m={k:r[f'observed20_{k}'] for k in ('n','high_return','low_return','end_return')}
        ax.set_title(f'{num:02d} {a["symbol"]} | buy {a["date"]} | next {m["n"]} sessions: high {m["high_return"]:+.1%}, low {m["low_return"]:+.1%}, end {m["end_return"]:+.1%}\nActual P&L {r["actual_pnl"]:+,.0f} CNY | '+('closed' if t else 'OPEN; P&L marked at data end'),fontsize=10)
        r['chart']=f'charts/{num:02d}-{a["symbol"]}-{a["date"]}.png';fig.savefig(OUT/r['chart'],dpi=115);plt.close(fig);records.append(r)
    assert len(records)==summary['filled_buys']==27
    assert sum(r['closed'] for r in records)==summary['closed_trades']==26
    assert abs(sum(r['actual_pnl'] for r in records)-(summary['final_equity']-summary['initial_cash']))<1e-6
    aggs=[]
    for n in HORIZONS:
        rs=[r for r in records if r[f'n{n}']==n]
        aggs.append(dict(horizon=n,complete_samples=len(rs),positive_end=sum(r[f'd{n}_end_return']>0 for r in rs),
                         median_end=median(r[f'd{n}_end_return'] for r in rs),mean_end=mean(r[f'd{n}_end_return'] for r in rs),
                         median_high=median(r[f'd{n}_high_return'] for r in rs),median_low=median(r[f'd{n}_low_return'] for r in rs),
                         reach5=sum(r[f'd{n}_high_return']>=.05 for r in rs),reach10=sum(r[f'd{n}_high_return']>=.10 for r in rs),
                         fall5=sum(r[f'd{n}_low_return']<=-.05 for r in rs),fall10=sum(r[f'd{n}_low_return']<=-.10 for r in rs)))
    rs=[r for r in records if r['n20']==20]
    stats=dict(case='larger_cost1',data_end='20260930',summary=summary,windows=aggs,
               first5_20=dict(Counter(r['first5_result'] for r in rs)),first1R_20=dict(Counter(r['first1R_result'] for r in rs)),
               losing_closed=[dict(number=r['number'],symbol=r['symbol'],pnl=r['actual_pnl'],peak_close=r['holding_peak_close_return'],high20=r['d20_high_return'],low20=r['d20_low_return']) for r in records if r['closed'] and r['actual_pnl']<0])
    save(OUT/'entries.csv',records);save(OUT/'windows.csv',long);dump(OUT/'entries.json',records);dump(OUT/'statistics.json',stats)
    contacts=[]
    for i in range(0,len(records),2):
        ims=[Image.open(OUT/r['chart']).convert('RGB') for r in records[i:i+2]];canvas=Image.new('RGB',(max(im.width for im in ims),sum(im.height for im in ims)),'white');y=0
        for im in ims:canvas.paste(im,(0,y));y+=im.height;im.close()
        path=f'charts/contact-{i//2+1:02d}.png';canvas.save(OUT/path);contacts.append(path)
    dump(OUT/'contacts.json',contacts)
    inputs=['bars.csv','universe.json','trade-paths.csv','larger_cost1/summary.json','larger_cost1/entry_audit.csv','larger_cost1/trades.csv']
    manifest=dict(source=str(SOURCE),files={p:hashlib.sha256((SOURCE/p).read_bytes()).hexdigest() for p in inputs},checks=checks,
                  entry_count=27,closed_count=26,pnl_reconciled=True,notes='D0 excluded. D+1..N observed stock sessions. Incomplete windows excluded from aggregate. Raw high/low returns signed, not clamped. Exit-independent and adjusted for factor changes. Prices do not include hypothetical exit fees/slippage. Both thresholds within same OHLC bar remain ambiguous.')
    dump(OUT/'verification.json',manifest)
    # Self-contained static report; all 27 charts are linked and embedded.
    parts=['<!doctype html><html lang="zh"><meta charset="utf-8"><title>头肩底买点事后核验</title><style>body{font:15px system-ui;max-width:1250px;margin:32px auto;line-height:1.65;color:#243244}table{border-collapse:collapse;width:100%;margin:16px 0}th,td{padding:7px;border-bottom:1px solid #ddd;text-align:right}th:first-child,td:first-child{text-align:left}img{width:100%}a{color:#1469a0}.note{background:#eff4f8;padding:16px}</style><h1>27次买入：价格路径与实际收益</h1>',
           '<p>策略：头肩底、不追高开、盈利后左右各5根日K确认结构保护；标准成本。回测区间2025-10-09至2026-09-30。27次买入，26次平仓（18赢、8亏），1次未平仓。账户收益6.67%。</p>',
           '<p class="note">以实际买入成交价为基准，复权因子统一到买入日。D0单列；D+1至D+N是该股票后续有行情的交易日，不受实际卖出时间截断。最高/最低是窗口内价格相对买价的有符号涨跌幅，不是峰值到谷值的回撤，也不是可实现收益。买价已含买入滑点，假设卖出费用及滑点未扣。T+1后的高低价仍不保证可成交。数据截止2026-09-30，未使用此后的行情。不完整窗口不纳入全窗口汇总。未来路径只能用于诊断，不能直接作入场过滤条件。</p>',
           '<h2>统一持有观察窗口</h2><table><tr><th>交易日</th><th>完整样本</th><th>期末上涨数</th><th>期末中位数</th><th>期末均值</th><th>最高涨幅中位数</th><th>最低涨跌幅中位数</th><th>曾涨≥10%</th><th>曾跌≥5%</th></tr>']
    for a in aggs:parts.append('<tr>'+''.join(f'<td>{v}</td>' for v in [a['horizon'],a['complete_samples'],a['positive_end'],pct(a['median_end']),pct(a['mean_end']),pct(a['median_high']),pct(a['median_low']),a['reach10'],a['fall5']])+'</tr>')
    parts+=['</table><h2>逐笔20日观察</h2><p>最后不足20日的交易显示已有日数，不与完整20日混算；实际损益含成本，末笔为未实现损益。灰色区域是实际卖出后，仍用于独立评估买点。</p><table><tr><th>编号／股票</th><th>买入日</th><th>观察日数</th><th>最高涨跌</th><th>最低涨跌</th><th>末日涨跌</th><th>实际损益（元）</th><th>±5%先触及</th></tr>']
    labels={'up_first':'先+5%','down_first':'先−5%','same_day_ambiguous':'同日，顺序未知','neither':'均未触及'}
    for r in records:
        parts.append('<tr>'+''.join(f'<td>{v}</td>' for v in [f'<a href="#{r["number"]}">{r["number"]:02d} {r["symbol"]} {html.escape(r["name"])}</a>',r['entry'],r['observed20_n'],pct(r['observed20_high_return']),pct(r['observed20_low_return']),pct(r['observed20_end_return']),f'{r["actual_pnl"]:+,.0f}'+('（未平仓）' if not r['closed'] else ''),labels[r['first5_result']]])+'</tr>')
    parts+=['</table><p>完整20日样本的±5%先后顺序：'+html.escape(str(stats['first5_20']))+'。首日即同触±5%不推断盘中顺序；本表不采用当天高点减低点的不可成交收益。</p>',
            '<p><a href="entries.csv">全部逐笔明细CSV（含5/10/20/40/60日）</a> · <a href="windows.csv">每笔每窗口含不完整样本</a> · <a href="verification.json">来源哈希与核验</a></p>']
    for r in records:parts.append(f'<h2 id="{r["number"]}">{r["number"]:02d} {r["symbol"]} {html.escape(r["name"])} · {r["entry"]}</h2><p>初始止损相对买价 {pct(r["stop_return"])}；实际卖出 {r["exit"] or "未平仓"}；实际持有期间收盘最高涨幅 {pct(r["holding_peak_close_return"])}（平仓交易不含卖出当日的盘中或收盘行情）。</p><a href="{r["chart"]}"><img src="{r["chart"]}"></a>')
    parts.append('</html>');(OUT/'report.html').write_text('\n'.join(parts),encoding='utf-8')
    print(json.dumps({k:v for k,v in stats.items() if k!='summary'},ensure_ascii=False,indent=2))
    for r in records:print(r['number'],r['symbol'],r['name'],r['entry'],r['observed20_n'],*(pct(r['observed20_'+k]) for k in ('high_return','low_return','end_return')),round(r['actual_pnl']),r['first5_result'])

if __name__=='__main__':main()
