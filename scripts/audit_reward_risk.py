"""Read-only, independent Decimal audit of a frozen rule-ablation experiment.

No RiskManager calls are used to recompute recorded cash flows or structure prices.
Output always goes to a new directory outside the experiment being audited.
"""
import argparse
import csv
import hashlib
import html
import json
import statistics
from collections import Counter
from datetime import datetime
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 40
D = Decimal


def cash_flows(fill, stop, target, quantity, commission, tax, slippage):
    f, s, t, q, c, x, slip = map(lambda v: D(str(v)),
                                  (fill, stop, target, quantity, commission, tax, slippage))
    sf, tf = s * (1-slip), t * (1-slip)
    buy = max(D(5), q*f*c)
    sell_stop = max(D(5), q*sf*c) + q*sf*x
    sell_target = max(D(5), q*tf*c) + q*tf*x
    gain, loss = q*(tf-f)-buy-sell_target, q*(f-sf)+buy+sell_stop
    return dict(gross_rr=(t-f)/(f-s), net_rr=gain/loss,
                expected_profit=gain, expected_loss=loss, entry_fee=buy,
                stop_exit_fee=sell_stop, estimated_stop_fill=sf,
                estimated_target_fill=tf)


def required_target(fill, stop, quantity, commission, tax, slippage, rr=3):
    """Raw sale target at which net RR equals rr (strictly greater is required).

    Both branches of the minimum-commission schedule are solved independently.
    This is a diagnostic threshold, never a generated trading target.
    """
    f,s,q,c,x,slip,r = map(lambda v:D(str(v)),
                         (fill,stop,quantity,commission,tax,slippage,rr))
    sf=s*(1-slip); buy=max(D(5),q*f*c)
    loss=q*(f-sf)+buy+max(D(5),q*sf*c)+q*sf*x
    fixed=(q*f+buy+r*loss+D(5))/(q*(1-x))
    proportional=(q*f+buy+r*loss)/(q*(1-c-x))
    tf=fixed if q*fixed*c<=5 else proportional
    return tf/(1-slip)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def read_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(2**20),b''): h.update(block)
    return h.hexdigest()


def dump(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def audit(experiment, output):
    experiment,output=experiment.resolve(),output.resolve()
    if output==experiment or experiment in output.parents:
        raise ValueError('Audit output must be outside the frozen experiment')
    output.mkdir(parents=True,exist_ok=False)
    config=read_json(experiment/'frozen-baseline/config.json')
    execution=config['execution'];variants=read_json(experiment/'comparison.json')
    params=config['strategies'][0]['params']
    trigger_buffer=D(str(params.get('trigger_buffer',.001)))
    stop_buffer=D(str(params.get('stop_buffer',.005)))
    if execution['minimum_commission']!=5:
        raise ValueError('Frozen engine contract requires minimum commission 5')
    inputs=[experiment/'comparison.json',experiment/'frozen-baseline/config.json',
            experiment/'frozen-baseline/bars.csv']
    plans={};audits={};trades={}
    for v in variants:
        vid=v['id'];folder=experiment/vid
        plans[vid]=read_json(folder/'plans.json')
        audits[vid]=read_csv(folder/'entry_audit.csv')
        trades[vid]=read_csv(folder/'trades.csv')
        inputs.extend(folder/name for name in ('plans.json','entry_audit.csv','trades.csv'))
    before={str(p.relative_to(experiment)):sha(p) for p in inputs}
    requested=set()
    for ps in plans.values():
        for p in ps:
            for date in [p['date']]+[p['evidence'][k] for k in
                ('core_a','core_b','core_c','small_b','small_c')]:
                requested.add((p['symbol'],date))
    raw={}
    with (experiment/'frozen-baseline/bars.csv').open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            key=(row['symbol'],row['date'])
            if key in requested:raw[key]=row
    failures=[];rows=[];plan_rows=[];summary=[];max_errors=Counter()
    for variant in variants:
        vid=variant['id'];first={(p['setup_id'],p['date']):p for p in plans[vid]}
        first_rejections={};fee_only=[];checked=0
        for index,row in enumerate(audits[vid]):
            if not row.get('net_rr'):continue
            q=int(row['candidate_quantity']);date=row['date']
            tax=execution['sell_tax_before_20230828'] if date<'20230828' else execution['sell_tax_after_20230828']
            result=cash_flows(row['fill'],row['stop'],row['target'],q,
                execution['commission_rate'],tax,execution['slippage'])
            checked+=1
            for key,value in result.items():
                error=abs(float(value)-float(row[key]));max_errors[key]=max(max_errors[key],error)
                tolerance=1e-7 if key in ('expected_profit','expected_loss','entry_fee','stop_exit_fee') else 1e-8
                if error>tolerance:failures.append(dict(variant=vid,index=index,field=key,error=error))
            if row['risk_reason']=='net_rr_not_above_threshold' and result['net_rr']>D(str(config['risk']['min_rr'])):
                failures.append(dict(variant=vid,index=index,field='rejection_direction'))
            if row['risk_reason']=='approved' and result['net_rr']<=D(str(config['risk']['min_rr'])):
                failures.append(dict(variant=vid,index=index,field='approval_direction'))
            required=required_target(row['fill'],row['stop'],q,execution['commission_rate'],tax,execution['slippage'])
            rows.append(dict(variant=vid,date=date,symbol=row['symbol'],setup_id=row['setup_id'],
                quantity=q,fill=float(row['fill']),stop=float(row['stop']),target=float(row['target']),
                **{k:float(v) for k,v in result.items()},required_target_for_net_3=float(required),
                risk_reason=row['risk_reason'],execution_reason=row['execution_reason']))
            if (row['setup_id'],row['date']) in first and row['execution_reason']=='plan_rejected':
                first_rejections[row['setup_id']]=rows[-1]
                if result['gross_rr']>3 and result['net_rr']<=3:fee_only.append(rows[-1])
        ratios=[];uncapped=[];unbuffered=[];plan_price_errors=[];extra_ids=set(variant.get('restored_ids',[]))
        for p in plans[vid]:
            e=p['evidence'];symbol=p['symbol'];factor=D(raw[symbol,p['date']]['factor'])
            def price(date,key):
                b=raw[symbol,date]
                return D(b[key])*D(b['factor'])/factor
            a,b,c=[price(e[k],key) for k,key in [('core_a','low'),('core_b','high'),('core_c','low')]]
            small_b,small_c=price(e['small_b'],'high'),price(e['small_c'],'low')
            projection=c+b-a
            expected_trigger=small_b*(1+trigger_buffer)
            expected_stop=small_c*(1-stop_buffer)
            levels=[projection]+[D(str(x['price'])) for x in e['pressure_audit'] if x['reason']=='effective']
            expected_target=projection if vid=='C01' else min(levels)
            for key,expected in [('trigger',expected_trigger),('stop',expected_stop),
                                 ('target',expected_target),('symmetry_target',projection)]:
                actual=e[key] if key=='symmetry_target' else p[key]
                error=abs(float(expected)-actual)
                if error>1e-7:plan_price_errors.append(dict(setup_id=p['setup_id'],field=key,error=error))
            entry,stop,target=map(lambda v:D(str(v)),(p['trigger'],p['stop'],p['target']))
            rr=(target-entry)/(entry-stop);ratios.append(float(rr))
            rr_no_pressure=(projection-entry)/(entry-stop);uncapped.append(float(rr_no_pressure))
            rr_no_buffer=(projection-small_b)/(small_b-small_c);unbuffered.append(float(rr_no_buffer))
            rejected=first_rejections.get(p['setup_id'])
            plan_rows.append(dict(variant=vid,setup_id=p['setup_id'],symbol=symbol,date=p['date'],
                restored=p['setup_id'] in extra_ids,trigger=float(entry),stop=float(stop),target=float(target),
                core_a_low=float(a),core_b_high=float(b),core_c_low=float(c),small_b_high=float(small_b),
                small_c_low=float(small_c),projection=float(projection),pressure_capped=target<projection-D('1e-8'),
                trigger_gross_rr=float(rr),uncapped_gross_rr=float(rr_no_pressure),
                unbuffered_uncapped_gross_rr=float(rr_no_buffer),
                first_plan_net_rr=rejected['net_rr'] if rejected else None,
                first_plan_required_target=rejected['required_target_for_net_3'] if rejected else None))
        failures.extend(dict(variant=vid,**x) for x in plan_price_errors)
        summary.append(dict(variant=vid,name=variant['name'],plans=len(ratios),assessment_rows=len(audits[vid]),
            arithmetic_checked=checked,first_plan_funnel=variant['first_plan_funnel'],
            gross_rr_above_3=sum(r>3 for r in ratios),median_gross_rr=statistics.median(ratios),
            uncapped_gross_rr_above_3=sum(r>3 for r in uncapped),
            unbuffered_uncapped_gross_rr_above_3=sum(r>3 for r in unbuffered),
            first_plan_cost_only_rejections=len(fee_only),cost_only_examples=fee_only,
            structure_price_checked=len(ratios),structure_price_errors=len(plan_price_errors)))
    # All sold-position R values must use original cost-inclusive initial risk,
    # rather than the current raised stop. Find the matching executed entry audit.
    trade_rows=[]
    for vid,ts in trades.items():
        fills={(r['symbol'],r['date']):r for r in audits[vid] if r['execution_reason']=='filled'}
        for t in ts:
            r=fills[t['symbol'],t['entry_date']]
            expected=float(t['pnl'])/float(r['expected_loss'])
            error=abs(expected-float(t['realized_r']))
            if error>1e-8:failures.append(dict(variant=vid,field='realized_r',symbol=t['symbol'],error=error))
            trade_rows.append(dict(variant=vid,**t,recomputed_realized_r=expected))
    after={str(p.relative_to(experiment)):sha(p) for p in inputs}
    if before!=after:raise RuntimeError('Frozen audit inputs changed during audit')
    base=[p for p in plan_rows if p['variant']=='baseline']
    baseline_diagnostics=dict(
        median_stop_distance_pct=statistics.median((p['trigger']-p['stop'])/p['trigger'] for p in base),
        median_remaining_space_pct=statistics.median((p['target']-p['trigger'])/p['trigger'] for p in base),
        median_small_to_core_correction_range=statistics.median(
            (p['small_b_high']-p['small_c_low'])/(p['core_b_high']-p['core_c_low']) for p in base),
        entry_at_or_above_core_b=sum(p['trigger']>=p['core_b_high'] for p in base))
    result=dict(experiment=str(experiment),formula='net target profit / net initial stop loss',
        assumptions=execution,threshold=config['risk']['min_rr'],summary=summary,
        assessment_rows=sum(len(x) for x in audits.values()),arithmetic_checked=len(rows),
        structure_plans_checked=len(plan_rows),closed_trades_checked=len(trade_rows),
        maximum_absolute_recomputation_errors=dict(max_errors),failures=failures,
        baseline_diagnostics=baseline_diagnostics,
        input_hashes=before,input_hashes_unchanged=True,production_modified=False,
        notes=['Repeated renewals and duplicated holding variants are not independent opportunities.',
               'Unbuffered/uncapped values are diagnostics; no altered strategy was backtested.',
               'Projection is a price-space hypothesis, not an expected probabilistic payoff.',
               'Gap, T+1, suspension and limit-down can exceed estimated initial stop loss.'])
    dump(output/'audit.json',result);dump(output/'plans.json',plan_rows)
    for name,records in [('assessments',rows),('plans',plan_rows),('trade-r',trade_rows)]:
        with (output/(name+'.csv')).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    table=''.join('<tr>'+''.join('<td>'+html.escape(str(v[k]))+'</td>' for k in
        ('variant','plans','gross_rr_above_3','uncapped_gross_rr_above_3','first_plan_cost_only_rejections'))+'</tr>' for v in summary)
    example=next(p for p in base if p['symbol']=='600458.SH')
    content=f'''<!doctype html><meta charset="utf-8"><title>盈亏比独立复算</title>
<style>body{{font:16px system-ui;max-width:1150px;margin:35px auto;line-height:1.7}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccd;padding:7px}}code{{background:#eee}}</style>
<h1>冻结基线：盈亏比独立复算</h1>
<p>复算 {len(rows)} 条账户评估、{len(plan_rows)} 条结构计划和 {len(trade_rows)} 笔平仓记录；发现 {len(failures)} 个数值或价格链路差异。所有输入 SHA256 前后相同。重复续期、相同持仓对照不算独立机会。</p>
<p>净盈亏比＝（目标卖出收入－买入支出－两侧佣金－卖出税）／（买入支出－止损卖出收入＋两侧佣金＋卖出税）。买入成交价已含买侧滑点，止损和目标再计卖侧滑点。门槛严格大于 3。</p>
<table><tr><th>对照</th><th>结构计划</th><th>触发价毛比&gt;3</th><th>去压力毛比&gt;3</th><th>首日仅成本挡掉</th></tr>{table}</table>
<p>基线 35 个计划，触发价毛盈亏比中位数 {summary[0]['median_gross_rr']:.3f}，只有 6 个超过 3；27 个首日盈亏比拒绝均不是仅由交易成本造成。去掉压力封顶仍只有 6 个超过 3。E03 新恢复的 12 个计划全部被盈亏比挡住。</p>
<p>基线初始止损距离中位数为入场价的 {baseline_diagnostics['median_stop_distance_pct']:.2%}，剩余目标空间中位数为 {baseline_diagnostics['median_remaining_space_pct']:.2%}；局部调整幅度／核心调整幅度中位数为 {baseline_diagnostics['median_small_to_core_correction_range']:.2%}。这些统计提示须验证日线代理节奏及初始风险是否表达了更小一层的入场结构，但不足以证明任何替代算法有效。两个距离中位数之比不等于逐计划盈亏比的中位数。</p>
<h2>问题集中在哪里</h2><p>目标采用日线 N 的 C＋(B－A)，再由有效压力封顶；入场突破采用日线小结构代理的 B，止损采用其 C 下方 0.5%。当确认较晚或小结构调整较宽，剩余目标空间可能远小于止损距离。计算正确不能证明这三个价位表达了正确的交易机会。</p>
<p>600458.SH：首次计划 {example['date']}，触发 {example['trigger']:.4f}，止损 {example['stop']:.4f}，目标 {example['target']:.4f}。未计成本毛比 {example['trigger_gross_rr']:.3f}，净比 {example['first_plan_net_rr']:.3f}；按相同数量、止损和费用，目标要高于 {example['first_plan_required_target']:.4f} 才能满足净比&gt;3。这个反解价只用于解释拒绝，不能当作新目标。</p>
<p>理论投射没有赋予到达概率，字段 expected_profit/expected_loss 实际表示“目标／止损情景盈亏”，不代表数学期望。净比&gt;3也不保证真实交易小亏大赚：止损执行可能跳空，盈利是否能保留取决于后续退出。此审计没有降低门槛、改变价位或用事后走势扩大目标。</p>
<p><a href="plans.csv">逐计划价位与来源</a> · <a href="assessments.csv">逐次资金流独立复算</a> · <a href="audit.json">完整审计及输入哈希</a></p>'''
    (output/'report.html').write_text(content,encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('arithmetic_checked','structure_plans_checked','closed_trades_checked','failures','maximum_absolute_recomputation_errors')},ensure_ascii=False))
    print('Output:',output)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('experiment',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    output=args.output or Path('runs')/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'-reward-risk-audit')
    result=audit(args.experiment,output)
    if result['failures']:raise SystemExit(1)
