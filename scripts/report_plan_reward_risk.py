"""Per-plan reward/risk and causal, provisional tighter-support diagnostics."""
import argparse
import csv
import hashlib
import html
import json
import math
import shutil
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from trading_system.analysis import adjusted
from trading_system.domain import Bar,Intent
from trading_system.risk import RiskManager
from trading_system.structure import swings
from trading_system.data import save_csv


def load(p):return json.loads(p.read_text(encoding='utf-8'))
def dump(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def read(p):
    with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))


def net_values(entry,stop,target,quantity,date,execution):
    slip=execution['slippage'];commission=execution['commission_rate'];minimum=execution['minimum_commission']
    tax=execution['sell_tax_after_20230828'] if date>='20230828' else execution['sell_tax_before_20230828']
    fee=lambda value,sell: max(minimum,value*commission)+(value*tax if sell else 0)
    entry_fee=fee(entry*quantity,False)
    exit_target=target*(1-slip);exit_stop=stop*(1-slip)
    reward=(exit_target-entry)*quantity-entry_fee-fee(exit_target*quantity,True)
    risk=(entry-exit_stop)*quantity+entry_fee+fee(exit_stop*quantity,True)
    return dict(expected_profit=reward,expected_loss=risk,net_rr=reward/risk)


def required_stop(entry,target,quantity,date,execution,rr=3):
    """A fee-aware geometric threshold at FIXED quantity, not a valid support."""
    if net_values(entry,entry,target,quantity,date,execution)['net_rr']<=rr:return None
    low=0.;high=entry
    for _ in range(90):
        mid=(low+high)/2
        if net_values(entry,mid,target,quantity,date,execution)['net_rr']<rr:low=mid
        else:high=mid
    return high


def closer_daily_supports(history,date,source_date,floor,entry):
    # Slice BEFORE adjusting or confirming pivots: later factors/lows cannot leak.
    known=adjusted([b for b in history if b.date<=date])
    if not known:return []
    result=[]
    for point in swings(known,1,1):
        if (point.kind!='low' or known[point.index].date<=source_date or
                not floor<point.price<entry):continue
        if any(b.low<=point.price for b in known[point.index+1:]):continue
        result.append(dict(price=point.price,source_date=known[point.index].date,
                           known_at=known[point.confirmed].date))
    return sorted(result,key=lambda p:p['price'],reverse=True)


def assessment(plan,config,fill=None):
    fill=plan['trigger']*(1+config['execution']['slippage']) if fill is None else fill
    intent=Intent(plan['strategy'],plan['symbol'],plan['date'],plan['trigger'],plan['stop'],plan['target'],plan['setup_id'],'diagnostic',{})
    r=RiskManager(config['risk']).assess(intent,fill,config['initial_cash'],config['initial_cash'],{}, {},
        config['execution']['commission_rate'],config['execution']['sell_tax_after_20230828'],slippage=config['execution']['slippage'])
    q=r['candidate_quantity'];assert q>0 and r.get('net_rr') is not None,r
    own=net_values(fill,plan['stop'],plan['target'],q,plan['date'],config['execution'])
    assert math.isclose(own['net_rr'],r['net_rr'],rel_tol=1e-11,abs_tol=1e-11)
    return dict(fill=fill,reference_quantity=q,**own)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    args=parser.parse_args();out=Path(args.output);out.mkdir()
    base=ROOT/'runs/20261022-mainboard-support-zone';original=ROOT/'runs/20261022-mainboard-daily-direction'
    cohort=ROOT/'runs/20261023-support-rebound-cohort-verified';outcomes=ROOT/'runs/20261023-68-plan-hit-rate'
    cfg=load(base/'config.json');oldcfg=load(original/'config.json');plans=load(base/'plans.json')
    key=lambda p:p['setup_id'].split(':',1)[1]
    old={key(p):p for p in load(original/'plans.json')};hits={key(p):p for p in load(outcomes/'support-plans.json')}
    assert len(plans)==len(old)==len(hits)==68
    barsfile=cohort/'bars.csv';digest=hashlib.sha256(barsfile.read_bytes()).hexdigest()
    assert digest==load(cohort/'manifest.json')['bars_sha256']
    history=defaultdict(list)
    for r in read(barsfile):history[r['symbol']].append(Bar(r['symbol'],r['date'],**{k:float(r[k]) for k in
        ('open','high','low','close','volume','factor','up_limit','down_limit')}))
    for seq in history.values():seq.sort(key=lambda b:b.date)
    rows=[]
    for p in plans:
        previous=old[key(p)];hit=hits[key(p)];a=assessment(p,cfg);b=assessment(previous,oldcfg)
        boundary=required_stop(a['fill'],p['target'],a['reference_quantity'],p['date'],cfg['execution'])
        upper=p['evidence']['support_upper']
        local=closer_daily_supports(history[p['symbol']],p['date'],p['evidence']['support_source_date'],p['stop'],a['fill'])
        best=local[0] if local else None
        row=dict(symbol=p['symbol'],signal_date=p['date'],setup_id=p['setup_id'],
            trigger=p['trigger'],estimated_entry=a['fill'],support_lower=p['stop'],support_upper=upper,target=p['target'],
            original_stop=previous['stop'],original_gross_rr=(p['target']-p['trigger'])/(p['trigger']-previous['stop']),
            original_net_rr=b['net_rr'],support_gross_rr=(p['target']-p['trigger'])/(p['trigger']-p['stop']),
            support_net_rr=a['net_rr'],reference_quantity=a['reference_quantity'],
            planned_reward_pct=(p['target']-a['fill'])/a['fill'],support_stop_pct=(a['fill']-p['stop'])/a['fill'],
            required_stop_for_net3=boundary,allowed_stop_pct_for_net3=(a['fill']-boundary)/a['fill'] if boundary is not None else None,
            required_stop_above_zone=boundary>upper if boundary is not None else None,
            zone_upper_net_rr=net_values(a['fill'],upper,p['target'],a['reference_quantity'],p['date'],cfg['execution'])['net_rr'],
            higher_daily_candidate_count=len(local),higher_daily_candidate=best['price'] if best else None,
            higher_daily_candidate_source=best['source_date'] if best else None,
            higher_daily_candidate_known_at=best['known_at'] if best else None,
            higher_daily_candidate_net_rr=net_values(a['fill'],best['price'],p['target'],a['reference_quantity'],p['date'],cfg['execution'])['net_rr'] if best else None,
            path_status=hit['status'],counterfactual_entry_date=hit['entry_date'],counterfactual_entry_price=hit['entry_price'],
            counterfactual_entry_net_rr=assessment(p,cfg,hit['entry_price'])['net_rr'] if hit['entry_price'] else None,
            target_hit_on_entry_day=hit['hit_on_entry_day'])
        if boundary is not None:
            assert math.isclose(net_values(a['fill'],boundary,p['target'],a['reference_quantity'],p['date'],cfg['execution'])['net_rr'],3,rel_tol=1e-10,abs_tol=1e-10)
        rows.append(row)
    triggered=[r for r in rows if r['counterfactual_entry_date']]
    save_csv(out/'all-68-plans.csv',rows);save_csv(out/'triggered-21-plans.csv',triggered);dump(out/'all-68-plans.json',rows)
    def distribution(items,field):
        vals=[r[field] for r in items if r[field] is not None]
        return dict(count=len(vals),min=min(vals),median=statistics.median(vals),max=max(vals),above3=sum(v>3 for v in vals))
    summary=dict(plans=68,triggered=len(triggered),original_gross=distribution(rows,'original_gross_rr'),
        original_net=distribution(rows,'original_net_rr'),support_gross=distribution(rows,'support_gross_rr'),
        support_net=distribution(rows,'support_net_rr'),triggered_entry_net=distribution(triggered,'counterfactual_entry_net_rr'),
        median_current_stop_pct=statistics.median(r['support_stop_pct'] for r in rows),
        median_allowed_stop_pct_for_net3=statistics.median(r['allowed_stop_pct_for_net3'] for r in rows if r['allowed_stop_pct_for_net3'] is not None),
        cost_floor_prevents_net3=sum(r['required_stop_for_net3'] is None for r in rows),
        net3_requires_stop_above_entire_zone=sum(r['required_stop_above_zone'] is True for r in rows),
        zone_upper_net3_count=sum(r['zone_upper_net_rr']>3 for r in rows),
        higher_daily_candidate_plans=sum(r['higher_daily_candidate_count']>0 for r in rows),
        higher_daily_candidate_net3_count=sum(r['higher_daily_candidate_net_rr'] is not None and r['higher_daily_candidate_net_rr']>3 for r in rows))
    needs=[r for r in rows if r['support_net_rr']<=3 and r['allowed_stop_pct_for_net3'] is not None]
    summary.update(plans_needing_tighter_stop=len(needs),
        median_allowed_stop_pct_among_needing_tightening=statistics.median(r['allowed_stop_pct_for_net3'] for r in needs),
        triggered_target_first_but_negative_expected_net_gain=sum(r['path_status']=='target_first' and r['counterfactual_entry_net_rr']<0 for r in triggered))
    # Planned net RR and realized R are different columns for the four actual trades.
    actual=[];audits={r['setup_id']:r for r in read(cohort/'candidate/entry_audit.csv') if r['execution_reason']=='filled'}
    for t in read(cohort/'candidate/trades.csv'):
        a=audits[t['setup_id']]
        actual.append(dict(symbol=t['symbol'],entry_date=t['entry_date'],exit_date=t['exit_date'],
            planned_net_rr=float(a['net_rr']),initial_stop_pct=float(a['support_entry_distance']),
            realized_r=float(t['realized_r']),pnl=float(t['pnl']),exit_reason=t['reason']))
    winners=[r['pnl'] for r in actual if r['pnl']>0];losers=[-r['pnl'] for r in actual if r['pnl']<0]
    summary['actual_4_average_win_to_average_loss']=statistics.mean(winners)/statistics.mean(losers) if winners and losers else None
    dump(out/'summary.json',summary);save_csv(out/'actual-4-trades.csv',actual)
    protocol=dict(population='original 68 breakout plans, matched by immutable setup suffix',
        gross='target-trigger divided by trigger-stop, before costs',
        net='entry=trigger*(1+slippage), sell levels include slippage; original fees, stamp tax and minimum commissions',
        quantities='each plan independently assessed from an empty 1,000,000 account under original risk/weight limits; ignores RR admission, 2% gate and dated eligibility',
        required_stop='fixed reference quantity and original target, solve net RR=3; strict admission needs RR>3; arithmetic threshold is NOT proven support',
        higher_support='only confirmed daily 1/1 swing lows strictly after original support candle, intact through signal close; provisional local support, not validated core ownership',
        not_a_backtest=True,price_data_sha256=digest)
    dump(out/'protocol.json',protocol);shutil.copy2(__file__,out/'source-report_plan_reward_risk.py')
    fmt=lambda v,d=2: '—' if v is None else f'{v:.{d}f}'
    names={r['ts_code']:r.get('name','') for r in load(base/'universe.json')['stocks']}
    labels={'target_first':'目标先到','stop_first':'止损先到','support_broken_before_trigger':'入场前失效',
        'not_triggered':'未触发','signal_universe_ineligible':'资格不符'}
    parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>68个计划逐项盈亏比</title>',
        '<style>body{font:15px/1.6 system-ui,"Microsoft YaHei";margin:30px;color:#23323e}h1{font-size:27px}h2{font-size:21px;margin-top:30px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap}th,td{text-align:right;padding:8px 10px;border-bottom:1px solid #dce3e7}th{background:#f1f5f8}th:first-child,td:first-child{text-align:left}thead{position:sticky;top:0}a{color:#176b87}.note{background:#edf4f7;padding:12px 16px;max-width:1100px}select,input{font:inherit;padding:7px;margin:8px}</style>',
        '<h1>68 个结构计划：逐项盈亏比与止损距离</h1>',
        f"<p class='note'>全部 68 计划的支撑下沿止损净盈亏比中位数 {summary['support_net']['median']:.2f}:1，{summary['support_net']['above3']} 个高于 3:1。21 个假设触发计划按实际触发参考价计算，中位数 {summary['triggered_entry_net']['median']:.2f}:1。这些是计划价格指标，不能当成实际交易收益。</p>",
        '<p>净盈亏比按每个计划独立、100万元空仓起算，参考仓位遵循原风险预算、10%单股上限及100股整手，含佣金、最低5元、卖出税费和双边滑点；暂不执行2%距离和最小盈亏比入场门槛。原始比值以触发价计算，不含费用。</p>',
        '<h2>收窄止损的检查结果</h2>',
        f"<p>68个中 {summary['support_net']['above3']} 个已满足净盈亏比>3；{summary['cost_floor_prevents_net3']} 个在固定参考仓位下，即使止损抬到入场价附近，目标空间仍不足以覆盖3倍含费用风险。其余 {len(needs)} 个需收窄，允许价格距离的中位数为 {summary['median_allowed_stop_pct_among_needing_tightening']:.2%}。</p>",
        f"<p>{summary['net3_requires_stop_above_entire_zone']} 个的3R数学止损线已高于整个原支撑区；按入场前已确认、原C点之后且未再次触及的日线1/1低点规则，更近支撑候选为 {summary['higher_daily_candidate_plans']} 个。把止损直接移到支撑区上沿，只能使净比>3的数量从 {summary['support_net']['above3']} 增至 {summary['zone_upper_net3_count']}，且这是几何比较，尚未回测新的扫损率。</p>",
        '<p>当前已验证的缩小初始价格风险方式，是支撑附近止跌后更早买入。进一步使用小时级回踩低点作止损，需要真实更小周期行情和独立的确认规则。本轮只做逐项诊断，没有修改策略止损或重新估计改变止损后的胜率。</p>',
        '<h2>新版实际 4 笔交易</h2><table><tr><th>股票</th><th>买入日期</th><th>入场净盈亏比</th><th>初始止损距离</th><th>实际盈亏 R</th><th>净盈亏（元）</th></tr>']
    for r in actual:
        parts.append('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in [r['symbol']+' '+names.get(r['symbol'],''),r['entry_date'],fmt(r['planned_net_rr'])+':1',f"{r['initial_stop_pct']:.2%}",fmt(r['realized_r']),fmt(r['pnl'])])+'</tr>')
    parts+=['</table><p>入场净盈亏比衡量“按目标和止损执行”的预计利润/风险；实际R = 实际净盈亏 / 初始含费用风险。二者不可混用，也不是“平均盈利金额/平均亏损金额”。</p>',
        '<h2>68 个计划明细</h2><p>下面的3R止损线是维持入场价和目标价时的数学边界，不能直接当作有效支撑。价格均为该计划当时复权基准。</p>',
        '<input id="search" placeholder="搜索股票代码或日期"><select id="filter"><option value="all">全部68个</option><option value="triggered">仅已触发21个</option><option value="net3">仅净盈亏比>3</option></select>',
        '<div class="scroll"><table id="plans"><thead><tr><th>股票</th><th>计划日期</th><th>触发价</th><th>支撑下沿</th><th>目标</th><th>原始盈亏比</th><th>原止损净比</th><th>支撑止损净比</th><th>当前止损距离</th><th>3R所需止损线</th><th>3R允许距离</th><th>日线更近低点</th><th>低点确认日期</th><th>结果</th><th>触发后净比</th></tr></thead><tbody>']
    for r in rows:
        values=[r['symbol']+' '+names.get(r['symbol'],''),r['signal_date'],fmt(r['trigger'],3),fmt(r['support_lower'],3),fmt(r['target'],3),
            fmt(r['support_gross_rr'])+':1',fmt(r['original_net_rr'])+':1',fmt(r['support_net_rr'])+':1',f"{r['support_stop_pct']:.2%}",
            fmt(r['required_stop_for_net3'],3),f"{r['allowed_stop_pct_for_net3']:.2%}" if r['allowed_stop_pct_for_net3'] is not None else '成本下无解',
            fmt(r['higher_daily_candidate'],3),r['higher_daily_candidate_known_at'] or '—',labels.get(r['path_status'],r['path_status']),fmt(r['counterfactual_entry_net_rr'])]
        parts.append(f"<tr data-triggered='{bool(r['counterfactual_entry_date'])}' data-net='{r['support_net_rr']}'>"+''.join('<td>'+html.escape(v)+'</td>' for v in values)+'</tr>')
    parts+=['</tbody></table></div>',
        '<p class="note">更近的日线低点仅是局部候选，尚未验证同级波段归属或重新回测，不能自动抬高止损。把止损放在原支撑区内部/上方会改变失效定义，原先71.43%的目标先到率不能继续沿用。原统计含6次入场当日目标触及，也不代表T+1下可兑现盈利。</p>',
        '<p><a href="all-68-plans.csv">全部68个CSV</a> · <a href="triggered-21-plans.csv">已触发21个CSV</a> · <a href="actual-4-trades.csv">实际4笔CSV</a> · <a href="summary.json">汇总</a> · <a href="protocol.json">计算口径</a></p>',
        '<script>function filter(){let q=document.querySelector("#search").value.toLowerCase(),f=document.querySelector("#filter").value;document.querySelectorAll("#plans tbody tr").forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q)||(f==="triggered"&&r.dataset.triggered!=="True")||(f==="net3"&&+r.dataset.net<=3));}document.querySelector("#search").oninput=filter;document.querySelector("#filter").onchange=filter;</script></html>']
    (out/'report.html').write_text('\n'.join(parts),encoding='utf-8')
    lines=['# 21 个已触发计划的盈亏比','',
        '以下为独立参考仓位、含费用的预计盈亏比，不是实际交易胜率或净利润。支撑止损使用v5.13下沿；触发后净比另考虑实际跳空入场价。','',
        '|股票|计划日期|预计入场净比|触发后净比|计划止损距离|价格结果|','|---|---|---:|---:|---:|---|']
    for r in triggered:
        lines.append(f"|{r['symbol']} {names.get(r['symbol'],'')}|{r['signal_date']}|{r['support_net_rr']:.2f}:1|{r['counterfactual_entry_net_rr']:.2f}:1|{r['support_stop_pct']:.2%}|{labels.get(r['path_status'],r['path_status'])}|")
    (out/'triggered-21.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(summary=summary,actual=actual),ensure_ascii=True))


if __name__=='__main__':main()
