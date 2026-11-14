"""Per-event R audit: real accounts and independently executable reference opportunities."""
import copy,csv,hashlib,html,json,math,shutil,sys,time
from collections import Counter,defaultdict
from pathlib import Path
from statistics import median
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'runs/20261025-w-ihs-v7-shared-account'
OUT=ROOT/'audits/20261025-w-ihs-v7-R-distribution'
sys.path.insert(0,str(RUN/'source/src'))
from trading_system.domain import Bar,Intent
from trading_system.engine import Backtest
from trading_system.pressure_support_trend import PressureSupportTrend
from trading_system.universe import MainboardUniverse
from trading_system.strategies import build_strategies
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def rows(p):
 with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def dump(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def save(p,rs):
 if not rs:return
 with p.open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rs for k in r)));w.writeheader();w.writerows(rs)
def near(a,b):assert math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-6),(a,b)
def family(strategy):return '双底' if strategy.startswith('double_bottom') else '头肩底'

def trade_record(scope,a,trade,bs,cost,last='20260930'):
    start=a['date'];end=trade['exit_date'] if trade else ''
    entrybar=next(b for b in bs if b.date==start);factor=entrybar.factor
    fill,q,fee,risk=(float(a[k]) for k in ('fill','filled_quantity','entry_fee','expected_loss'))
    held=[b for b in bs if start<=b.date<=last and (not end or b.date<end)]
    assert held
    def price(b,k):return getattr(b,k)*b.factor/factor
    def net(v):
        value=v*q*(1-cost['slippage'])
        return value-fill*q-fee-max(5,value*cost['commission_rate'])-value*cost['sell_tax_after_20230828']
    high=max(held,key=lambda b:price(b,'high'));close=max(held,key=lambda b:price(b,'close'));low=min(held,key=lambda b:price(b,'low'))
    pnl=float(trade['pnl']) if trade else (price(held[-1],'close')-fill)*q-fee
    high_R=net(price(high,'high'))/risk;close_R=net(price(close,'close'))/risk
    if trade:
        near(float(trade['realized_r']),pnl/risk)
        sell_value=float(trade['exit'])*float(trade['quantity'])
        sale_fee=max(5,sell_value*cost['commission_rate'])+sell_value*cost['sell_tax_after_20230828']
        near(pnl,sell_value-fill*q-fee-sale_fee)
        gross_pnl=(float(trade['exit'])-float(trade['entry']))*float(trade['quantity'])
        near(gross_pnl-fee-sale_fee,pnl)
        if pnl/risk>high_R:high_R=pnl/risk;peak_date=end
        else:peak_date=high.date
    else:sale_fee=None;gross_pnl=(price(held[-1],'close')-fill)*q;peak_date=high.date
    classification=('未平仓' if not trade else '盈利平仓' if pnl>0 else '保本平仓' if pnl==0 else
        '收盘至少1R后转亏' if close_R>=1 else '仅盘中至少1R后转亏' if high_R>=1 else
        '上涨不足1R后亏损' if high_R>0 else '未观察到净浮盈即亏损')
    return dict(scope=scope,shape=family(a['strategy']),symbol=a['symbol'],strategy=a['strategy'],setup_id=a['setup_id'],
        signal_date=a.get('signal_date',''),entry_date=start,exit_date=end,closed=bool(trade),entry_price=fill,
        initial_stop=float(a['stop']),initial_R_money=risk,quantity=q,reference_target=float(a['target']),
        entry_net_RR=float(a['net_rr']),stop_distance=(fill-float(a['stop']))/fill,
        exit_price=float(trade['exit']) if trade else None,net_pnl=pnl,net_R=pnl/risk,
        gross_price_pnl_R=gross_pnl/risk,actual_fee_R=(fee+sale_fee)/risk if sale_fee is not None else fee/risk,
        entry_fee=fee,sell_fee=sale_fee,MFE_net_R=high_R,peak_date=peak_date,peak_close_net_R=close_R,
        MAE_observed_net_R=net(price(low,'low'))/risk,first_day_close_net_R=net(price(held[0],'close'))/risk,
        entry_day_stop_touched=price(held[0],'low')<=float(a['stop']),
        held_observed_sessions=len(held),first_close_1R=next((b.date for b in held if net(price(b,'close'))>=risk),''),
        giveback_from_MFE_R=high_R-pnl/risk,exit_reason=trade['reason'] if trade else 'OPEN_MARKED',classification=classification)

def summarize(rs):
    closed=[r for r in rs if r['closed']];wins=[r for r in closed if r['net_pnl']>0];losses=[r for r in closed if r['net_pnl']<0]
    mean=lambda xs,k:sum(r[k] for r in xs)/len(xs) if xs else None
    win_R=mean(wins,'net_R');loss_R=-mean(losses,'net_R') if losses else None
    total_loss=-sum(r['net_pnl'] for r in losses);recovered=[r for r in losses if r['peak_close_net_R']>=1]
    return dict(trades=len(rs),closed=len(closed),open=len(rs)-len(closed),wins=len(wins),losses=len(losses),flat=len(closed)-len(wins)-len(losses),
        win_rate=len(wins)/len(closed) if closed else None,total_closed_R=sum(r['net_R'] for r in closed),
        mean_closed_R=mean(closed,'net_R'),median_closed_R=median(r['net_R'] for r in closed) if closed else None,
        average_win_R=win_R,average_loss_R=loss_R,realized_payoff_ratio=win_R/loss_R if win_R is not None and loss_R else None,
        break_even_winrate_at_observed_R_payoff=loss_R/(win_R+loss_R) if win_R is not None and loss_R else None,
        realized_pnl=sum(r['net_pnl'] for r in closed),open_marked_pnl=sum(r['net_pnl'] for r in rs if not r['closed']),
        profit_factor=sum(r['net_pnl'] for r in wins)/total_loss if total_loss else None,
        first_day_close_negative=sum(r['first_day_close_net_R']<0 for r in rs),
        entry_day_stop_touches=sum(r['entry_day_stop_touched'] for r in rs),
        losing_entry_day_stop_touches=sum(r['entry_day_stop_touched'] for r in losses),
        losses_before_close_1R=sum(r['peak_close_net_R']<1 for r in losses),
        losses_before_high_1R=sum(r['MFE_net_R']<1 for r in losses),
        close_1R_to_loss=len(recovered),high_1R_to_loss=sum(r['MFE_net_R']>=1 for r in losses),
        high_2R_to_loss=sum(r['MFE_net_R']>=2 for r in losses),
        losses_before_high_1R_pnl=sum(r['net_pnl'] for r in losses if r['MFE_net_R']<1),
        close_1R_to_loss_pnl=sum(r['net_pnl'] for r in recovered),
        close_1R_ever=sum(r['peak_close_net_R']>=1 for r in rs),high_1R_ever=sum(r['MFE_net_R']>=1 for r in rs),
        mean_initial_stop_distance=mean(rs,'stop_distance'),median_initial_stop_distance=median(r['stop_distance'] for r in rs) if rs else None,
        median_initial_R_money=median(r['initial_R_money'] for r in rs) if rs else None,
        mean_entry_net_RR=mean(rs,'entry_net_RR'),exit_reasons=dict(Counter(r['exit_reason'] for r in closed)),
        R_distribution={label:sum(test(r['net_R']) for r in closed) for label,test in (
          ('<-1R',lambda v:v<-1-1e-9),('-1R到0R',lambda v:-1-1e-9<=v<0),
          ('0R到1R',lambda v:0<=v<1),('1R到2R',lambda v:1<=v<2),('2R到3R',lambda v:2<=v<3),('>=3R',lambda v:v>=3))})

def main():
    OUT.mkdir(exist_ok=True);(OUT/'source').mkdir(exist_ok=True);shutil.copy2(__file__,OUT/'source'/Path(__file__).name)
    cfg=load(RUN/'candidate_combined/config.json');cost=cfg['execution'];cal=load(RUN/'calendar.json');ud=load(RUN/'universe.json')
    universe=MainboardUniverse(ud['stocks'],ud['st_by_date']);last='20260930'
    plans=load(RUN/'candidate_combined/plans.json');needed={p['symbol'] for p in plans};hist=defaultdict(list)
    protocol=dict(source_run=str(RUN),evaluation='20251009-20260930',rules_changed=False,
        actual_scope='candidate_combined real 146 entries is primary; independent W and IHS accounts reported separately',
        opportunity_scope='each frozen full-population signal screened independently with flat reference 1M account; original per-trade risk/position caps, fees, next-session fill and universe rules retained',
        opportunities_not_portfolio='events can overlap, same symbol can appear repeatedly; no combined return claimed',
        denominator='1R is entry-time expected loss at initial stop after modeled entry fee, stop slippage, exit commission and tax; never reset R when support moves',
        wins='net profitable closed trades / all closed trades; open marked results excluded',
        MFE='hypothetical net sell value at held-day highs; exit-day high/low excluded, actual exit fill included; entry-day peaks may be unsellable under T+1',
        fixed_reference_account=1000000,no_parameter_search=True,holdout_accessed=False)
    dump(OUT/'protocol.json',protocol);print(json.dumps(dict(status='loading',candidates=len(plans))),flush=True)
    with (RUN/'bars.csv').open(encoding='utf-8-sig',newline='') as f:
        for r in csv.DictReader(f):
            if r['symbol'] in needed and r['date']<=last:hist[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    indexes={};days={}
    for symbol,bs in hist.items():bs.sort(key=lambda b:b.date);indexes[symbol]={b.date:i for i,b in enumerate(bs)};days[symbol]={b.date:b for b in bs}
    scopes={'组合实盘模拟':RUN/'candidate_combined','双底独立账户':RUN/'candidate_w',
      '头肩底独立账户':ROOT/'runs/20261025-mainboard-inverse-head-shoulders-v7-pressure-support'}
    actual=[]
    for scope,folder in scopes.items():
        fills=[a for a in rows(folder/'entry_audit.csv') if a.get('execution_reason')=='filled'];trades={t['setup_id']:t for t in rows(folder/'trades.csv')}
        rs=[trade_record(scope,a,trades.get(a['setup_id']),hist[a['symbol']],cost) for a in fills]
        s=load(folder/'summary.json');near(sum(r['net_pnl'] for r in rs),s['final_equity']-s['initial_cash'])
        near(summarize(rs)['win_rate'],s['win_rate']);assert len(rs)==s['filled_buys']
        actual+=rs
    primary={r['setup_id']:r for r in actual if r['scope']=='组合实盘模拟'}
    dates=[d for d in cal['open_dates'] if d<=last];nextdate={d:dates[i+1] for i,d in enumerate(dates[:-1])};calendar_index={d:i for i,d in enumerate(dates)}
    opportunities=[];screen=[];started=time.monotonic()
    for n,p in enumerate(plans,1):
        shape=family(p['setup_id']);symbol=p['symbol'];signal=p['date'];pid=p['setup_id'];bs=hist[symbol]
        ledger=dict(shape=shape,symbol=symbol,setup_id=pid,signal_date=signal,reference_entry_date=nextdate.get(signal,''),
            in_combined_actual=pid in primary,status='',reason='',reference_RR=None,reference_R_money=None)
        if not universe.eligible(symbol,signal):ledger.update(status='NO_TRADE',reason='universe_ineligible_signal')
        elif signal not in nextdate:ledger.update(status='待区间外执行',reason='no_next_session_in_evaluation')
        else:
            evidence={k:copy.deepcopy(v) for k,v in p.items() if k not in ('date','symbol','setup_id','trigger','stop','target')}
            strategy=pid.split(':')[0];intent=Intent(strategy,symbol,signal,p['trigger'],p['stop'],p['target'],pid,'direct_w' if shape=='双底' else 'inverse_head_shoulders',evidence)
            e=Backtest(copy.deepcopy(cfg),build_strategies(cfg['strategies']));e.refresh_context(signal)
            assessment=e.assess_entry(intent,intent.trigger*(1+cost['slippage']),e.cash,e.cash,{},signal)
            if not assessment['quantity']:ledger.update(status='NO_TRADE',reason='signal_'+assessment['risk_reason'])
            else:
                d=nextdate[signal];e.histories[symbol]=bs[:indexes[symbol][signal]+1];e.marks[symbol]=e.histories[symbol][-1].close;e.pending=[intent]
                b=days[symbol].get(d);today={symbol:b} if b else {};e.adjust_factors(today,d);e.refresh_context(d);e.execute_interval(today,d,universe,e.cash)
                if symbol not in e.positions:
                    why=e.entry_audits[-1]['execution_reason'] if e.entry_audits else e.events[-1].get('reason',e.events[-1]['event'])
                    ledger.update(status='NO_TRADE',reason='execution_'+why)
                else:
                    a=e.entry_audits[-1];assert a['execution_reason']=='filled'
                    ledger.update(status='BUY_ALLOWED',reason='reference_account_executable',reference_RR=float(a['net_rr']),reference_R_money=float(a['expected_loss']))
                    manager=PressureSupportTrend(strategy,cal['open_dates'],cal['week_ends'])
                    e.histories[symbol].append(b);e.marks[symbol]=b.close
                    ex,_=manager.manage(e.histories[symbol],e.positions[symbol]);e.pending_exits.extend(ex)
                    for held_date in dates[calendar_index[d]+1:]:
                        if symbol not in e.positions:break
                        b=days[symbol].get(held_date);today={symbol:b} if b else {}
                        e.adjust_factors(today,held_date);e.execute_interval(today,held_date,universe,e.cash)
                        if b:e.histories[symbol].append(b);e.marks[symbol]=b.close
                        if symbol in e.positions and b:
                            ex,_=manager.manage(e.histories[symbol],e.positions[symbol]);e.pending_exits.extend(ex)
                    t=e.trades[0] if e.trades else None
                    r=trade_record('独立准入机会',a,t,bs,cost)
                    r['in_combined_actual']=pid in primary;r['actual_combined_net_R']=primary[pid]['net_R'] if pid in primary else None
                    near(r['net_pnl'],e.equity()-cfg['initial_cash']);opportunities.append(r)
        screen.append(ledger)
        if n%500==0 or n==len(plans):print(json.dumps(dict(status='screening_and_replaying',candidates_done=n,candidates=len(plans),qualified=len(opportunities),seconds=round(time.monotonic()-started))),flush=True)
    all_records=actual+opportunities;stats=[]
    for scope in (*scopes,'独立准入机会'):
        rs=[r for r in all_records if r['scope']==scope]
        for shape in ('双底','头肩底','合计'):
            subset=[r for r in rs if shape=='合计' or r['shape']==shape]
            if subset:stats.append(dict(scope=scope,shape=shape,**summarize(subset)))
    dump(OUT/'summary.json',stats);save(OUT/'summary.csv',[{k:(json.dumps(v,ensure_ascii=False) if isinstance(v,dict) else v) for k,v in r.items()} for r in stats])
    save(OUT/'actual-trades-R.csv',actual);save(OUT/'combined-trades-R.csv',[r for r in actual if r['scope']=='组合实盘模拟'])
    save(OUT/'qualified-opportunities-R.csv',opportunities);save(OUT/'candidate-screening.csv',screen)
    dump(OUT/'screening-summary.json',dict(total_candidates=len(plans),by_shape={shape:dict(Counter(r['reason'] for r in screen if r['shape']==shape)) for shape in ('双底','头肩底')},qualified=len(opportunities),
        actual_combined=len(primary),actual_present_in_independent_qualification=sum(r['in_combined_actual'] for r in opportunities)))
    dump(OUT/'verification.json',dict(actual_cash_pnl_reconciled=True,actual_net_R_reconciled=True,actual_winrates_reconciled=True,
        actual_combined_trades=len(primary),independent_candidates_screened=len(screen),independent_qualified=len(opportunities),
        independent_reference_cash_and_R_reconciled=True,no_same_day_future_high_low_execution=True,entry_and_exit_rules_changed=False))
    render(stats,actual,opportunities)
    print(json.dumps(dict(status='complete',summary=stats),ensure_ascii=True),flush=True)

def render(stats,actual,opportunities):
    def table(headers,data):return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+html.escape(str(v))+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in r)+'</tr>' for r in data)+'</tbody></table></div>'
    num=lambda v:'—' if v is None else f'{v:.3f}'
    pct=lambda v:'—' if v is None else f'{v:.2%}'
    body='<h1>双底与头肩底：逐笔R、准入机会与亏损路径</h1><p>2025-10-09 至 2026-09-30 · v7动态压力转支撑卖出 · 统计审计，不修改交易规则</p>'
    body+='<p><b>1R为入场时原始含成本止损风险金额。</b>最终净R＝扣费净损益÷原始1R金额；支撑上移后不重设R。理论目标对应的入场净RR不是实际最终R。胜率＝已平仓净盈利笔数÷已平仓总笔数，未平仓不计胜率。</p>'
    for scope in ('组合实盘模拟','独立准入机会','双底独立账户','头肩底独立账户'):
        body+='<h2>'+scope+'</h2>'
        if scope=='独立准入机会':body+='<p>每个候选分别放入空仓100万元参考账户，必须通过信号日审核、下一交易日实际预计成交价审核与真实模拟成交，再独立持有至v7退出。去除持仓竞争，不去除原入场距离、净RR、费用、成交及单笔风险限制。机会可重叠，不能相加当作一个账户的收益。</p>'
        body+=table(['形态','入场/已平/未平','盈利/亏损','胜率','累计已平净R','平均净R','平均盈利R','平均亏损R绝对值','实际盈亏比','按此R幅度盈亏平衡胜率'],[(s['shape'],f"{s['trades']}/{s['closed']}/{s['open']}",f"{s['wins']}/{s['losses']}",pct(s['win_rate']),num(s['total_closed_R']),num(s['mean_closed_R']),num(s['average_win_R']),num(s['average_loss_R']),num(s['realized_payoff_ratio']),pct(s['break_even_winrate_at_observed_R_payoff'])) for s in stats if s['scope']==scope])
    body+='<h2>组合实际交易：亏损发生在哪个阶段</h2>'+table(['形态','入场当日触及止损','入场当日收盘净亏','亏损中未达盘中1R','收盘1R后转亏','盘中2R后转亏','未达盘中1R的亏损额','收盘1R后转亏损失','已实现净损益','未平仓账面损益'],[(s['shape'],s['entry_day_stop_touches'],s['first_day_close_negative'],s['losses_before_high_1R'],s['close_1R_to_loss'],s['high_2R_to_loss'],f"{s['losses_before_high_1R_pnl']:,.2f}",f"{s['close_1R_to_loss_pnl']:,.2f}",f"{s['realized_pnl']:,.2f}",f"{s['open_marked_pnl']:,.2f}") for s in stats if s['scope']=='组合实盘模拟'])
    body+='<h2>组合已平仓R分布</h2>'+table(['形态','<-1R','-1R到0R','0R到1R','1R到2R','2R到3R','≥3R'],[[s['shape']]+list(s['R_distribution'].values()) for s in stats if s['scope']=='组合实盘模拟'])
    body+='<h2>逐笔完整明细</h2><p>支持按账户、形态、股票代码、日期及退出原因搜索。默认只显示组合实际成交；切换可查看所有独立审核通过的机会。下面每行均列出1R金额、计划RR、实际净R及持仓最高净R。</p><label>范围 <select id="scope"><option>组合实盘模拟</option><option>独立准入机会</option><option>双底独立账户</option><option>头肩底独立账户</option></select></label> <label>形态 <select id="shape"><option>全部</option><option>双底</option><option>头肩底</option></select></label> <label>搜索 <input id="query" placeholder="股票、日期、退出原因"></label><p id="shown"></p>'
    headers=['范围','形态','股票','信号日','买入日','卖出日','入场价','初始止损','1R金额','原始数量','入场净RR','最终净R/账面R','最高盘中净R','最高收盘净R','首日收盘净R','净损益','买入日触及止损','退出原因','路径分类']
    body+='<div class="scroll"><table id="details"><thead><tr>'+''.join('<th>'+html.escape(h)+'</th>' for h in headers)+'</tr></thead><tbody>'
    for r in sorted(actual+opportunities,key=lambda r:(r['entry_date'],r['shape'],r['symbol'],r['scope'])):
        vals=[r['scope'],r['shape'],r['symbol'],r['signal_date'],r['entry_date'],r['exit_date'] or '未平仓',num(r['entry_price']),num(r['initial_stop']),f"{r['initial_R_money']:,.2f}",r['quantity'],num(r['entry_net_RR']),num(r['net_R']),num(r['MFE_net_R']),num(r['peak_close_net_R']),num(r['first_day_close_net_R']),f"{r['net_pnl']:,.2f}",'是' if r['entry_day_stop_touched'] else '否',r['exit_reason'],r['classification']]
        body+='<tr data-scope="'+html.escape(r['scope'])+'" data-shape="'+r['shape']+'">'+''.join('<td>'+html.escape(str(v))+'</td>' for v in vals)+'</tr>'
    body+='</tbody></table></div>'
    body+='<p>持仓峰值估计扣除了买入佣金及假设卖出的滑点、佣金与税。退出日只纳入实际成交点，不使用整根日线高低点；峰值不是保证可成交的收益，买入当天受T+1限制。未平仓仅按期末市值扣入场费用，尚未扣未来卖出成本。各独立账户以及参考机会相互重叠，不可合并计算组合胜率或收益。</p>'
    body+='<p><a href="combined-trades-R.csv">组合每笔R明细</a> · <a href="qualified-opportunities-R.csv">全部独立准入机会每笔R</a> · <a href="candidate-screening.csv">全部候选审核结果</a> · <a href="actual-trades-R.csv">三个真实账户逐笔R</a> · <a href="summary.csv">汇总统计</a> · <a href="protocol.json">统计口径</a> · <a href="verification.json">核验结果</a></p>'
    js="""<script>const scope=document.getElementById('scope'),shape=document.getElementById('shape'),query=document.getElementById('query'),rs=[...document.querySelectorAll('#details tbody tr')];function filter(){let n=0;const q=query.value.trim().toLowerCase();for(const r of rs){const show=r.dataset.scope===scope.value&&(shape.value==='全部'||r.dataset.shape===shape.value)&&(!q||r.textContent.toLowerCase().includes(q));r.hidden=!show;if(show)n++}document.getElementById('shown').textContent='显示 '+n+' 笔'}scope.onchange=shape.onchange=query.oninput=filter;filter();</script>"""
    (OUT/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>双底与头肩底逐笔R审计</title><style>body{font:15px/1.7 system-ui;max-width:1600px;margin:30px auto;padding:0 20px;color:#18324a}.scroll{overflow:auto;max-height:650px}table{border-collapse:collapse;width:100%}th,td{padding:7px;border:1px solid #dce4ec;white-space:nowrap}th{background:#eef3f8;position:sticky;top:0}input,select{padding:7px}label{margin-right:14px}[hidden]{display:none!important}</style>'+body+js,encoding='utf-8')
if __name__=='__main__':main()
